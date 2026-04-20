#!/usr/bin/env python3
"""
GTFOBins Lookup UI - v4 patched

Features
--------
- Single or comma-separated command lookup from mode 1
- File-path only loading for .txt / .csv in mode 2
- Consistent ANSI-colored UI
- Full unprivileged report for single and small multi lookups
- Optional SUDO / SUID follow-up fetch after single and small multi lookups
- Compact output for large lists with an explicit note that full details go in the saved .txt
- Input validation loops so invalid responses do not accidentally exit the program

Dependencies
------------
    pip install requests beautifulsoup4
"""

from __future__ import annotations

import csv
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("[!] Missing dependency. Install with:")
    print("    pip install requests beautifulsoup4")
    sys.exit(1)


BASE_URL = "https://gtfobins.org/"
INDEX_TIMEOUT = 20
DETAIL_TIMEOUT = 20
WRAP_WIDTH = 92
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# ANSI colors
RESET = "\033[0m"
WHITE = "\033[97m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
PINK = "\033[95m"
ORANGE = "\033[38;5;208m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


@dataclass
class SupportingBlock:
    title: str
    paragraphs: List[str] = field(default_factory=list)
    code_blocks: List[str] = field(default_factory=list)


@dataclass
class ExampleBlock:
    example_number: int
    comment_title: Optional[str] = None
    comment_text: Optional[str] = None
    context_intro: str = ""
    code_blocks: List[str] = field(default_factory=list)
    supporting_blocks: List[SupportingBlock] = field(default_factory=list)


@dataclass
class FunctionSection:
    name: str
    slug: str
    description: str = ""
    examples: List[ExampleBlock] = field(default_factory=list)


@dataclass
class CommandResult:
    term: str
    found: bool = False
    canonical_name: Optional[str] = None
    page_url: Optional[str] = None
    descriptors: List[str] = field(default_factory=list)
    unprivileged_sections: List[FunctionSection] = field(default_factory=list)
    sudo_sections: List[FunctionSection] = field(default_factory=list)
    suid_sections: List[FunctionSection] = field(default_factory=list)
    error: Optional[str] = None

    def display_name(self) -> str:
        return self.canonical_name or self.term


def prompt(msg: str) -> str:
    try:
        return input(msg)
    except EOFError:
        return ""


