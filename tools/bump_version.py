#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bump the version everywhere it is stated, then stop for a human decision.

    python tools/bump_version.py 1.0.3

It rewrites every version-derived string in tracked files and seeds a new
CHANGELOG entry. It deliberately does NOT touch historical CHANGELOG sections,
the release notes of an older release, or any SHA-256: a new version means a new
binary, and that hash must come from the new build via ``make refresh-facts``
and the release checklist, never from a guess.
"""

import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_REPLACEMENTS = (
    ("src/app.h", [(r'(?m)^#define EF11_VERSION +L"[^"]+"$',
                    lambda v: '#define EF11_VERSION      L"%s"' % v)]),
    ("src/app.rc", [
        (r"(?m)^ FILEVERSION +[\d,]+\s*$", lambda v: " FILEVERSION    %s,0" % v.replace(".", ",")),
        (r"(?m)^ PRODUCTVERSION +[\d,]+\s*$", lambda v: " PRODUCTVERSION %s,0" % v.replace(".", ",")),
        (r'"\d+\.\d+\.\d+\.0"', lambda v: '"%s.0"' % v),
    ]),
    (".github/workflows/build.yml", [
        (r'findstr /C:"ExplorerF11 \d+\.\d+\.\d+"',
         lambda v: 'findstr /C:"ExplorerF11 %s"' % v),
    ]),
    ("README.md", [
        (r"ExplorerF11-\d+\.\d+\.\d+-win64\.exe", lambda v: "ExplorerF11-%s-win64.exe" % v),
    ]),
    ("README.zh-CN.md", [
        (r"ExplorerF11-\d+\.\d+\.\d+-win64\.exe", lambda v: "ExplorerF11-%s-win64.exe" % v),
    ]),
    ("SECURITY.md", [
        (r"ExplorerF11-\d+\.\d+\.\d+-win64\.exe", lambda v: "ExplorerF11-%s-win64.exe" % v),
        (r"# ExplorerF11 \d+\.\d+\.\d+", lambda v: "# ExplorerF11 %s" % v),
        (r"# \d+\.\d+\.\d+\.0", lambda v: "# %s.0" % v),
    ]),
    ("docs/USAGE.en.md", [
        (r"ExplorerF11 \d+\.\d+\.\d+", lambda v: "ExplorerF11 %s" % v),
    ]),
    ("docs/USAGE.zh-CN.md", [
        (r"ExplorerF11 \d+\.\d+\.\d+", lambda v: "ExplorerF11 %s" % v),
    ]),
    ("docs/ARCHITECTURE.md", [
        (r"(?m)^version \d+\.\d+\.\d+ ", lambda v: "version %s " % v),
    ]),
    ("tools/release_facts.py", [
        (r'(?m)^VERSION = "[^"]+"$', lambda v: 'VERSION = "%s"' % v),
        (r'(?m)^ASSET = .*$',
         lambda v: 'ASSET = "ExplorerF11-" + VERSION + "-win64.exe"'),
    ]),
)


def bump(path, rules, version):
    full = os.path.join(ROOT, path)
    with open(full, encoding="utf-8") as fh:
        text = fh.read()
    for pattern, render in rules:
        new, n = re.subn(pattern, lambda m, r=render: r(version), text)
        if n == 0:
            raise SystemExit("bump_version: %s: no match for %s" % (path, pattern))
        text = new
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("  rewrote %s" % path)


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        raise SystemExit("usage: python tools/bump_version.py MAJOR.MINOR.PATCH")
    version = sys.argv[1]

    print("bump_version: %s" % version)
    for path, rules in STATIC_REPLACEMENTS:
        bump(path, rules, version)

    changelog = os.path.join(ROOT, "CHANGELOG.md")
    with open(changelog, encoding="utf-8") as fh:
        text = fh.read()
    if re.search(r"(?m)^## %s - " % re.escape(version), text):
        raise SystemExit("bump_version: CHANGELOG already has %s" % version)
    entry = ("## %s - %s\n\n### Summary required before release.\n\n" %
             (version, datetime.date.today().isoformat()))
    text = re.sub(r"(?m)^(## \d+\.\d+\.\d+ - )", entry + r"\1", text, count=1)
    with open(changelog, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("  seeded CHANGELOG.md (%s)" % version)

    print("\nNext steps (all mechanical except the last):")
    print("  1. fill in the CHANGELOG summary")
    print("  2. make -B && make refresh-facts   # rebuild, re-measure, update facts/manifest")
    print("  3. python tools/check_release_facts.py")
    print("  4. git tag -a v%s ... and publish; the hash comes from the NEW binary" % version)


if __name__ == "__main__":
    sys.exit(main())
