# SPDX-License-Identifier: MIT
"""Static audit of tools/translations.json beyond what check_i18n.py enforces.

check_i18n.py proves *coverage*: every T() key is translated and every
placeholder survived. This script proves *quality*, i.e. the defects a native
reviewer would flag but a coverage check cannot see:

  script   a value containing characters from a script the target language does
           not use (Han inside Korean, Hangul inside Japanese, ...)
  bracket  a phrase that opens with a full-width parenthesis and closes with an
           ASCII one, e.g. "\uff08HKCU\\Software\u2026)"
  punct    ASCII punctuation glued to CJK text inside an otherwise full-width
           sentence, e.g. "\u7d42\u4e86 (\u5b9f\u884c\u4e2d)" instead of "\u7d42\u4e86\uff08\u5b9f\u884c\u4e2d\uff09"
  space    an ASCII space between two CJK glyphs, which leaves a ragged gap
  term     a target-language variant that contradicts the term chosen for that
           language elsewhere in the file (mainland wording in Traditional
           Chinese, "wreckage" where the domain term is "residue", ...)

Punctuation inside flags, paths, registry keys, identifiers and file names is
ASCII on purpose and is excluded before the check runs.

Exit code 0 = clean, 1 = findings, so it can be a build gate.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRANS = os.path.join(HERE, "translations.json")

LANGS = ["zh-Hant", "ja", "ko"]
INDEX = {"zh-Hant": 0, "ja": 1, "ko": 2}

RANGES = {
    "Han": [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)],
    "Hiragana": [(0x3040, 0x309F)],
    "Katakana": [(0x30A0, 0x30FF)],
    "Hangul": [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)],
}

ALLOWED = {
    "ja": {"Han", "Hiragana", "Katakana"},
    "ko": {"Han", "Hangul"},
    "zh-Hant": {"Han"},
}

CJK = "\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af"
CJK_RE = re.compile("[%s]" % CJK)

# Spans whose punctuation is ASCII by design.
CODE_SPAN = re.compile(
    r"(--[A-Za-z-]+(?:\s*,\s*--[A-Za-z-]+)*"      # --clean, --purge
    r"|EXPLORERF11_[A-Z]+"
    r"|%[A-Z]+%"
    r"|[A-Za-z]:\\[^\s\uff0c\u3002]*"             # D:\...
    r"|HKCU\\[^\s\uff0c\u3002]*"
    r"|HKLM\\[^\s\uff0c\u3002]*"
    r"|[\w.]+\.(?:exe|log|pf|dll|json|txt)"
    r"|\b(?:REG_SZ|REG_DWORD|REG_BINARY|Tabs|InitialSweep|Language|Windows|"
    r"explorer|MuiCache|UserAssist|Prefetch|StartupApproved|ROT13|exe|MB|KB|B)\b)"
)

# Half-width marks that must not sit against CJK text.
ASCII_MARKS = ",.:;()!?"

# Variants that contradict the terminology chosen for that language. Each entry
# is (bad variant, why it is wrong, canonical replacement).
TERM_TRAPS = {
    "zh-Hant": [
        ("残骸", "simplified glyph", "殘骸"),
        ("残留", "simplified glyph", "殘留"),
        ("文件夹", "mainland wording", "資料夾"),
        ("选项卡", "mainland wording", "索引標籤"),
        ("选项卡", "mainland wording", "索引標籤"),
        ("注册表", "mainland wording", "登錄檔"),
        ("默认", "mainland wording", "預設"),
        ("设置", "mainland wording", "設定"),
        ("程序", "mainland wording for 'program'", "程式"),
        ("文件", "mainland wording for 'file'", "檔案"),
        ("痕迹", "mainland wording", "痕跡"),
        ("足迹", "mainland wording", "足跡"),
    ],
    "ja": [
        ("残骸", "wreckage, not the domain term", "残留"),
        ("文件夹", "not Japanese", "フォルダー"),
        ("选项卡", "not Japanese", "タブ"),
        ("默认", "not Japanese", "既定"),
        ("注册表", "not Japanese", "レジストリ"),
        ("フォルダ ", "Microsoft style drops the long vowel", "フォルダー"),
    ],
    "ko": [
        ("흔적", "trace, not the domain term", "잔여물"),
        ("윈도우", "transliteration; the UI term is 창", "창"),
    ],
}

findings = []


def add(kind, lang, key, value, detail):
    findings.append((kind, lang, key, value, detail))


def strip_code(s):
    return CODE_SPAN.sub("", s)


def has_range(ch, ranges):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in ranges)


def audit_script(lang, key, value):
    allowed = ALLOWED[lang]
    for ch in value:
        for name, ranges in RANGES.items():
            if name in allowed:
                continue
            if has_range(ch, ranges):
                add("script", lang, key, value,
                    "U+%04X %r is %s script" % (ord(ch), ch, name))
                return


def audit_brackets(lang, key, value):
    """A phrase must not mix （ with ) - the two styles are never combined."""
    if ("\uff08" in value and ")" in value) or ("(" in value and "\uff09" in value):
        add("bracket", lang, key, value, "mixes full-width and ASCII parentheses")
        return


def audit_punct(lang, key, value):
    body = strip_code(value)
    for i, ch in enumerate(body):
        if ch not in ASCII_MARKS:
            continue
        left = body[i - 1] if i else ""
        right = body[i + 1] if i + 1 < len(body) else ""
        # Only a mark touching CJK text is a defect; " 1 = clean" is fine.
        if CJK_RE.match(left or " ") or CJK_RE.match(right or " "):
            add("punct", lang, key, value,
                "ASCII %r glued to CJK text" % ch)
            return


# Han and hiragana only: a space between two katakana words is Microsoft's
# house style for Japanese compounds (タスク マネージャー), not a defect.
NO_SPACE = "\u3040-\u309f\u3400-\u9fff\uf900-\ufaff"


def audit_space(lang, key, value):
    body = strip_code(value)
    for m in re.finditer(r"(?<=[%s]) (?=[%s])" % (NO_SPACE, NO_SPACE), body):
        add("space", lang, key, value, "ASCII space between two CJK glyphs")
        return


def audit_term(lang, key, value):
    for bad, why, good in TERM_TRAPS[lang]:
        if bad in value:
            add("term", lang, key, value, "%r -> %r (%s)" % (bad, good, why))
            return


def main():
    with open(TRANS, encoding="utf-8") as f:
        data = json.load(f)

    for key, row in data.items():
        if len(row) != 3:
            add("shape", "-", key, str(row), "expected 3 translations")
            continue
        for lang in LANGS:
            value = row[INDEX[lang]]
            if not value:
                continue
            audit_script(lang, key, value)
            # Korean punctuation is ASCII by convention (KS X 1026), and Korean
            # separates words with spaces, so neither check applies to it.
            if lang != "ko":
                audit_brackets(lang, key, value)
                audit_punct(lang, key, value)
                audit_space(lang, key, value)
            audit_term(lang, key, value)

    order = {"script": 0, "term": 1, "bracket": 2, "punct": 3, "space": 4, "shape": 5}
    findings.sort(key=lambda f: (order.get(f[0], 9), f[1], f[2]))

    print("keys: %d   findings: %d" % (len(data), len(findings)))
    for kind, lang, key, value, detail in findings:
        head = value if len(value) <= 110 else value[:107] + "..."
        head = head.replace("\n", "\\n")
        print("\n[%s] %s\n  value %s\n  why   %s" % (kind, lang, head, detail))

    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
