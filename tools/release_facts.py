#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single source of truth for release-facing numbers.

Every number that appears in more than one place lives here. Documentation is
prose and therefore repeats these values; ``check_release_facts.py`` is the gate
that keeps every copy equal to the one below. ``bump_version.py`` rewrites the
version-derived copies mechanically.

Provenance:
  version      src/app.h EF11_VERSION, the only authoritative definition
  asset/checksum  naming convention fixed here; see docs/RELEASING.md
  gates/assertions  counted from the Makefile ``test`` recipe and suite output
  measured     test_smoke.py on Windows 11 build 26300.9974, one folder window
               open, shortly after start-up; size is the MinGW-w64 release build
               (MSVC is not byte-identical, so no build-time size assertion)
"""

VERSION = "1.0.3"
ASSET = "ExplorerF11-" + VERSION + "-win64.exe"
CHECKSUM = "SHA256SUMS.txt"

GATES = 13
STATIC_CHECKS = 4
SUITES = 9
ASSERTIONS = 322

SIZE_KIB = 370
# A private-memory sample moves between 1.86 and 1.87 MB between runs. The
# published figure is therefore a ceiling, not a point sample; the raw value of
# each refresh is kept in measurement.json for the record.
PRIVATE_CEIL_MB = 2
HANDLES = 135
THREADS_PEAK = 4
THREADS_SETTLED = 1
CPU_SECONDS = "0.03"

CPP_LABEL = "C++23"
GCC_FLAG = "-std=c++23"
MSVC_FLAG = "/std:c++latest"

# Files whose prose must always describe the *current* release. Historical
# material in CHANGELOG.md is checked only in the topmost version section.
CURRENT_FILES = (
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/USAGE.en.md",
    "docs/USAGE.zh-CN.md",
    "docs/RESEARCH.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

BUILD_FILES = ("Makefile", "build.bat", ".github/workflows/build.yml")
