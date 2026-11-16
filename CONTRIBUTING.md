# Contributing

Thanks for taking a look. This is a small utility, so the rules are short.

## Before you change behaviour

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Three constraints are not
negotiable, because they are the reason the project exists:

1. **No polling.** Everything is driven by the shell hook or a WinEvent hook.
2. **No injection.** Messages to other processes, never a DLL, never memory
   patching.
3. **No residue you cannot remove.** A new registry value, file or cache entry
   needs an entry in `residue.cpp` and a line in `docs/RESIDUE.md`, and
   `--clean` must remove it. If it cannot be removed, say so in the report.

## Build

```bat
build.bat
build.bat debug
```

Requires either MSVC (Developer Command Prompt) or MinGW-w64 with `g++` on PATH.

## Test

```bat
rem static gates
python tools\check_i18n.py
python tools\audit_i18n.py
python tools\check_help_align.py

rem suites that drive the built binary
python tests\test_lang_names.py
python tests\test_menu_order.py
python tests\test_residue_report.py
python tests\test_registry_policy.py
python tests\test_language.py
python tests\test_icons.py
python tests\test_tray_cleanup.py
python tests\test_smoke.py
```

`make test` runs all eleven gates: three static checks and eight suites. They
must pass before a pull request; the suites drive the real binary, so build
first. Three rules for tests:

- every suite asserts and exits non-zero on failure — printing a report for a
  human to read is not a test;
- a test that changes state must restore it, including the autostart entry and
  the stored language (see `test_registry_policy.py`);
- a test must never delete a real user's settings. The clean-button test only
  runs when the machine is already clean, and the tray test plants its own keys
  instead of touching the user's.

## Code style

- C++17, Win32 only. No third-party libraries, no C++ exceptions across the
  Win32 boundary, no `std::filesystem` (it pulls in more than the exe saves).
- Comments explain *why*, not *what*. A comment that restates the code is noise.
- Every user-visible string goes through `T(L"简体中文", L"English")` from
  `src/i18n.h`. Add the Traditional Chinese, Japanese and Korean forms to
  `tools/translations.json`, keyed by the exact Simplified Chinese literal, then
  run `python tools\sync_i18n.py` (it updates the key list, reports anything
  still untranslated, and regenerates `src/i18n_extra.cpp`). A string missing
  from any of the five languages is a bug; `tools/check_i18n.py` enforces
  coverage and `tools/audit_i18n.py` enforces quality on every build.
- A language is named in exactly one place, `LangName()` in `src/i18n.h`, and
  the name never varies with the UI language. Do not hardcode a language name in
  a translated string: that is how the report header ended up claiming every
  report was written in Chinese.
- Check every `PostMessage`/`Reg*` return value when a failure would be silent.
- Keep the exe small: `-Os`, static CRT, no iostream.

## Commits and pull requests

- One logical change per commit; the message says what breaks without it.
- Update `CHANGELOG.md` under an `Unreleased` heading for anything user-visible.
- If you add a flag, add it to `UsageText()` in `src/main.cpp` in all five
  languages, and to the table in both usage documents. Keep the exit-code
  contract intact: `0` success, `1` residues found by `--status`, `2` usage
  error. A token the parser does not recognise must fail loudly — falling
  through to "start the tray app" is how a typo becomes a silent no-op.

## Releasing

[docs/RELEASING.md](docs/RELEASING.md) lists every file that carries the version,
the eleven gates, and how an artefact is built, verified and published.

## Docs

Screenshots in `docs/images` are captures of the running binary, so they must be
regenerated after any change to the menu or the report:

```bat
python tools\capture-screenshots.py zh
python tools\capture-screenshots.py en
```

The script drives the real windows, so build first and close anything that would
photobomb the popup.

## Reporting a bug

Include the Windows build number (`winver`), whether ExplorerPatcher or a
similar shell mod is installed, the output of `ExplorerF11.exe --status`, and the
relevant lines from `%TEMP%\ExplorerF11.log` if you ran with `--log`.

Behaviour that depends on undocumented shell internals can change between
Windows builds. A report that names the build number is worth ten that do not.
