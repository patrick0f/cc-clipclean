#!/usr/bin/env python3
"""cc-clipclean — clipboard-watcher daemon that unwraps terminal hard-wraps."""
import re
import sys
import time

POLL_INTERVAL = 0.15            # seconds between NSPasteboard.changeCount checks
TERMINATORS = ".!?:;"           # ends a sentence → insert paragraph break
DONT_MERGE = ".!?:;,}])\\"      # ends a line that shouldn't absorb the next line
BULLET = re.compile(r"^(\s*)([-*•]|\d+[.)])\s")
HEADING = re.compile(r"^(\s*)#{1,6}\s")
CODEY_INDENT = re.compile(r"^(\s{4,}|\t)")
FENCE = re.compile(r"^\s*```")
STRUCTURAL_ONLY = re.compile(r"^[^\w\s]+$")   # only punctuation/brackets (e.g. "}", "]);")


def is_hard_wrapped(text: str) -> bool:
    lines = text.splitlines()
    for i in range(1, len(lines)):
        prev, cur = lines[i - 1], lines[i]
        if not prev.strip() or not cur.strip():
            continue
        if prev.rstrip()[-1:] in DONT_MERGE:
            continue
        if " " not in prev.strip():  # single-token line — not prose
            continue
        if STRUCTURAL_ONLY.match(cur.strip()):  # cur is "}", "]", etc. — structural
            continue
        if BULLET.match(cur) or HEADING.match(cur) or CODEY_INDENT.match(cur):
            continue
        return True
    return False


def _strip_cc_indent(line: str) -> str:
    # single leading space is a CC wrap artifact; double+ may be intentional
    if line.startswith(" ") and not line.startswith("  "):
        return line[1:]
    return line


