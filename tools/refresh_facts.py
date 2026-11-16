#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh release_facts.py and the measurement manifest from ground truth.

    make refresh-facts

Ground truth is read from src/app.h, the Makefile ``test`` recipe, the built
executable and a full run of every gate. Each gate is invoked separately so a
suite's assertion count can be attributed to that suite. A failing gate stops
the refresh and leaves the published facts untouched.
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTS = os.path.join(ROOT, "tools", "release_facts.py")
MANIFEST = os.path.join(ROOT, "tools", "measurement.json")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def substitute(path, pairs):
    text = read(path)
    for pattern, value in pairs:
        text, n = re.subn(pattern, lambda m, v=value: v, text, count=1)
        if n != 1:
            raise SystemExit("refresh_facts: no match for %r in %s" % (pattern, path))
    write(path, text)


def assertion_total(output, command):
    """Count a suite's assertions, accepting all three summary styles in-tree."""
    m = re.search(r"ALL PASS\s+(\d+)/(\d+)", output)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+) checks,\s*(\d+) failed", output)
    if m:
        return int(m.group(1))
    lines = [ln for ln in output.splitlines() if ln.startswith("PASS")]
    if lines and "全部通过" in output:
        return len(lines)
    raise SystemExit("refresh_facts: cannot count assertions of %s" % command)


def main():
    version = re.search(r'#define\s+EF11_VERSION\s+L"([^"]+)"',
                        read(os.path.join(ROOT, "src", "app.h"))).group(1)

    recipe = re.search(r"(?ms)^test:.*?\n\n", read(os.path.join(ROOT, "Makefile"))).group(0)
    commands = re.findall(r"^\tpython (.+)$", recipe, re.M)
    suites = [c for c in commands if c.startswith("tests/")]
    if len(commands) != len(suites) + sum(1 for c in commands if c.startswith("tools/")):
        raise SystemExit("refresh_facts: unclassified test commands: %r" % commands)

    # Run every gate individually: one red gate invalidates the whole refresh.
    counts = {}
    smoke_output = ""
    for command in commands:
        # The facts gate compares docs against the facts file. Running it here
        # would compare against the *previous* snapshot, so defer it until the
        # new facts have been written (see the verification step below).
        if command.endswith("tools/check_release_facts.py"):
            continue
        proc = subprocess.run(["python"] + command.split(), cwd=ROOT, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print("$ %s" % command)
        print(proc.stdout[-1200:])
        if proc.returncode:
            raise SystemExit("refresh_facts: %s failed; facts not changed" % command)
        if command.startswith("tests/"):
            counts[command] = assertion_total(proc.stdout, command)
        if command.endswith("test_smoke.py"):
            smoke_output = proc.stdout

    measured = re.search(r"private=([\d.]+) MB\s+threads=(\d+)\s+handles=(\d+)",
                         smoke_output)
    if not measured:
        raise SystemExit("refresh_facts: smoke resource line missing")

    exe = os.path.join(ROOT, "dist", "ExplorerF11.exe")
    size_kib = int(round(os.path.getsize(exe) / 1024.0))
    total = sum(counts.values())

    pairs = [
        (r'(?m)^VERSION = "[^"]+"$', 'VERSION = "%s"' % version),
        (r'(?m)^GATES = \d+$', "GATES = %d" % len(commands)),
        (r'(?m)^STATIC_CHECKS = \d+$',
         "STATIC_CHECKS = %d" % (len(commands) - len(suites))),
        (r'(?m)^SUITES = \d+$', "SUITES = %d" % len(suites)),
        (r'(?m)^ASSERTIONS = \d+$', "ASSERTIONS = %d" % total),
        (r'(?m)^SIZE_KIB = \d+$', "SIZE_KIB = %d" % size_kib),
        (r'(?m)^PRIVATE_CEIL_MB = \d+$',
         "PRIVATE_CEIL_MB = %d" % int(float(measured.group(1)) + 0.999)),
        (r'(?m)^HANDLES = \d+$', "HANDLES = %d" % int(measured.group(3))),
        (r'(?m)^THREADS_PEAK = \d+$', "THREADS_PEAK = %d" % int(measured.group(2))),
    ]
    substitute(FACTS, pairs)

    manifest = {
        "version": version,
        "suite_assertions": {os.path.basename(k): v for k, v in counts.items()},
        "assertions_total": total,
        "private_mb": measured.group(1),
        "threads_peak": int(measured.group(2)),
        "handles": int(measured.group(3)),
        "size_kib": size_kib,
    }
    write(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    # Now that facts and manifest agree, the consistency gate can validate them.
    verify = subprocess.run(["python", "tools/check_release_facts.py"], cwd=ROOT,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = "\n".join(verify.stdout.strip().splitlines()[-8:])
    print("$ python tools/check_release_facts.py\n" + tail)
    if verify.returncode:
        raise SystemExit("refresh_facts: consistency gate failed; see output above")

    print("release_facts: v%s, %d gates (%d static + %d suites), %d assertions, "
          "%d KiB, %s MB / %s handles / %s threads" %
          (version, len(commands), len(commands) - len(suites), len(suites), total,
           size_kib, measured.group(1), measured.group(3), measured.group(2)))


if __name__ == "__main__":
    sys.exit(main())
