# Contributing

ExplorerF11 is a small program with a narrow attack surface. The rules below
exist to keep that true; they are shorter than the reasoning behind them, which
is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Invariants

Three constraints are non-negotiable. A change that breaks one has to argue that
the constraint itself should change, not merely that the new behaviour is
convenient:

1. **No polling.** Detection comes from the shell hook or a WinEvent hook.
2. **No injection.** `PostMessageW` into another process is the only permitted
   cross-process action — no DLL, no remote thread, no memory patching.
3. **No unremovable residue.** A new registry value, file or cache entry needs a
   case in `src/residue.cpp`, a row in `docs/RESIDUE.md` and removal by
   `--clean`. If it cannot be removed, the report must say so.

## Build and test

Either MSVC (Developer Command Prompt) or MinGW-w64 with `g++` on PATH:

```bat
build.bat
build.bat debug
build.bat msvc       :: force cl.exe, which is what CI runs
build.bat mingw      :: force g++, the compiler the release is built with
```

Then:

```sh
make test
```

Fourteen gates: five static checks plus nine suites that drive the built binary.
The suite needs the exe, so build first. `test_smoke.py` opens a real folder
window and requires a desktop session. A new gate must also be classified in
`tools/check_gate_inventory.py` — as CI-runnable or as needing a shell — and
listed in the tables of `docs/ARCHITECTURE.md` and `docs/RELEASING.md`; that
gate fails until all four surfaces agree.

Three rules for tests:

- every gate asserts and exits non-zero on failure. Printing a report for a
  human to read is not a test;
- a test observes the program from outside. Run it, read what it wrote, ask the
  window it drew, check the registry it touched. Reading `src/` and matching a
  line is allowed only where no outside observation exists at all, it is marked
  `WHITE-BOX` in the file, and it names the observation that is missing;
- a test that changes state restores it, including autostart and the stored
  language — see `test_registry_policy.py`;
- a test never deletes a real user's settings. The clean-button test only runs
  when the machine is already clean, and the tray test plants its own keys.

Event-driven paths (shell-hook recovery, F11 recovery, handle and icon
ownership) cannot be driven deterministically on a CI runner. Pin their source
contracts in `tests/test_robustness.py` and state plainly what was not
exercised; do not substitute a mock for the Win32 behaviour and claim
equivalence.

## What is in `tools/`

Not a junk drawer, and not interchangeable: five of these files are gates that
run on every `make test`, the rest are the pipeline or the measurement behind a
published number. Only `src/i18n_extra.cpp` and `docs/images/*.png` are
generated from what is here.

| Group | Files | Role |
|---|---|---|
| Gates | `check_i18n.py`, `audit_i18n.py`, `check_help_align.py`, `check_release_facts.py`, `check_gate_inventory.py` | run by `make test`; each exits non-zero on failure |
| Translation pipeline | `extract_i18n_pairs.py`, `gen_i18n.py`, `sync_i18n.py`, `translations.json`, `i18n_strings.json` | extract `T()` sites, hold the four translations per key, regenerate `src/i18n_extra.cpp` |
| Release pipeline | `release.py`, `release_facts.py`, `refresh_facts.py`, `check_github_sync.py`, `bump_version.py`, `treefp.py`, `measurement.json`, `capture-screenshots.py` | the sixteen stages, the number every document quotes, and the tree fingerprint that lets `gates` reuse a proven run |
| Shared runtime | `win32util.py` | process launch and observation primitives used by the suites and the screenshot tool |
| Measurement | `bench_hotpaths.cpp`, `bench_probes.cpp`, `bench_ua_match.cpp`, `measure_mem.cpp`, `mem_floor.cpp`, `verify_handles.cpp`, `verify_marks.cpp`, `icon_probe.cpp`, `make_ico_bmp.py`, `make-icons.py` | one-shot evidence for a number in `docs/PERFORMANCE.md` or `CHANGELOG.md`; kept so the claim can be re-measured, not run by anything |

A measurement tool that no longer backs a published number is deleted, not kept
"for reference". `dist/` holds only what a build or a release run produced.

## Code conventions

- C++23 and Win32 only. No third-party libraries, no C++ exceptions across a
  Win32 callback, no `std::filesystem` — it pulls in more code than the exe
  saves. The sources deliberately use no C++20/23-only library facilities, so an
  older toolchain can still build them by switching the flag back to C++17; the
  release binaries are compiled as C++23 (`-std=c++23` on MinGW,
  `/std:c++latest` on MSVC — `cl` does not accept `/std:c++23`).
- Comments explain *why*. A comment that restates the code is noise.
- Check every `PostMessage` and `Reg*` return value when a failure would be
  silent. A failed delivery is what the recovery timer exists for.
- Keep the exe small: `-Os`, static CRT, no iostream.
- Ownership is explicit at teardown. A handle created by a fallback path must be
  closed by that path; a system-owned icon must never be destroyed by the tool.
- `--quiet`, `--lang` and the other CLI switches are parsed into local state
  and applied after localisation, so diagnostics follow the selected language.
  An unrecognised token fails with exit code 2; falling through to "start the
  tray app" would turn a typo into a silent no-op.

## User-visible strings

Every user-visible string goes through `T(L"简体中文", L"English")` from
`src/i18n.h`. Add the Traditional Chinese, Japanese and Korean forms to
`tools/translations.json`, keyed by the exact Simplified Chinese literal, then
run:

```bat
python tools\sync_i18n.py
```

It updates the key list, reports anything still untranslated and regenerates
`src/i18n_extra.cpp`. A missing translation in any of the five languages is a
bug: `tools/check_i18n.py` enforces coverage and `tools/audit_i18n.py` enforces
script and punctuation rules on every build.

A language is named in exactly one place — `LangName()` in `src/i18n.h` — and
the name never varies with the UI language. Do not hardcode a language name in a
translated string: that is how a report header once claimed every report was
written in Simplified Chinese.

If you add a flag, add it to `UsageText()` in `src/main.cpp` in all five
languages, to both usage documents and to the help-alignment check. Keep the
exit-code contract: `0` success, `1` residues found by `--status`, `2` usage
error.

## Commits and pull requests

- One logical change per commit; the message says what breaks without it.
- Add a `CHANGELOG.md` entry under `Unreleased` for anything user-visible.
- Regenerate `docs/images` after changing the menu, tooltip or report window:

```bat
python tools\capture-screenshots.py zh
python tools\capture-screenshots.py en
```

The script drives the real windows, so build first and close anything that
would overlap the popup.

## Bug reports

Include the Windows build number (`winver`), whether ExplorerPatcher or a
similar shell modification is installed, the output of `ExplorerF11.exe
--status`, and the relevant lines from `%TEMP%\ExplorerF11.log` if you ran with
`--log`. Behaviour that depends on undocumented shell internals changes between
Windows builds; a report naming the build number is worth ten that do not.

For anything security-related, use the private channel in
[SECURITY.md](SECURITY.md) instead of a public issue.

## Releasing

[docs/RELEASING.md](docs/RELEASING.md) lists the files carrying the version, the
fourteen gates and the build/verification/publication sequence.
