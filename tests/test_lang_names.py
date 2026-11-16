#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The language *names*, which are a separate concern from the language itself.

A language has one name in this tool, and that name never changes with the UI
language. Two surfaces have to agree on it:

  the tray submenu   one radio row per language, each written in its own script
  the report header  "UI language: <the same name>"

Proven here:
  1. the five menu rows are byte-identical in all five UI languages, so a user
     who lands in a language they cannot read can still find their way back;
  2. the rows are the endonyms from src/i18n.h: LangName(), in a fixed order;
  3. the report header names the language that is actually active - the
     regression this suite exists for, where a Traditional Chinese report
     claimed to be written in Simplified Chinese;
  4. no UI language names any language other than its own in the header.

Run:  python tests/test_lang_names.py
"""

import sys as _sys

# These suites print Chinese, Japanese and Korean. A Windows console defaults to
# a legacy code page, where print() raises UnicodeEncodeError and the suite fails
# for a reason that has nothing to do with the binary under test.
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")

TAGS = ("zh", "zh-Hant", "en", "ja", "ko")

# src/i18n.h: LangName(). Order is the menu order, which is also the radio
# group order. These strings are endonyms and are therefore identical in every
# UI language by design.
ENDONYM = {
    "zh": "简体中文",
    "zh-Hant": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}
MENU_ORDER = [ENDONYM[t] for t in TAGS]

# The label that introduces the language in the report header, per language.
HEADER_LABEL = {
    "zh": "界面语言：",
    "zh-Hant": "介面語言：",
    "en": "UI language: ",
    "ja": "表示言語：",
    "ko": "표시 언어: ",
}

ENV = {k: v for k, v in os.environ.items() if k != "EXPLORERF11_LANG"}

results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(("  PASS  " if ok else "  FAIL  ") + "%-56s got=%r want=%r" % (name, got, want))
    return ok


def check_true(name, cond, detail=""):
    return check(name + (("  [" + str(detail) + "]") if detail else ""), bool(cond), True)


def run(*args):
    p = subprocess.run([EXE] + list(args), cwd=os.path.dirname(EXE),
                       env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout


def menu_rows(lang):
    """The five indented radio rows, without the tick marker."""
    out = run("--menu", "--lang", lang, "--quiet")
    rows = []
    for line in out.splitlines():
        if not line.startswith("    "):
            continue
        m = re.match(r"^    \[[ x✓]\] (.+)$", line)
        if m:
            rows.append(m.group(1))
    return rows


def header_language(lang):
    """The name after the header label, or None when the label is missing."""
    out = run("--status", "--lang", lang, "--quiet")
    label = HEADER_LABEL[lang]
    for line in out.splitlines()[:6]:
        i = line.find(label)
        if i >= 0:
            return line[i + len(label):].strip()
    return None


def main():
    print("==== 1. 语言名称：五种界面语言下完全一致 ====")
    baseline = menu_rows("zh")
    check("中文界面下的五个语言行", baseline, MENU_ORDER)
    for lang in TAGS[1:]:
        check("%s 界面下的语言行" % lang, menu_rows(lang), baseline)

    print("\n==== 2. 报告头写明实际生效的语言 ====")
    for lang in TAGS:
        got = header_language(lang)
        check("%s 报告头的语言名" % lang, got, ENDONYM[lang])

    print("\n==== 3. 报告头不得张冠李戴 ====")
    for lang in TAGS:
        got = header_language(lang)
        others = [n for t, n in ENDONYM.items() if t != lang]
        check_true("%s 没有写成别的语言" % lang, got not in others, got)

    print("\n==== 4. 菜单勾选行 = 报告头语言名 ====")
    for lang in TAGS:
        out = run("--menu", "--lang", lang, "--quiet")
        ticked = [re.match(r"^    \[✓\] (.+)$", ln).group(1)
                  for ln in out.splitlines() if ln.startswith("    [✓] ")]
        check("%s 勾选行唯一且与报告头一致" % lang, ticked, [header_language(lang)])

    failed = results.count(False)
    print("\n%d checks, %d failed" % (len(results), failed))
    if failed:
        print("FAILURES: %d" % failed)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