def sanitize_term(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    value = re.sub(r"\s+", " ", value)
    return value


def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def wrap_plain(text: str, indent: int = 0, subsequent: Optional[int] = None) -> List[str]:
    text = clean_text(text)
    if not text:
        return []
    first_indent = " " * indent
    later_indent = " " * (subsequent if subsequent is not None else indent)
    return textwrap.wrap(
        text,
        width=WRAP_WIDTH,
        initial_indent=first_indent,
        subsequent_indent=later_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def slugify_anchor(name: str) -> str:
    name = clean_text(name).lower()
    name = name.replace("/", " ")
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def get_direct_child(tag: Tag, name: str) -> Optional[Tag]:
    for child in tag.children:
        if isinstance(child, Tag) and child.name == name:
            return child
    return None


def get_direct_children(tag: Tag, name: str) -> List[Tag]:
    items: List[Tag] = []
    for child in tag.children:
        if isinstance(child, Tag) and child.name == name:
            items.append(child)
    return items


def colorize_code_line(line: str, command_name: str) -> str:
    """
    Entire command line is orange by default.
    Exact matches of the searched/found command name are green.
    After each green match, orange is re-applied so the rest of the line
    stays orange rather than falling back to terminal default.
    """
    if not line:
        return ""
    if not command_name:
        return c(line, ORANGE)

    pattern = re.compile(rf"(?<![\w./-])({re.escape(command_name)})(?![\w./-])", re.IGNORECASE)

    parts: List[str] = []
    last = 0
    for match in pattern.finditer(line):
        if match.start() > last:
            parts.append(c(line[last:match.start()], ORANGE))
        parts.append(c(match.group(1), GREEN))
        last = match.end()
    if last < len(line):
        parts.append(c(line[last:], ORANGE))
    if not parts:
        return c(line, ORANGE)
    return "".join(parts)


class GTFOBinsClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self._index_map: Optional[Dict[str, Dict[str, object]]] = None

    def load_index(self, force_refresh: bool = False) -> Dict[str, Dict[str, object]]:
        if self._index_map is not None and not force_refresh:
            return self._index_map

        resp = self.session.get(BASE_URL, timeout=INDEX_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        index: Dict[str, Dict[str, object]] = {}
        for row in soup.select("tr[data-gtfobin-name]"):
            if not isinstance(row, Tag):
                continue

            name = clean_text(row.get("data-gtfobin-name", ""))
            if not name:
                continue

            link_tag = row.select_one("a.bin-name")
            if not isinstance(link_tag, Tag):
                continue

            href = link_tag.get("href", "")
            page_url = urljoin(BASE_URL, href)

            descriptors: List[str] = []
            for item in row.select("ul.tag-list li[data-function-name]"):
                if not isinstance(item, Tag):
                    continue
                label = clean_text(item.get("data-function-name", "") or item.get_text(" ", strip=True))
                if label and label not in descriptors:
                    descriptors.append(label)

            index[name.lower()] = {
                "canonical_name": name,
                "page_url": page_url,
                "descriptors": descriptors,
            }

        self._index_map = index
        return index

    def lookup(self, term: str, include_details: bool = True) -> CommandResult:
        cleaned = sanitize_term(term)
        result = CommandResult(term=cleaned)

        if not cleaned:
            return result

        index = self.load_index()
        entry = index.get(cleaned.lower())
        if not entry:
            return result

        result.found = True
        result.canonical_name = str(entry["canonical_name"])
        result.page_url = str(entry["page_url"])
        result.descriptors = list(entry.get("descriptors", []))

        if include_details:
            try:
                sections_by_context = self.fetch_sections_by_context(result.page_url, contexts=("unprivileged",))
                result.unprivileged_sections = sections_by_context.get("unprivileged", [])
            except Exception as exc:  # noqa: BLE001
                result.error = f"Failed to fetch detail page: {exc}"

        return result

    def fetch_optional_contexts(self, result: CommandResult, contexts: Tuple[str, ...]) -> None:
        if not result.found or not result.page_url:
            return
        section_map = self.fetch_sections_by_context(result.page_url, contexts=contexts)
        if "sudo" in contexts:
            result.sudo_sections = section_map.get("sudo", [])
        if "suid" in contexts:
            result.suid_sections = section_map.get("suid", [])

    def fetch_sections_by_context(
        self,
        url: str,
        contexts: Tuple[str, ...] = ("unprivileged",),
    ) -> Dict[str, List[FunctionSection]]:
        wanted = {ctx.lower() for ctx in contexts}
        resp = self.session.get(url, timeout=DETAIL_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results: Dict[str, List[FunctionSection]] = {ctx: [] for ctx in wanted}

        for heading in soup.select("h2.function-name"):
            if not isinstance(heading, Tag):
                continue

            function_name = clean_text(heading.get_text(" ", strip=True)).replace("┬╢", "").strip()
            slug = heading.get("id", "") or slugify_anchor(function_name)

            description_parts: List[str] = []
            cursor = heading.next_sibling
            examples_ul: Optional[Tag] = None

            while cursor is not None:
                if isinstance(cursor, Tag):
                    if cursor.name == "h2":
                        break
                    if cursor.name in ("ul", "ol") and "examples" in (cursor.get("class") or []):
                        examples_ul = cursor
                        break
                    if cursor.name == "p":
                        text = clean_text(cursor.get_text(" ", strip=True))
                        if text:
                            description_parts.append(text)
                cursor = cursor.next_sibling

            if not isinstance(examples_ul, Tag):
                continue

            parsed = self._parse_examples_for_contexts(examples_ul, wanted)
            for ctx_name, examples in parsed.items():
                if examples:
                    results[ctx_name].append(
                        FunctionSection(
                            name=function_name,
                            slug=slug,
                            description=" ".join(description_parts).strip(),
                            examples=examples,
                        )
                    )

        return results

    def _parse_examples_for_contexts(
        self,
        examples_ul: Tag,
        wanted_contexts: set[str],
    ) -> Dict[str, List[ExampleBlock]]:
        out: Dict[str, List[ExampleBlock]] = {ctx: [] for ctx in wanted_contexts}

        example_items = get_direct_children(examples_ul, "li")
        for example_index, example_li in enumerate(example_items, start=1):
            comment_title, comment_text = self._parse_comment_fieldset(example_li)
            contexts_div = get_direct_child(example_li, "div")
            if not isinstance(contexts_div, Tag) or "contexts" not in (contexts_div.get("class") or []):
                continue

            context_map = self._extract_context_panels(contexts_div)
            post_blocks = self._parse_supporting_fieldsets(example_li)

            for ctx_name in wanted_contexts:
                panel = context_map.get(ctx_name)
                if not isinstance(panel, Tag):
                    continue

                intro = self._extract_first_direct_paragraph(panel)
                code_blocks = self._extract_direct_pre_code_blocks(panel)
                out[ctx_name].append(
                    ExampleBlock(
                        example_number=example_index,
                        comment_title=comment_title,
                        comment_text=comment_text,
                        context_intro=intro,
                        code_blocks=code_blocks,
                        supporting_blocks=post_blocks,
                    )
                )

        return out

    def _parse_comment_fieldset(self, example_li: Tag) -> Tuple[Optional[str], Optional[str]]:
        for child in example_li.children:
            if isinstance(child, Tag) and child.name == "fieldset":
                legend = child.find("legend")
                legend_text = clean_text(legend.get_text(" ", strip=True)) if isinstance(legend, Tag) else ""
                if legend_text.lower() == "comment":
                    paragraphs = [
                        clean_text(p.get_text(" ", strip=True))
                        for p in child.find_all("p")
                        if clean_text(p.get_text(" ", strip=True))
                    ]
                    return legend_text, " ".join(paragraphs).strip() or None
            if isinstance(child, Tag) and child.name == "div" and "contexts" in (child.get("class") or []):
                break
        return None, None

    def _parse_supporting_fieldsets(self, example_li: Tag) -> List[SupportingBlock]:
        blocks: List[SupportingBlock] = []
        seen_contexts = False

        for child in example_li.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "div" and "contexts" in (child.get("class") or []):
                seen_contexts = True
                continue
            if not seen_contexts or child.name != "fieldset":
                continue

            legend = child.find("legend")
            title = clean_text(legend.get_text(" ", strip=True)) if isinstance(legend, Tag) else "Notes"
            paragraphs = [
                clean_text(p.get_text(" ", strip=True))
                for p in child.find_all("p")
                if clean_text(p.get_text(" ", strip=True))
            ]
            code_blocks = [
                clean_text(code.get_text("\n", strip=True))
                for code in child.select("pre > code")
                if clean_text(code.get_text("\n", strip=True))
            ]
            blocks.append(SupportingBlock(title=title or "Notes", paragraphs=paragraphs, code_blocks=code_blocks))

        return blocks

    def _extract_context_panels(self, contexts_div: Tag) -> Dict[str, Tag]:
        panels: Dict[str, Tag] = {}
        children = [child for child in contexts_div.children if isinstance(child, Tag)]

        for idx, child in enumerate(children):
            if child.name != "label":
                continue
            label_text = clean_text(child.get_text(" ", strip=True)).lower()
            if label_text not in {"unprivileged", "sudo", "suid"}:
                continue
            panel: Optional[Tag] = None
            if idx + 1 < len(children) and children[idx + 1].name == "div":
                panel = children[idx + 1]
            if isinstance(panel, Tag):
                panels[label_text] = panel

        return panels

    def _extract_first_direct_paragraph(self, panel: Tag) -> str:
        for child in panel.children:
            if isinstance(child, Tag) and child.name == "p":
                return clean_text(child.get_text(" ", strip=True))
        return ""

    def _extract_direct_pre_code_blocks(self, panel: Tag) -> List[str]:
        blocks: List[str] = []
        for child in panel.children:
            if isinstance(child, Tag) and child.name == "pre":
                code = child.find("code")
                if isinstance(code, Tag):
                    text = clean_text(code.get_text("\n", strip=True))
                    if text:
                        blocks.append(text)
        return blocks


def parse_terms_from_text_file(path: Path) -> List[str]:
    terms: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            value = sanitize_term(line)
            if value:
                terms.append(value)
    return dedupe_keep_order(terms)


def parse_terms_from_csv(path: Path) -> List[str]:
    terms: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            for cell in row:
                value = sanitize_term(cell)
                if value:
                    terms.append(value)
    return dedupe_keep_order(terms)


def parse_manual_terms(raw: str) -> List[str]:
    if not raw.strip():
        return []
    if "," in raw:
        parts = [sanitize_term(x) for x in raw.split(",")]
    else:
        parts = [sanitize_term(x) for x in raw.split()]
    return dedupe_keep_order([x for x in parts if x])


def choose_input_mode() -> str:
    print("\n" + c("=" * WRAP_WIDTH, YELLOW))
    print(c("GTFOBins Lookup", WHITE))
    print(c("=" * WRAP_WIDTH, YELLOW))
    print(f"{c('1)', RED)} {c('Enter command name(s) directly ΓÇö single term or comma-separated multiple terms', WHITE)}")
    print(f"{c('2)', RED)} {c('Load command names from file path only (.txt or .csv)', WHITE)}")
    print(f"{c('4)', RED)} {c('Refresh GTFOBins index cache', WHITE)}")
    print(f"{c('Q)', RED)} {c('Quit', WHITE)}")
    return prompt(f"{c('Select mode:', WHITE)} ").strip().lower()


def get_terms_for_mode(mode: str) -> Tuple[List[str], str]:
    if mode == "1":
        raw = prompt(f"{c('Enter command name(s):', WHITE)} ")
        terms = parse_manual_terms(raw)
        return terms, "single_or_manual"

    if mode == "2":
        path = Path(prompt(f"{c('Enter path to .txt or .csv file:', WHITE)} ").strip().strip('"'))
        if not path.exists() or not path.is_file():
            print(c("[!] File not found.", RED))
            return [], "invalid"
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return parse_terms_from_text_file(path), "file"
        if suffix == ".csv":
            return parse_terms_from_csv(path), "file"
        print(c("[!] Unsupported file type. Use .txt or .csv", RED))
        return [], "invalid"

    return [], "invalid"


def build_single_context_report(
    result: CommandResult,
    context_name: str,
    sections: List[FunctionSection],
) -> str:
    lines: List[str] = []
    display = result.display_name()
    banner = c("=" * WRAP_WIDTH, YELLOW)

    lines.append(banner)
    lines.append(f"{c('GTFOBins Report ::', WHITE)} {c(display, GREEN)}")
    lines.append(banner)
    lines.append(f"{c('Command :', WHITE)} {c(display, GREEN)}")
    lines.append(f"{c('Found   :', WHITE)} {c('yes' if result.found else 'no', WHITE)}")

    if result.found:
        uses = ", ".join(result.descriptors) if result.descriptors else "[none listed]"
        lines.append(f"{c('Uses    :', WHITE)} {c(uses, WHITE)}")
        lines.append(f"{c('Mode    :', WHITE)} {c(context_name.upper(), WHITE)}")
        lines.append("")

    if not result.found:
        lines.append(banner)
        return "\n".join(lines)

    if not sections:
        lines.append(c(f"[No {context_name} entries were parsed from the command page.]", WHITE))
        lines.append("")
        lines.append(c("Page:", RED))
        lines.append(f"  {result.page_url}")
        if result.error:
            lines.append(f"{c('Note:', YELLOW)} {c(result.error, WHITE)}")
        lines.append(banner)
        return "\n".join(lines)

    for section_index, section in enumerate(sections, start=1):
        lines.append(c("-" * WRAP_WIDTH, YELLOW))
        lines.append(f"{c(f'[{section_index}]', RED)} {c(section.name, GREEN if section.name.lower() == display.lower() else WHITE)}")
        if section.description:
            for ln in wrap_plain(section.description, indent=4):
                lines.append(c(ln, WHITE))
        lines.append("")

        for example in section.examples:
            lines.append(f"    {c(f'Example {example.example_number}', RED)}")
            if example.comment_text:
                wrapped = wrap_plain(f"{example.comment_title or 'Comment'}: {example.comment_text}", indent=8)
                if wrapped:
                    first = wrapped[0]
                    label = f"{example.comment_title or 'Comment'}:"
                    if label in first:
                        first = first.replace(label, c(label, YELLOW), 1)
                    lines.append(c(first, WHITE).replace(c(label, YELLOW), c(label, YELLOW)))
                    for more in wrapped[1:]:
                        lines.append(c(more, WHITE))
            if example.context_intro:
                for ln in wrap_plain(example.context_intro, indent=8):
                    lines.append(c(ln, WHITE))
            if example.code_blocks:
                for code_idx, code in enumerate(example.code_blocks, start=1):
                    label = "Command" if len(example.code_blocks) == 1 else f"Command {code_idx}"
                    lines.append(f"        {c(label + ':', YELLOW)}")
                    for code_line in code.splitlines():
                        lines.append(" " * 12 + colorize_code_line(code_line, display))
            for sup in example.supporting_blocks:
                lines.append(f"        {c(sup.title + ':', YELLOW)}")
                for para in sup.paragraphs:
                    for ln in wrap_plain(para, indent=12):
                        lines.append(c(ln, WHITE))
                for code_idx, code in enumerate(sup.code_blocks, start=1):
                    code_label = "Code" if len(sup.code_blocks) == 1 else f"Code {code_idx}"
                    lines.append(f"            {c(code_label + ':', YELLOW)}")
                    for code_line in code.splitlines():
                        lines.append(" " * 16 + colorize_code_line(code_line, display))
            lines.append("")

    lines.append(c("Page:", RED))
    lines.append(f"  {result.page_url}")
    if result.error:
        lines.append(f"{c('Note:', YELLOW)} {c(result.error, WHITE)}")
    lines.append(banner)
    return "\n".join(lines)


def format_single_result_text(result: CommandResult) -> str:
    return build_single_context_report(result, "unprivileged", result.unprivileged_sections)


def print_single_result(result: CommandResult) -> None:
    print()
    print(format_single_result_text(result))


def format_compact_results_text(results: List[CommandResult]) -> str:
    return "\n".join(f"{r.display_name()} -> match({'yes' if r.found else 'no'})" for r in results)


def print_compact_results(results):
    print()
    for result in results:
        status = "yes" if result.found else "no"
        print(f"{c(result.display_name(), GREEN)} {c('->', WHITE)} {c(f'match({status})', WHITE)}")

    print()
    print(c("[ Full command information will be in the saved .txt file if you choose to save it. ]", RED))

def format_matches_only_text(results: List[CommandResult]) -> str:
    matches = [r.display_name() for r in results if r.found]
    return "\n".join(matches) if matches else "[no matches found]"


def format_multi_full_info(results: List[CommandResult]) -> str:
    parts: List[str] = []
    for result in results:
        parts.append(format_single_result_text(result))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def save_text_file(default_hint: str, content: str) -> None:
    while True:
        filename = prompt(f"{c('Output filename', WHITE)} {c(f'({default_hint})', PINK)}: ").strip()
        if not filename:
            print(c("[!] Save cancelled.", RED))
            return
        out_path = Path(filename).expanduser()
        try:
            out_path.write_text(content, encoding="utf-8")
            print(f"{c('[+]', GREEN)} {c('Saved:', WHITE)} {out_path}")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"{c('[!]', RED)} {c(f'Failed to save file: {exc}', WHITE)}")


def ask_yes_no(msg: str, default_no: bool = True) -> bool:
    while True:
        suffix = "(y/N)" if default_no else "(Y/n)"
        value = prompt(f"{c(msg, WHITE)} {c(suffix, PINK)}: ").strip().lower()
        if value == "":
            return not default_no
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print(c("[!] Invalid input. Enter y or n.", RED))


def maybe_save_single_result(result: CommandResult) -> None:
    if ask_yes_no("Save .txt of result?"):
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", result.display_name())
        save_text_file(f"{safe_name}_gtfobins.txt", format_single_result_text(result))


def maybe_save_multi_matches(results: List[CommandResult]) -> None:
    if ask_yes_no("Save list of matches to a .txt file?"):
        save_text_file("gtfobins_matches.txt", format_matches_only_text(results))


def maybe_save_full_info(results: List[CommandResult]) -> None:
    if ask_yes_no("Save .txt with full info?"):
        save_text_file("gtfobins_full_results.txt", format_multi_full_info(results))


def select_result_from_small_multi(results: List[CommandResult]) -> Optional[CommandResult]:
    matches = [r for r in results if r.found]
    if not matches:
        print(c("[!] No matched commands available for follow-up context.", RED))
        return None

    print()
    print(c("Matched commands:", WHITE))
    for idx, result in enumerate(matches, start=1):
        print(f"{c(str(idx) + ')', RED)} {c(result.display_name(), GREEN)}")

    while True:
        raw = prompt(f"{c('Select command number or N to skip:', WHITE)} ").strip().lower()
        if raw in {"", "n", "no"}:
            return None
        if raw.isdigit():
            num = int(raw)
            if 1 <= num <= len(matches):
                return matches[num - 1]
        print(c("[!] Invalid selection.", RED))


def ask_followup_contexts(client: GTFOBinsClient, result: CommandResult) -> None:
    if not result.found or not result.page_url:
        return

    print()
    print(c("Additional view options:", WHITE))
    print(f"  {c('1)', RED)} {c('Show SUDO entries', WHITE)}")
    print(f"  {c('2)', RED)} {c('Show SUID entries', WHITE)}")
    print(f"  {c('3)', RED)} {c('Show both SUDO + SUID', WHITE)}")
    print(f"  {c('N)', RED)} {c('Skip', WHITE)}")

    while True:
        choice = prompt(f"{c('Select follow-up view:', WHITE)} ").strip().lower()
        if choice in {"n", "no", ""}:
            return
        if choice in {"1", "2", "3"}:
            break
        print(c("[!] Invalid selection.", RED))

    wanted: List[str] = []
    if choice in {"1", "3"}:
        wanted.append("sudo")
    if choice in {"2", "3"}:
        wanted.append("suid")

    print(c("[*] Fetching additional context from command page...", WHITE))
    try:
        client.fetch_optional_contexts(result, tuple(wanted))
    except Exception as exc:  # noqa: BLE001
        print(f"{c('[!]', RED)} {c(f'Failed to fetch extra context: {exc}', WHITE)}")
        return

    if "sudo" in wanted:
        report = build_single_context_report(result, "sudo", result.sudo_sections)
        print()
        print(report)
        if ask_yes_no("Save SUDO report to .txt?"):
            safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", result.display_name())
            save_text_file(f"{safe_name}_sudo_gtfobins.txt", report)

    if "suid" in wanted:
        report = build_single_context_report(result, "suid", result.suid_sections)
        print()
        print(report)
        if ask_yes_no("Save SUID report to .txt?"):
            safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", result.display_name())
            save_text_file(f"{safe_name}_suid_gtfobins.txt", report)


def handle_small_multi_followup(client: GTFOBinsClient, results: List[CommandResult]) -> None:
    matches = [r for r in results if r.found]
    if not matches:
        return

    print()
    print(c("Additional view options for small multi results:", WHITE))
    print(f"  {c('1)', RED)} {c('Choose one matched command and show SUDO/SUID entries', WHITE)}")
    print(f"  {c('N)', RED)} {c('Skip', WHITE)}")

    while True:
        choice = prompt(f"{c('Select follow-up view:', WHITE)} ").strip().lower()
        if choice in {"", "n", "no"}:
            return
        if choice == "1":
            picked = select_result_from_small_multi(results)
            if picked is not None:
                ask_followup_contexts(client, picked)
            return
        print(c("[!] Invalid selection.", RED))


def run_lookup(client: GTFOBinsClient, terms: List[str], origin: str) -> None:
    if not terms:
        print(c("[!] No terms to search.", RED))
        return

    if len(terms) == 1:
        result = client.lookup(terms[0], include_details=True)
        print_single_result(result)
        maybe_save_single_result(result)
        ask_followup_contexts(client, result)
        return

    include_details = len(terms) < 5
    results: List[CommandResult] = []

    print(f"\n{c('[*]', WHITE)} {c(f'Searching {len(terms)} term(s) against GTFOBins...', WHITE)}")
    for idx, term in enumerate(terms, start=1):
        print(f"    {c(f'[{idx}/{len(terms)}]', RED)} {c(term, GREEN)}")
        results.append(client.lookup(term, include_details=include_details))
        time.sleep(0.05)

    if origin == "file":
        matches = [r for r in results if r.found]
        print("\n" + c("Matching commands:", WHITE))
        if matches:
            for item in matches:
                print(f"  - {c(item.display_name(), GREEN)}")
        else:
            print(c("  [none]", WHITE))
        maybe_save_multi_matches(results)
        return

    if len(terms) < 5:
        print()
        for result in results:
            print(format_single_result_text(result))
            print()
        maybe_save_full_info(results)
        handle_small_multi_followup(client, results)
    else:
        print_compact_results(results)
        maybe_save_full_info(results)


def main() -> None:
    client = GTFOBinsClient()

    while True:
        choice = choose_input_mode()

        if choice == "q":
            print(c("Bye.", WHITE))
            break

        if choice == "4":
            try:
                client.load_index(force_refresh=True)
                print(f"{c('[+]', GREEN)} {c('GTFOBins index cache refreshed.', WHITE)}")
            except Exception as exc:  # noqa: BLE001
                print(f"{c('[!]', RED)} {c(f'Failed to refresh index: {exc}', WHITE)}")

            if not ask_yes_no("Another search?"):
                print(c("Bye.", WHITE))
                break
            continue

        if choice not in {"1", "2"}:
            print(c("[!] Invalid selection.", RED))
            continue

        try:
            terms, origin = get_terms_for_mode(choice)
            run_lookup(client, terms, origin)
        except requests.RequestException as exc:
            print(f"{c('[!]', RED)} {c(f'Network error: {exc}', WHITE)}")
        except KeyboardInterrupt:
            print("\n" + c("[!] Cancelled by user.", RED))
        except Exception as exc:  # noqa: BLE001
            print(f"{c('[!]', RED)} {c(f'Unexpected error: {exc}', WHITE)}")

        if not ask_yes_no("Another search?"):
            print(c("Bye.", WHITE))
            break


if __name__ == "__main__":
    main()
