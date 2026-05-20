#!/usr/bin/env python3
"""Fail CI if any SKILL.md description exceeds 900 chars (OnchainOS budget)."""
import re
import sys
from pathlib import Path


def main() -> int:
    failed = False
    for f in sorted(Path("skills").glob("*/SKILL.md")):
        text = f.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            print(f"{f}: no frontmatter")
            failed = True
            continue
        fm = m.group(1)
        dm = re.search(r'^description:\s*"((?:[^"\\]|\\.)*)"', fm, re.MULTILINE)
        if dm is None:
            dm = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
            if dm is None:
                print(f"{f}: NO description field")
                failed = True
                continue
        desc = dm.group(1)
        n = len(desc)
        status = "ok" if n <= 900 else "FAIL"
        print(f"{f}: {n} chars [{status}]")
        if n > 900:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
