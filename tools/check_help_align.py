#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check that the --help option column is aligned in every shipped language.

The help block is a hand-padded literal, so a wider glyph or a full-width
parenthesis silently pushes one description out of the column. This script
measures the display width (East Asian Wide = 2 columns) of every option row and
reports rows whose description does not start on the shared column.

Run:  python tools/check_help_align.py
"""

import sys as _sys

# These tools print translated strings, which are Chinese, Japanese or Korean on
# a machine whose console code page cannot represent them. Force UTF-8 so a
# finding is reported instead of turning into UnicodeEncodeError.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import re
import subprocess
import sys
import unicodedata

EXE = "dist/ExplorerF11.exe"
LANGS = ["zh", "zh-Hant", "en", "ja", "ko"]

# A row is "  --flag" or "  （なし）" followed by at least two spaces.
ROW = re.compile(r"^  (\S.*?)( {2,})(\S.*)$")


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def main():
    bad = 0
    for lang in LANGS:
        out = subprocess.run([EXE, "--help", "--lang", lang],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        rows = []
        for line in out.splitlines():
            m = ROW.match(line)
            if not m:
                continue
            # Skip the indented continuation paragraphs (6 spaces) and the
            # Examples block, whose padding is unrelated to the option column.
            if line.startswith("      "):
                continue
            if not m.group(1).startswith(("--", "(", "\uff08")):
                continue
            rows.append((m.group(1), width(m.group(1)) + width(m.group(2))))
        if not rows:
            print("%-8s no option rows found" % lang)
            bad += 1
            continue
        columns = sorted(set(c for _, c in rows))
        status = "ok" if len(columns) == 1 else "MISALIGNED"
        print("%-8s rows=%d columns=%s %s" % (lang, len(rows), columns, status))
        if len(columns) != 1:
            target = max(columns)
            for name, col in rows:
                if col != target:
                    print("         %-20s starts at %d, expected %d" % (name, col, target))
            bad += 1
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
