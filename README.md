# GTFOBins CLI Lookup Tool
This is a Python-based CLI interface for searching and exploring GTFOBins directly from the terminal.

This tool allows you to:
- Check if a command exists in GTFOBins
- View unprivileged exploitation techniques (default)
- Optionally fetch SUDO and SUID techniques on demand
- Process single commands, multiple commands, or full lists
- Export results to .txt files for later reference

---
## About GTFOBins

This project is built on top of the work from:
https://gtfobins.org/
"GTFOBins is a joint effort by Emilio Pinna and Andrea Cardaci, and many other contributors."

This CLI does not replace GTFOBins. It provides a terminal-based interface for faster access to their content.

---
## Features

### Lookup Modes
- Single command
- Comma-separated commands
- File-based input (.txt or .csv)

### Output Modes
- Detailed output for small queries
- Compact output for large lists
- Export full results to .txt

### Performance Behavior
- Fetches unprivileged data by default
- Fetches SUDO and SUID data only when requested
- Avoids excessive terminal output for large queries

### CLI Styling
- Colorized output for readability
- Structured sections mirroring GTFOBins layout

---
## Installation

Install dependencies:

pip install requests beautifulsoup4

Clone repository:

git clone https://github.com/prizmatik666/GTFObin_CLI_search

cd GTFObin_CLI_search

Run:

python3 gtfo.py

---
## Usage

### Mode 1 Direct Input

Enter command names directly.

Supports:
- Single command
- Multiple commands (comma-separated)

Example:

bash, python, awk

---
### Mode 2 File Input

Provide path to:
- .txt file (one command per line)
- .csv file (comma-separated values)

---
## Output Behavior

| Input Size | Behavior |
|------------|---------|
| 1 command  | Full detailed output |
| < 5 commands | Full output for each |
| > 5 commands | Compact summary |
| File input | Matching commands only |

For large lists, the CLI displays a notice that full details are available in the saved .txt output.

---
## Advanced Usage

by default, search results only show the 'unprivaledged' command examples in main result return
to keep the readout clean.
After a lookup, the user may optionally request:
- SUDO techniques
- SUID techniques

These are fetched only when selected to keep the main workflow fast.

---
## Saving Results

The tool provides prompts to save:
- Single command reports
- Multi-command reports
- Match-only lists

Output files are saved as:

<command>_gtfobins.txt

---
## Disclaimer

This tool is intended for:
- Educational use
- Capture The Flag environments
- Authorized penetration testing

Do not use this tool as an informational resource to exploit systems without permission.

---
## Contributing

This project complements GTFOBins and does not aim to replace it.
Infact, without GTFOBins this program would be useless ;)

Potential contributions:
- Improved parsing reliability
- Interactive result selection
- Output formatting improvements

---
## Keywords

gtfobins cli  
linux privilege escalation  
ctf enumeration tool  
sudo suid exploitation  
terminal gtfobins lookup  

---
## Roadmap

- Interactive selection mode for large results
- Offline caching
- JSON export support
- Text-based UI version

---
## Credit to GTFOBins for creating this helpful resource for the community!
---
GTFOBins creators:
- Emilio Pinna - https://x.com/norbemi
- Andrea Cardaci - https://x.com/cyrus_and
- Community contributors - https://github.com/GTFOBins/GTFOBins.github.io/graphs/contributors

https://gtfobins.org/

This project just provides a CLI interface to access their work more efficiently(for me at least, i make no claims of grandeur).
---
## Notes
If you find this useful, consider contributing or supporting the original GTFOBins project.
