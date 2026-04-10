# cc-clipclean

A tiny macOS background daemon that fixes terminal hard-wraps in the clipboard.

## What it does

When you Cmd+C text out of a terminal running Claude Code (or any terminal, really), the clipboard comes out hard-wrapped at the terminal column width with occasional stray leading-space artifacts:

```
When copying text from a Claude Code session in Terminal.app, the clipboard
comes out wrapped in CC's box-drawing frame chars ( ╭─│ ╰─), tool-call
markers (⏺), and other TUI decoration.
 Pasting anywhere else then requires manual cleanup.
```

`cc-clipclean` detects this pattern and rewrites the clipboard in place, so by the time you Cmd+V into a chat, doc, or email, you get clean paragraphs:

```
When copying text from a Claude Code session in Terminal.app, the clipboard comes out wrapped in CC's box-drawing frame chars ( ╭─│ ╰─), tool-call markers (⏺), and other TUI decoration.

Pasting anywhere else then requires manual cleanup.
```

It watches `NSPasteboard` directly, so it works across Terminal.app, iTerm2, the VSCode integrated terminal, Ghostty, etc. — anything that copies to the system pasteboard.

## How it works

1. A Python daemon (`cleaner.py`) polls `NSPasteboard.generalPasteboard().changeCount()` every 150 ms.
2. When the clipboard changes, it runs a sniffer (`is_hard_wrapped`) that asks: "are there any two consecutive prose lines where the first doesn't end in a sentence-terminator or structural punctuation?"
3. If yes, it runs the reformatter: unwrap soft-wrapped lines, strip single-space indent artifacts, insert paragraph breaks where previous lines end in `.!?:`, collapse multiple blank lines.
4. It writes the cleaned text back to the pasteboard and records its own `changeCount` to avoid a rewrite loop.

The daemon is launched by a `LaunchAgent` (`com.p.ccclipclean.plist`) with `RunAtLoad=true` + `KeepAlive=true`, so it starts automatically at login and restarts if it ever crashes.

## Files

```
cc-clipclean/
├── cleaner.py                            # the daemon + test mode
├── com.p.ccclipclean.plist.template      # LaunchAgent template (paths are filled in at install)
├── install.sh                            # one-shot installer
├── cleaner.log                           # daemon stdout/stderr (generated; gitignored)
├── com.p.ccclipclean.plist               # generated plist with your absolute paths (gitignored)
├── LICENSE
└── README.md
```

The generated plist is installed (copied) to `~/Library/LaunchAgents/com.p.ccclipclean.plist`.

## Install

```bash
git clone https://github.com/patrick0f/cc-clipclean.git
cd cc-clipclean
./install.sh
```