def reformat(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or CODEY_INDENT.match(line):
            out.append(line)
            continue
        if not line.strip():
            out.append("")
            continue
        if not out or not out[-1].strip():
            out.append(_strip_cc_indent(line))
            continue
        prev = out[-1]
        # never merge a regular line into a code-indented previous line
        if CODEY_INDENT.match(prev):
            out.append(line)
            continue
        if BULLET.match(line) or HEADING.match(line):
            out.append(line)
            continue
        prev_end = prev.rstrip()[-1:]
        if prev_end in TERMINATORS:
            out.append("")
            out.append(_strip_cc_indent(line))
            continue
        if prev_end in DONT_MERGE:
            out.append(line)
            continue
        if " " not in prev.strip():  # single-token prev — not prose, don't merge
            out.append(line)
            continue
        if STRUCTURAL_ONLY.match(line.strip()):  # cur is "}", "]);", etc. — don't absorb
            out.append(line)
            continue
        out[-1] = prev.rstrip() + " " + line.lstrip()

    result: list[str] = []
    prev_blank = False
    for l in out:
        blank = not l.strip()
        if blank and prev_blank:
            continue
        result.append(l)
        prev_blank = blank
    return "\n".join(result).strip("\n")


# def reformat_safe(text: str) -> str:
#     """Fallback: strip only single-space leading indents on continuation lines,
#        don't unwrap. Swap into main() if unwrap proves too aggressive."""
#     lines = text.splitlines()
#     out = []
#     for i, line in enumerate(lines):
#         if i > 0 and lines[i - 1].strip() and line.startswith(" ") and not line.startswith("  "):
#             out.append(line[1:])
#         else:
#             out.append(line)
#     return "\n".join(out)


FIXTURE_INPUT = (
    "When copying text from a Claude Code session in Terminal.app, the clipboard\n"
    "comes out wrapped in CC's box-drawing frame chars ( ╭─│ ╰─), tool-call\n"
    "markers (⏺), and other TUI decoration.\n"
    " Pasting anywhere else then requires manual cleanup. CC has a /copy command\n"
    "for the last message, but that's inconvenient when you want to copy a portion of a\n"
    "response, or anything\n"
    " mid-scrollback."
)

FIXTURE_EXPECTED = (
    "When copying text from a Claude Code session in Terminal.app, the clipboard "
    "comes out wrapped in CC's box-drawing frame chars ( ╭─│ ╰─), tool-call "
    "markers (⏺), and other TUI decoration.\n"
    "\n"
    "Pasting anywhere else then requires manual cleanup. CC has a /copy command "
    "for the last message, but that's inconvenient when you want to copy a portion of a "
    "response, or anything mid-scrollback."
)


def _daemon_pass(text: str) -> str:
    """Simulate the full daemon flow: sniffer-gate + reformat."""
    if not is_hard_wrapped(text):
        return text
    return reformat(text)


def run_tests() -> int:
    failures = 0

    def check_daemon(name: str, got: str, want: str) -> None:
        nonlocal failures
        if got == want:
            print(f"PASS  {name}")
        else:
            failures += 1
            print(f"FAIL  {name}")
            print("  got:")
            for l in got.splitlines():
                print(f"    | {l!r}")
            print("  want:")
            for l in want.splitlines():
                print(f"    | {l!r}")

    # 1. The user's actual paste fixture
    assert is_hard_wrapped(FIXTURE_INPUT), "fixture should be detected as hard-wrapped"
    check_daemon("user fixture", _daemon_pass(FIXTURE_INPUT), FIXTURE_EXPECTED)

    # 2. Already-clean prose passes through unchanged
    clean = "This is a single line.\n\nThis is another paragraph."
    assert not is_hard_wrapped(clean), "clean text should not trigger sniffer"
    check_daemon("clean passthrough", _daemon_pass(clean), clean)

    # 3. Fenced code block preserved verbatim
    fenced = (
        "Here's some code:\n\n"
        "```python\n"
        "def foo():\n"
        "    return 42\n"
        "```\n\n"
        "Done."
    )
    check_daemon("fenced code preserved", _daemon_pass(fenced), fenced)

    # 4. Bullet lists stay on their own lines
    bullets = (
        "Here are options:\n"
        "- first item\n"
        "- second item\n"
        "- third item"
    )
    check_daemon("bullet list preserved", _daemon_pass(bullets), bullets)

    # 5. Indented code (4+ spaces) preserved
    indented = (
        "Look at this:\n"
        "    some code line\n"
        "    more code\n"
        "End."
    )
    check_daemon("indented code preserved", _daemon_pass(indented), indented)

    # 6. Short one-liner untouched
    short = "hello world"
    assert not is_hard_wrapped(short)
    check_daemon("short passthrough", _daemon_pass(short), short)

    # 7. Pretty-printed JSON with 2-space indent — must not merge lines
    json_pretty = (
        '{\n'
        '  "name": "alice",\n'
        '  "age": 30,\n'
        '  "tags": ["a", "b"]\n'
        '}'
    )
    check_daemon("json 2-space indent preserved", _daemon_pass(json_pretty), json_pretty)

    # 8. CSV — every line ends in a non-terminator, but comma blocks merge
    csv = (
        "id,name,age\n"
        "1,alice,30\n"
        "2,bob,25\n"
        "3,carol,40"
    )
    check_daemon("csv preserved", _daemon_pass(csv), csv)

    # 9. Function signature wrapping — closing paren blocks merge
    sig = (
        "def do_thing(\n"
        "    arg_one,\n"
        "    arg_two,\n"
        ")"
    )
    check_daemon("function signature preserved", _daemon_pass(sig), sig)

    # 10. Minimal JSON without trailing commas — closing brace must stay put
    json_simple = (
        '{\n'
        '  "name": "alice",\n'
        '  "age": 30\n'
        '}'
    )
    check_daemon("minimal json preserved", _daemon_pass(json_simple), json_simple)

    print()
    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILED'}")
    return failures


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        sys.exit(run_tests())

    from AppKit import NSPasteboard, NSStringPboardType  # type: ignore

    pb = NSPasteboard.generalPasteboard()
    last_count = pb.changeCount()
    print(f"[cc-clipclean] watching pasteboard (start changeCount={last_count})", flush=True)
    while True:
        time.sleep(POLL_INTERVAL)
        count = pb.changeCount()
        if count == last_count:
            continue
        last_count = count
        text = pb.stringForType_(NSStringPboardType)
        if not text or not is_hard_wrapped(text):
            continue
        cleaned = reformat(text)
        # cleaned = reformat_safe(text)  # uncomment for safe-mode fallback
        if cleaned == text:
            continue
        pb.clearContents()
        pb.setString_forType_(cleaned, NSStringPboardType)
        last_count = pb.changeCount()
        print(f"[cc-clipclean] rewrote clipboard ({len(text)}→{len(cleaned)} chars)", flush=True)


if __name__ == "__main__":
    main()
