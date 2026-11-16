#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate: the gate list has one owner, and every surface agrees with it.

`make test` is the owner: the recipe in the Makefile is what a contributor runs
and what `refresh_facts.py` counts. Two other surfaces enumerate the same gates
by hand:

  * `.github/workflows/build.yml` runs the subset that needs no Explorer shell,
  * the table in `docs/ARCHITECTURE.md` describes one row per gate.

Both used to drift silently in the direction that costs the most: a new gate was
added to the Makefile, never reached CI, and the documentation table kept
describing the previous set - so the gate existed, ran on one machine, and
guarded nothing. This script makes the three lists a single decision: every gate
must be classified as CI-runnable or shell-dependent, CI must run exactly the
classified subset, and the table must describe every gate once.

The classifications below are the decision, with the reason spelled out. A gate
that is missing from both groups fails here, so adding a gate means answering
"does CI run this?" before it can land.
"""

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKEFILE = os.path.join(ROOT, "Makefile")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "build.yml")
ARCHITECTURE = os.path.join(ROOT, "docs", "ARCHITECTURE.md")

# Runs on a hosted Windows runner: no Explorer shell, no visible window.
# test_lang_names, test_menu_order and test_robustness only read stdout of the
# built exe; test_tray_cleanup only plants entries in HKCU and runs --clean.
CI_RUNS = (
    "tools/check_i18n.py",
    "tools/audit_i18n.py",
    "tools/check_help_align.py",
    "tools/check_release_facts.py",
    "tools/check_gate_inventory.py",
    "tests/test_lang_names.py",
    "tests/test_menu_order.py",
    "tests/test_tray_cleanup.py",
    "tests/test_robustness.py",
)

# Needs a live Explorer: a real folder window, the tray, or the app's own menu
# window driven through WM_COMMAND. A hosted runner has no shell to hook.
NEEDS_SHELL = {
    "tests/test_residue_report.py": "opens and reads the report window",
    "tests/test_registry_policy.py": "drives the tray menu of a running instance",
    "tests/test_language.py": "switches the live tray menu and the open report",
    "tests/test_icons.py": "reads the tooltip the shell draws",
    "tests/test_smoke.py": "accelerates a real Explorer window and measures it",
}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    suffix = ("  [" + str(detail) + "]") if detail else ""
    print(("PASS  " if ok else "FAIL  ") + name + suffix)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


recipe = re.search(r"(?ms)^test:.*?\n\n", read(MAKEFILE))
gate_commands = re.findall(r"^\tpython (.+)$", recipe.group(0), re.M) if recipe else []
check("Makefile test 配方可解析", len(gate_commands) >= 10, "%d 条命令" % len(gate_commands))

workflow = read(WORKFLOW)
ci_commands = re.findall(r"(?m)^\s+python ((?:tools|tests)/\S+\.py)\s*$", workflow)

print("\n==== 分类完整性 ====")
declared = set(CI_RUNS) | set(NEEDS_SHELL)
unclassified = [c for c in gate_commands if c not in declared]
phantom = sorted(declared - set(gate_commands))
check("每道闸门都已分类（CI 或需要 shell）", not unclassified,
      "未分类: " + ", ".join(unclassified))
check("分类表没有已删除的闸门", not phantom, "多余: " + ", ".join(phantom))
check("两组不重叠", not (set(CI_RUNS) & set(NEEDS_SHELL)),
      ", ".join(sorted(set(CI_RUNS) & set(NEEDS_SHELL))))
check("每组都非空", bool(CI_RUNS) and bool(NEEDS_SHELL),
      "%d CI / %d shell" % (len(CI_RUNS), len(NEEDS_SHELL)))

print("\n==== CI 与分类一致 ====")
check("CI 运行的闸门 = 声明可在 CI 运行的集合",
      sorted(ci_commands) == sorted(CI_RUNS),
      "CI 独有: %s | 声明独有: %s" % (
          ", ".join(sorted(set(ci_commands) - set(CI_RUNS))) or "-",
          ", ".join(sorted(set(CI_RUNS) - set(ci_commands))) or "-"))
check("CI 没有重复运行同一道闸门",
      len(ci_commands) == len(set(ci_commands)), "%d 次调用" % len(ci_commands))

print("\n==== CI 构建 = 文档记录的构建 ====")
# The workflow used to carry its own copy of the cl command line, so the MSVC
# path it proved was not the one build.bat documents (missing /GL and /LTCG).
# One definition, invoked by CI, is the only version that cannot drift.
check("CI 调用 build.bat 而不是手抄编译命令",
      re.search(r"(?m)^\s+call build\.bat\s+msvc\s*$", workflow) is not None)
check("CI 不直接调用 cl 或 g++",
      re.search(r"(?m)^\s+(cl|g\+\+)\s", workflow) is None)

print("\n==== 文档表格 ====")
table = re.search(r"(?m)^\| Gate \| Proves \|\n\|[-\s|]+\|\n((?:\|.*\n)+)",
                  read(ARCHITECTURE))
rows = re.findall(r"(?m)^(\|[^|\n]+\|.*)$", table.group(1)) if table else []
# First column only: the "proves" column carries backticks of its own (`T()`,
# `--help`), and matching those would count prose as a gate.
documented = []
for row in rows:
    cell = row.strip().strip("|").split("|")[0]
    m = re.search(r"`([^`]+)`", cell)
    if m:
        documented.append(m.group(1).replace("\\", "/").split("/")[-1])
expected = [c.split("/", 1)[1] for c in gate_commands]
check("ARCHITECTURE 有闸门表", table is not None, "%d 行" % len(documented))
check("ARCHITECTURE 表格行数 = 闸门数", len(documented) == len(expected),
      "%d 行 vs %d 道" % (len(documented), len(expected)))
check("ARCHITECTURE 表格覆盖每道闸门、无多余行",
      sorted(documented) == sorted(expected),
      "缺: %s | 多: %s" % (
          ", ".join(sorted(set(expected) - set(documented))) or "-",
          ", ".join(sorted(set(documented) - set(expected))) or "-"))

print("\n==== RELEASING 的表格（顺序也一致）====")
releasing = re.search(r"\| Gate \| What it proves \|\n((?:\|.*\n)+)",
                      read(os.path.join(ROOT, "docs", "RELEASING.md")))
ordered = []
if releasing:
    for row in re.findall(r"(?m)^(\|[^|\n]+\|.*)$", releasing.group(1)):
        m = re.search(r"`([^`]+)`", row.strip().strip("|").split("|")[0])
        if m:
            ordered.append(m.group(1).replace("\\", "/"))
check("RELEASING 按 Makefile 顺序列出每道闸门", ordered == gate_commands,
      "%d 行 vs %d 道" % (len(ordered), len(gate_commands)))

failed = results.count(False)
print("\n%d/%d 通过" % (len(results) - failed, len(results)))
sys.exit(1 if failed else 0)