That:
1. Resolves your `python3` (override with `PYTHON=/path/to/python3 ./install.sh` if you want a specific one).
2. Installs `pyobjc-framework-Cocoa` into that Python.
3. Runs the self-test (10 fixtures).
4. Generates `com.p.ccclipclean.plist` from the template with your absolute paths.
5. Copies it to `~/Library/LaunchAgents/` and loads it with `launchctl`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.p.ccclipclean.plist
rm ~/Library/LaunchAgents/com.p.ccclipclean.plist
```

The project directory itself can stay or be deleted — nothing persists outside of it and the LaunchAgent file.

## License

MIT — see `LICENSE`.

## Stop / restart / logs

```bash
launchctl unload ~/Library/LaunchAgents/com.p.ccclipclean.plist   # stop
launchctl load   ~/Library/LaunchAgents/com.p.ccclipclean.plist   # start
launchctl list   | grep ccclipclean                               # status (pid, exit code)
tail -f ~/Documents/GitHub/cc-clipclean/cleaner.log               # logs
```

The log records one line per startup and one line per rewrite. It won't fill your disk unless you're copying thousands of times a day.

## Self-test

```bash
python3 ~/Documents/GitHub/cc-clipclean/cleaner.py --test
```

Runs 10 fixtures through the full sniffer + reformatter flow (same code path the daemon uses). Run this after any edit to `cleaner.py`.

## Will it accidentally reformat non-CC content?

**Yes, sometimes.** The detector is content-based, not app-based — it has no idea whether the copy came from Claude Code, `man`, an email, or a plain text file. Anything that looks like hard-wrapped prose is fair game.

### What *will* get rewritten

- Claude Code responses copied out of a terminal. ✓ (the goal)
- **Any** terminal program's multi-line prose output — `man` pages, `git log` bodies, `fortune`, `curl` + formatted text, etc. Usually this is still what you want.
- Hard-wrapped plaintext emails (e.g., copied from `mutt`, older mailing-list archives).
- Text files wrapped at 72/80 columns (old READMEs, commit messages with manual line breaks).
- Multi-line prose from a web page that was copied with soft line breaks.

### What is *explicitly protected*

The detector/reformatter skips content that looks structural rather than prose:

| Case | Protected by |
|---|---|
| Fenced code blocks (```) | Fence detection — preserved verbatim |
| Indented code (4+ spaces or tab) | `CODEY_INDENT` regex |
| Bulleted / numbered lists (`-`, `*`, `•`, `1.`) | `BULLET` regex |
| Markdown headings (`#`, `##`, …) | `HEADING` regex |
| Pretty-printed JSON / JS objects | Lines ending in `,`, `}`, `]` block merges; closing brackets alone on a line are detected as "structural-only" |
| CSV / TSV data | Lines are single-token (no spaces), so the sniffer doesn't fire |
| Function signatures across lines | Closing `)` blocks merging |
| Short single-line copies | Sniffer needs 2 consecutive lines |
| Text already ending every line with `.!?:;,}])` | Nothing looks soft-wrapped |

### Known false positives

| Case | What happens | Mitigation |
|---|---|---|
| Poetry, song lyrics, intentionally short lines | Lines get merged into paragraphs | Uncomment `reformat_safe` in `cleaner.py:main()` for that session |
| Plaintext email with 72-char hard wraps | Same as CC output — unwrapped into paragraphs | Usually desirable; otherwise use safe mode |
| Numbered list with no space after the digit (e.g., `1.foo`) | Sniffer may fire and merge | Edit the source to add the space after the period; rare in practice |
| A sentence containing an abbreviation like `U.S.` at a wrap boundary | The `.` is treated as a sentence terminator; the next line starts a new paragraph instead of merging | Very rare; manually join |

### Safe mode

If the unwrap is ever wrong for something you need to copy, swap to the safe fallback without uninstalling:

1. Open `cleaner.py`.
2. In `main()`, comment out `cleaned = reformat(text)` and uncomment `cleaned = reformat_safe(text)` (also uncomment the `reformat_safe` function definition above).
3. Reload: `launchctl unload … && launchctl load …`.

Safe mode only strips single-space leading indents on continuation lines and does **not** unwrap. It fixes the " mid-scrollback." artifact but leaves hard line breaks alone.


## Internals quick reference

| Constant / regex in `cleaner.py` | What it does |
|---|---|
| `POLL_INTERVAL = 0.15` | seconds between pasteboard polls |
| `TERMINATORS = ".!?:;"` | line-ending chars that trigger a paragraph break after unwrap |
| `DONT_MERGE = ".!?:;,}])\\"` | line-ending chars that block the next line from merging into this one |
| `BULLET` | matches `-`, `*`, `•`, `1.`, `2)` etc. — these lines are never merged into |
| `HEADING` | matches markdown `#`…`######` lines |
| `CODEY_INDENT` | matches 4+ leading spaces or a tab — treat as code, preserve |
| `FENCE` | matches ` ``` ` — toggles verbatim preservation of the enclosed block |
| `STRUCTURAL_ONLY` | matches lines that are only punctuation/brackets (`}`, `]`, `);`, etc.) — these don't get absorbed and don't count as prose |

## Change log

- **v1** — hard-wrap unwrap with fence / bullet / heading / indent / structural-brace protection; LaunchAgent; 10-fixture self-test; measured footprint.
