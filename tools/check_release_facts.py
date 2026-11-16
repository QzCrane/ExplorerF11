#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate: every release-facing number agrees with tools/release_facts.py.

Why this exists: a version bump used to touch a dozen files by hand, and any
missed one survived until a user found it. Now the facts live in one module and
this gate fails the build when a document, build file or manifest disagrees.

Scope is deliberate:
  * current statements are checked everywhere they appear;
  * CHANGELOG history is checked only in the current release section — older
    numbers there are measurements of older binaries and must stay as they are.
"""

import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_facts as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def check(name, ok, detail=""):
    results.append(bool(ok))
    suffix = ("  [" + str(detail) + "]") if detail else ""
    print(("PASS  " if ok else "FAIL  ") + name + suffix)


def contains(name, rel, needle):
    check(name, needle in read(rel), needle)


def absent(name, rel, pattern):
    text = read(rel)
    m = re.search(pattern, text, re.I)
    check(name, m is None, "" if m is None else repr(m.group(0)))


print("==== 1. 权威版本定义 ====")
app_h = read("src/app.h")
check("app.h EF11_VERSION = facts.VERSION",
      re.search(r'#define\s+EF11_VERSION\s+L"%s"' % re.escape(F.VERSION), app_h) is not None,
      F.VERSION)

rc = read("src/app.rc")
tuple_ver = ",".join(F.VERSION.split(".")) + ",0"
check("app.rc FILEVERSION/PRODUCTVERSION 数值", rc.count("FILEVERSION    " + tuple_ver) == 1
      and rc.count("PRODUCTVERSION " + tuple_ver) == 1, tuple_ver)
check("app.rc StringFileInfo 两处字符串", rc.count('"%s.0"' % F.VERSION) == 2,
      "%s.0" % F.VERSION)

ci = read(".github/workflows/build.yml")
contains("CI smoke 断言当前版本", ".github/workflows/build.yml",
         'findstr /C:"ExplorerF11 %s"' % F.VERSION)
absent("CI 不含 /std:c++17", ".github/workflows/build.yml", r"/std:c\+\+17\b")
contains("CI 使用 MSVC 最新标准开关", ".github/workflows/build.yml", F.MSVC_FLAG)

print("\n==== 2. 构建标准 ====")
for rel in ("Makefile", "build.bat"):
    text = read(rel)
    absent("%s 不含旧 C++17 开关" % rel, rel, r"(?<!c)\-std=c\+\+17\b|/std:c\+\+17\b")
    check("%s 使用 C++23 开关" % rel,
          (F.GCC_FLAG in text) and (F.MSVC_FLAG in text or rel == "Makefile"),
          F.GCC_FLAG if rel == "Makefile" else F.MSVC_FLAG)

print("\n==== 3. 实测清单 ====")
manifest = json.loads(read("tools/measurement.json"))
check("清单版本 = facts", manifest["version"] == F.VERSION, manifest["version"])
check("清单断言合计 = facts", manifest["assertions_total"] == F.ASSERTIONS,
      "%d vs %d" % (manifest["assertions_total"], F.ASSERTIONS))
check("清单套件数 = facts", len(manifest["suite_assertions"]) == F.SUITES,
      len(manifest["suite_assertions"]))
check("清单私有内存样本低于发布上限",
      float(manifest["private_mb"]) <= F.PRIVATE_CEIL_MB,
      "%s <= %d MB" % (manifest["private_mb"], F.PRIVATE_CEIL_MB))
check("清单句柄 = facts", manifest["handles"] == F.HANDLES, manifest["handles"])
check("清单线程峰值 = facts", manifest["threads_peak"] == F.THREADS_PEAK,
      manifest["threads_peak"])
check("清单文件大小 = facts", manifest["size_kib"] == F.SIZE_KIB,
      manifest["size_kib"])

print("\n==== 4. 当前文档陈述 ====")
for rel in F.CURRENT_FILES:
    text = read(rel)
    # Version and asset: only current-release identifiers may appear.
    stale_ver = re.findall(r"ExplorerF11-\d+\.\d+\.\d+-win64\.exe", text)
    check("%s 资产名一致" % rel,
          all(v == F.ASSET for v in stale_ver),
          ",".join(sorted(set(stale_ver))) or "(none)")
    stale_head = re.findall(r"ExplorerF11 \d+\.\d+\.\d+", text)
    check("%s 版本头一致" % rel,
          all(v == "ExplorerF11 " + F.VERSION for v in stale_head),
          ",".join(sorted(set(stale_head))) or "(none)")
    # Older measured values are history; they do not belong in a current claim.
    for token in (r"367 KiB", r"366 KiB", r"2\.3 MB", r"156 handles",
                  r"319 assertions", r"295 assertions", r"12 gates",
                  r"twelve gates", r"12 道闸门", r"three static checks",
                  r"3 项静态检查", r"-std=c\+\+17", r"/std:c\+\+17"):
        absent("%s 无陈旧标记 %s" % (rel, token), rel, token)

contains("README 资产名", "README.md", F.ASSET)
contains("README 闸门/断言", "README.md", "%d gates" % F.GATES)
contains("README 大小", "README.md", "%d KiB" % F.SIZE_KIB)
contains("README.zh-CN 资产名", "README.zh-CN.md", F.ASSET)
contains("README.zh-CN 闸门/断言", "README.zh-CN.md", "%d 道闸门" % F.GATES)
contains("README.zh-CN 大小", "README.zh-CN.md", "%d KiB" % F.SIZE_KIB)
contains("PR 模板闸门行", ".github/PULL_REQUEST_TEMPLATE.md",
         "%d gates: %d static checks + %d suites, %d assertions" %
         (F.GATES, F.STATIC_CHECKS, F.SUITES, F.ASSERTIONS))
contains("CONTRIBUTING 闸门构成", "CONTRIBUTING.md",
         "%s gates: %s static checks plus %s suites" %
         (("Thirteen", "four", "nine") if F.GATES == 13 else ("Twelve", "three", "nine")))
contains("ARCHITECTURE 资源表", "docs/ARCHITECTURE.md",
         "| Disk | %d KiB |" % F.SIZE_KIB)
GATE_WORD = {12: "Twelve", 13: "Thirteen"}.get(F.GATES, str(F.GATES))
check("ARCHITECTURE 闸门/断言",
      ("%d gates, %d assertions" % (F.GATES, F.ASSERTIONS)) in read("docs/ARCHITECTURE.md")
      or ("%s gates, %d assertions" % (GATE_WORD, F.ASSERTIONS)) in read("docs/ARCHITECTURE.md"))
check("RELEASING 闸门数",
      ("%d gates in this order" % F.GATES) in read("docs/RELEASING.md")
      or ("%s gates in this order" % GATE_WORD.lower()) in read("docs/RELEASING.md"))
contains("RELEASING checksum 名称", "docs/RELEASING.md", F.CHECKSUM)
contains("SECURITY 资产名", "SECURITY.md", F.ASSET)
contains("SECURITY checksum 名称", "SECURITY.md", F.CHECKSUM)

BADGE = "language-C%2B%2B23-00599C" if F.CPP_LABEL == "C++23" else None
for rel in ("README.md", "README.zh-CN.md"):
    check("%s 语言标签为 %s" % (rel, F.CPP_LABEL),
          (BADGE is not None and BADGE in read(rel))
          or ("C++%s" % F.CPP_LABEL[3:]) in read(rel), F.CPP_LABEL)

print("\n==== 5. CHANGELOG 当前段 ====")
current = re.search(r"(?ms)^## %s - .*?(?=^## |\Z)" % re.escape(F.VERSION),
                    read("CHANGELOG.md"))
check("存在当前版本条目", current is not None, F.VERSION)
if current:
    body = current.group(0)
    check("当前段引用当前二进制大小", "%d KiB" % F.SIZE_KIB in body,
          "%d KiB" % F.SIZE_KIB)
    check("当前段不含旧标准声明", "C++17 and Win32 only" not in body)

print("\n==== 6. 全仓库版本号残留 ====")
# A version literal that is not the current one is stale by definition, and the
# list of files that quote the version grows without anyone noticing: the issue
# template still advertised 1.0.1 three releases later, and it was invisible
# because it was never in CURRENT_FILES. Scan the whole tree instead of a list.
# CHANGELOG.md is exempt: it is history, and its older sections are measurements
# of older binaries.
SKIP_DIRS = {".git", ".workbuddy", ".workbuddy-ai", "dist", "__pycache__", ".pytest_cache"}
TEXT_EXT = (".md", ".yml", ".yaml", ".py", ".json", ".cpp", ".h", ".rc", ".txt",
            ".bat", ".ps1", ".cfg", ".toml")
stale_hits = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for name in filenames:
        if name == "CHANGELOG.md":
            continue
        if not (name.endswith(TEXT_EXT) or name in ("Makefile", ".editorconfig", ".gitattributes")):
            continue
        full = os.path.join(dirpath, name)
        rel = os.path.relpath(full, ROOT).replace("\\", "/")
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for m in re.finditer(r"ExplorerF11[ -](\d+\.\d+\.\d+)", text):
            if m.group(1) != F.VERSION:
                stale_hits.append("%s: %s" % (rel, m.group(0)))
check("无其他文件引用旧版本号", not stale_hits, "; ".join(stale_hits[:3]))

print("\n==== 7. 签名状态 ====")
# Whether the binary is signed is a published fact, and the documents make a
# claim about it. When the two disagree, the release page tells the user to
# expect a warning that will not appear - or the reverse. The check reads the
# PE security directory rather than trusting a flag, so it describes the file
# that would be uploaded.
EXE = os.path.join(ROOT, "dist", "ExplorerF11.exe")


def pe_is_signed(path):
    """True/False for a readable PE, None when there is no binary to inspect."""
    if not os.path.exists(path):
        return None
    import struct
    with open(path, "rb") as fh:
        data = fh.read(4096)
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\0\0":
        return None
    opt = e + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    return struct.unpack_from("<I", data, dd + 4 * 8 + 4)[0] > 0


UNSIGNED_CLAIMS = {
    "README.md": r"\bunsigned\b|\bnot code-signed\b",
    "README.zh-CN.md": r"未做代码签名|未签名",
    "SECURITY.md": r"\bnot code-signed\b|code-signing certificate",
}
signed = pe_is_signed(EXE)
if signed is None:
    print("SKIP  dist/ExplorerF11.exe 不存在，跳过签名比对")
else:
    print("      binary is %s" % ("signed" if signed else "unsigned"))
    for doc, pattern in UNSIGNED_CLAIMS.items():
        claims_unsigned = re.search(pattern, read(doc)) is not None
        if signed:
            check("%s 不再声称未签名" % doc, not claims_unsigned,
                  "binary carries a signature")
        else:
            check("%s 声明二进制未签名" % doc, claims_unsigned,
                  "binary has an empty security directory")

bad = results.count(False)
print("\n%s  %d/%d 通过" % ("ALL PASS" if not bad else "FAILURES",
                            len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
