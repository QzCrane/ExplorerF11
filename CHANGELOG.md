# Changelog

All notable changes to this project. Versions follow [SemVer](https://semver.org/).

`1.0.0` is the first release. The numbers before it were internal build numbers
used while the tool was still being shaped; none of them was ever published, and
they are kept below as build history rather than as releases.

## 1.0.2 - 2026-11-16

Maintenance release. It ships the two post-release audit fixes that were
committed after the 1.0.1 tag but never reached its Release asset, and moves the
compilation baseline from C++17 to C++23. No documented behaviour changes.

### Fixed

- **Tools reading `VS_FIXEDFILEINFO` saw 1.0.0.0.** `src/app.rc` still carried
  the numeric `FILEVERSION`/`PRODUCTVERSION` fields from 1.0.0 while the string
  values said 1.0.1. Both now follow `EF11_VERSION`, and `tests/test_icons.py`
  asserts the raw fields against `--version` so the mismatch cannot recur.
- **The English residue report printed "1 entries".** The tray-bookkeeping line
  now selects `entry` or `entries` by count; `tests/test_residue_report.py`
  locks the branch.

### Changed

- **Compilation baseline is C++23** for MinGW (`-std=c++23`), MSVC
  (`/std:c++23`) and CI. The sources use no C++20/23-only library facilities, so
  a toolchain limited to C++17 can still build them by changing one flag in
  `Makefile` or `build.bat`.

### Delivery

- Both READMEs now show the application icon. The PNG is generated from the
  same master as the embedded ICO by `tools/make-icons.py`.
- The 1.0.1 Release body was rewritten: it had been a verbatim copy of the 1.0.0
  text, with stale filenames, checksums and gate counts. Release verification
  now reads the published body back before a version is called done.

## 1.0.1 - 2026-11-16

Patch release. Six defects found in a post-release audit. None was covered by CI
or the existing suites: the shell-hook, recovery and console paths are driven by
live OS events that a runner cannot reproduce deterministically. Each fix is
pinned by a source-contract assertion in `tests/test_robustness.py`.

### Fixed

- **Explorer restart could leave an orphan tray icon.** When Windows restarted
  Explorer and re-registering the shell hook failed, the tool relaunched itself
  (`RelaunchSelf` calls `DestroyWindow` synchronously) and then still added a
  tray icon on the now-dead window handle — an icon that could never be clicked
  or removed except by restarting Explorer again. The failure branch now returns
  immediately; the fresh instance rebuilds the tray in its own `WM_CREATE`.
- **One stuck fullscreen could hide another.** Partial F11 delivery was tracked
  in a single `g_risk` slot with one timer, so a second failure within 500 ms
  overwrote the first and left its window stuck in fullscreen. Recovery now
  keeps a list of at-risk windows and processes them all.
- **Recovery could poke or unmark the wrong window.** It trusted `IsWindow()`
  alone; a handle recycled onto a different window in the 500 ms gap would be
  sent F11 and have its marks removed. Each entry now carries the mark tick as
  an identity token — a recycled or re-accelerated window fails the check and
  is left untouched.
- **`CONOUT$` handle leak.** `ConsoleOut()` created a console handle on the
  third resolution path that was never closed. It now reports ownership and
  `Emit()` closes only the handle it created.
- **System shared icon could be destroyed.** The fallback icon from
  `LoadIconW(NULL, IDI_APPLICATION)` is system-owned but `WM_DESTROY` destroyed
  all icon handles unconditionally. The fallback now takes a private copy.
- **A bare `--lang` was misreported or swallowed the next flag.** A trailing
  `--lang` was called an unknown option, and `--lang --quiet` consumed `--quiet`
  as a language tag. It now prints a dedicated "requires a language tag" message
  in all five languages and never eats a following option.

### Added

- `tests/test_robustness.py`: 24 assertions covering all six fixes — source
  contracts for the event-driven paths, behavioural CLI checks for argument
  parsing, and ownership checks for the console handle and the fallback icon.

### Post-release audit (fixes shipped in 1.0.2)

A repository-wide audit of the CI workflow, build scripts, test suites,
translation pipeline, GitHub templates and the remaining source files found two
more defects that the release gates missed:

- **Binary version block stayed at 1.0.0.0.** The 1.0.1 bump updated the
  StringFileInfo `FileVersion`/`ProductVersion` strings but not the numeric
  `FILEVERSION`/`PRODUCTVERSION` fields in `app.rc`, so tools reading
  `VS_FIXEDFILEINFO` reported 1.0.0.0. `test_icons.py` now asserts the
  `FileVersionRaw`/`ProductVersionRaw` values as well, and a regression check
  confirmed the new assertion fails against the old block.
- **"1 entries" in the English residue report.** The tray-bookkeeping line
  always used the plural `entries`, so a single record read `1 entries`. It now
  selects `entry`/`entries` by count, matching the existing item formatter.

The suite grew from 319 to 323 assertions. Every file in the repository was
reviewed; the rest of the audit found either correct behaviour or documented
design trade-offs (notably: CI runs a stable six-gate subset while the twelve
local gates include desktop-dependent suites; Prefetch bytes are counted in the
report total because the item is genuinely removable by an elevated `--clean`).

### Measured

Resource figures were re-measured on the 1.0.1 binary after the icon and handle
fixes: 367 KiB on disk, 1.87 MB private, 135 handles, 4 threads shortly after
start-up (three pool workers retire after about 45 s idle), 0.03 s cumulative
CPU per two minutes. The 1.0.0 figures below were accurate for that build; the
difference is not a regression.

## 1.0.0 - 2026-11-16

First release.

### What it does

- **Event-driven F11 acceleration for Windows 11 File Explorer.** A shell hook
  watches for folder windows and posts the two F11 cycles each one needs, so a
  new window opens without the address bar and the command bar competing for
  space.
- **Acceleration is counted in windows, not tabs.** F11 is handled by the window
  frame, so one round trip covers every tab in that window at once; a tab has no
  F11 state of its own and is never accelerated separately. The bracketed figure
  in the status line is how many tabs those windows currently hold.
- **The default configuration writes nothing.** No registry value, no file. A
  value appears only when a setting leaves its default, when autostart is
  ticked, or when the UI language is switched, and returning to the default
  deletes it again.

### Added

- **Five UI languages**: 简体中文, 繁體中文, English, 日本語 and 한국어,
  switchable at run time. Every menu row, tooltip, help text, report field and
  report-window button is translated.
- **A translation pipeline with a build gate.** `tools/i18n_strings.json` is the
  extracted source key list, `tools/translations.json` is the single source of
  truth for the three non-inline languages, and `tools/gen_i18n.py` emits
  `src/i18n_extra.cpp`. `tools/check_i18n.py` fails on a missing key, a missing
  translation, a mismatched placeholder or a stale generated table.
  `tools/audit_i18n.py` adds the checks a coverage gate cannot make: wrong script
  inside a translation, ASCII punctuation glued to CJK text, and a target term
  that contradicts the one chosen elsewhere.
- **The residue report refreshes while it is open.** Toggling autostart, the
  new-tab setting or the start-up sweep rebuilds the body immediately; so do
  pause/resume and a language change.

### Changed

- **One concept, one word**: 残留 / residue / 残留 / 잔여물 in Chinese, English,
  Japanese and Korean. The marketing-style "zero footprint" framing was replaced
  by a factual description of the default write policy. Internal modules,
  headers, tests and documents were renamed from `footprint` to `residue`.
- **One name per language, everywhere.** The menu row, the ticked radio and the
  report header all use the same endonym from `i18n.h: LangName()`, so a
  Traditional Chinese report can no longer claim to be written in Simplified
  Chinese, and the row that switches back stays readable after a mis-click.
- **`--lang` accepts five tags** (`zh`, `zh-Hant`, `en`, `ja`, `ko`) and common
  BCP-47 regional aliases. `--help` documents all of them.
- **The report states its scope neutrally**: every possible location is listed
  with its result, present or absent.

### Fixed

- **The tray hover tooltip no longer disappears.** Under `NOTIFYICON_VERSION_4`
  the shell suppresses the standard tip unless `NIF_SHOWTIP` is set, and
  `NIM_MODIFY` replaces the flag set instead of merging it. Every tip update now
  re-asserts `NIF_SHOWTIP` together with `NIF_TIP`.
- **The report header named the wrong language.** The language was baked into a
  translated fragment, so every non-English report claimed one fixed language.
  The name is now appended at run time from the active language.
- **Japanese used 残骸 (wreckage) for a leftover registry value.** The domain
  term is 残留, which also matches the Chinese and Korean wording.
- **Japanese and Korean verdicts no longer duplicate the counter** ("1 件 件を
  削除", "1 개개 정리"); the connector fragments were corrected.
- **The MSVC build decoded the sources with the ANSI code page.** They are UTF-8
  without a BOM and carry CJK wide literals, so `cl` needed `/utf-8`; without it
  a Japanese string compiled correctly only on a Japanese machine.
- **Control Panel was accelerated on non-English Windows.** The filter matched
  only the English and Simplified Chinese window titles; it now covers all five
  shipped languages.
- **The test baseline assumed the binary had run before.** Windows writes
  MuiCache and the compatibility store on the first launch of any exe, so the
  read-only assertions failed on a clean machine until one warm-up run was added.
- **An unknown option started a tray instance instead of failing.** A typo such
  as `--cleen` left a running process that looked like it had done the work.
  The parser now echoes the offending token, points at `--help` and exits 2;
  the same path covers `--lang` without a value and `--lang` with a tag that
  names no supported language.
- **The published resource profile was stale.** The documented 333 KB / 3.5 MB /
  148 handles described a build from before the icons were embedded. Re-measured
  on the shipped binary: 366 KiB, 2.3 MB private, 156 handles, one thread after
  the shell hook's three pool workers retire, 0.031 s cumulative CPU over the
  first two idle minutes. `docs/ARCHITECTURE.md`, `docs/RESEARCH.md` and both
  READMEs now carry the measured figures.

### Tests

- Eight suites drive the built binary rather than a mock, plus three static
  gates (translation coverage, translation quality, help-column alignment).
- `test_lang_names.py` pins the naming invariant: the five language rows are
  byte-identical in all five UI languages, and each report header names the
  language that is actually active.
- `test_language.py` covers all five languages for command-line, environment and
  tray switches, and checks that an already-open report window repaints its
  title, body and all three buttons.
- `test_menu_order.py` pins the five-row language submenu and the localised menu
  in all five languages.
- `test_residue_report.py` verifies the five-language report structure and guards
  against duplicated counters.

## Pre-release history

Internal build numbers, never published. Kept for the record. The last of
them, build 6.3.0, is what shipped as 1.0.0.

### build 6.2.0 - 2026-11-15

The release that makes the program look and behave like something installed
rather than something compiled.

### Added
- **Real icons.** `src/app.rc` embeds a running icon, a paused icon and a version
  block; `tools/make-icons.py` draws them from geometry. Nine frames each (16-256)
  so the shell gets the pixel size it asks for at 100 %, 150 % and 200 % scaling.
  Explorer, the taskbar, Alt+Tab and the report window finally show the product
  mark instead of the generic blank document.
- **The tray picture carries the state**: blue bolt while running, grey while
  paused.
- **Live report window**: opening or closing folder windows, pausing, resuming or
  switching language rebuilds the body in place, keeping the scroll position.

### Changed
- **One clean entry, and it asks first.** The tray menu's "clear all traces and
  exit" item and the report window's unconfirmed button were two different
  behaviours for the same destructive act. The menu item is gone; the report's
  **Clean up…** is the only place that deletes, it lists every category before
  doing so, and it no longer quits afterwards - the list simply refreshes.
- **Tooltip freshness**: `NOTIFYICON_VERSION_4` plus a push on every state change.
  The hover text can no longer show a count from minutes ago.

### Removed
- The v4 `ExplorerF11Ultra` migration path and the three "legacy leftovers" rows
  it fed. The report now covers 11 locations in three groups; nothing in it
  describes a predecessor this program does not have.

### build 6.1.1 - 2026-11-15

Terminology fix. The status line said "N windows" while a user could see two tabs
in one window and had no way to reconcile the two numbers; the new-tab setting
also implied that a tab could be accelerated on its own, which it cannot.

### Changed
- **The unit is stated and shown in full**: the tooltip, the menu header and the
  residue report now read "已加速 1 个窗口（含 2 个选项卡）" / "1 window
  accelerated (2 tabs)". The figure before the bracket is the unit of the action;
  the bracket is what those windows currently hold. Both are produced by one
  function in `residue.cpp`, so the three surfaces cannot drift apart.
- **`新标签页也加速` → `新建选项卡时重新加速窗口`** ("Accelerate new tabs" →
  "Re-accelerate the window on new tabs"). The old label claimed a per-tab
  action; F11 is handled by the window frame, and a tab has no F11 state.
- **Chinese terminology follows Windows**: 选项卡, the term Microsoft uses in the
  Simplified Chinese Explorer UI and documentation, instead of 标签页.
- `--help`, both READMEs, `USAGE` (both languages) and `ARCHITECTURE` define the
  unit and explain why tabs are contents, not a second unit.

### Tests
- `test_menu_order.py` takes the expected version from `--version` instead of
  hard-coding it, matches the status line against a complete pattern, requires the
  tab count whenever a window count is shown, and asserts that `--help` documents
  the unit in both languages.

### build 6.1.0 - 2026-11-15

Language-switching release. The UI was bilingual since 6.0.0 but could only be
changed before start-up; now it can be changed from the tray, while the program
is running, and the choice survives a restart.

### Added
- **Language submenu in the tray** (`Language` / 界面语言): 简体中文 and
  English, as a radio pair, each written in its own language so the menu stays
  usable after switching to a language you do not read. The switch is immediate:
  the menu, the tooltip and an already-open residue window all follow.
- **The choice is persisted** in `HKCU\Software\ExplorerF11\Language` and used
  on the next start, but only while it differs from the system language.
  Picking the system language deletes the value and prunes the empty key, so a
  user who never opens that submenu still writes nothing at all.
- **Tray tooltip** now carries the version and the live state (windows
  accelerated / paused / waiting).
- **Residue report header**: program path, generation time, UI language and
  the number of locations inspected.
- **`tests/test_language.py`**: 28 checks covering the resolution order,
  persistence, live switching of an open report window, `--lang` precedence and
  the zero-write rule.

### Changed
- **Every user-visible string rewritten** to state exactly what happens and what
  it costs, in both languages: menu items, help text, residue notes, clean
  confirmation and result dialogs.
- Residue items now carry an explicit `removable` / `kept` tag, absent items
  are no longer labelled "nothing to remove" (the state line already says
  absent), and the verdict reports per-group counts with correct English plurals.
- `--menu` dumps submenus as indented rows, so the language pair is asserted by
  the same test as the rest of the menu.
- The clean confirmation lists every category that will be deleted instead of
  summarising them.
- The report window picks the UI font that belongs to the language (Microsoft
  YaHei UI / Segoe UI).
- `tests/test_menu_order.py`, `test_residue_report.py`, `test_tray_cleanup.py`
  and `test_smoke.py` now assert and exit non-zero on failure, instead of
  printing a report for a human to read.

### Fixed
- Mixed-script typo in the `--uninstall` message (其余 was written as 其
  followed by a literal 余).
- The "cannot register for shell events" error box was the only string that
  bypassed localisation.

### build 6.0.0 - 2026-11-15

Repository and architecture release; same behaviour as 5.3 plus a complete
residue model.

### Added
- **Bilingual UI** (Chinese / English), chosen at start-up from `--lang`,
  `EXPLORERF11_LANG` or the Windows display language. No resource DLL. (6.1.0
  made the choice switchable while running.)
- **Full residue report** (`--status`, tray window): 14 items in four groups -
  what this program wrote, what Windows recorded because it ran, legacy v4
  leftovers, and the program file itself. Each item shows who wrote it, the exact
  location, current contents and byte count.
- **`--clean` now removes everything removable**, including Windows' own
  bookkeeping: tray-icon cache, StartupApproved flag, Compatibility Assistant
  store, MuiCache name, UserAssist counters and Prefetch entries.
- `--help`, `--version`, `make test`, GitHub Actions build.

### Changed
- Source split into `main.cpp` / `config.cpp` / `residue.cpp` with `app.h`,
  `i18n.h`; no behaviour change intended.
- Default build output moved to `dist/ExplorerF11.exe`.
- Tests moved to `tests/` and made path-independent.

### Fixed
- Report punctuation and singular/plural wording in the menu header.
- Language detection now also consults the regional locale, so an English UI on
  a Chinese region still gets Chinese.

### build 5.3.0 - 2026-11-15

- Tray menu rebuilt: one grey status line, then actions / settings / maintenance /
  exit. Destructive item separated from Exit.
- "Apply to current window" now targets the last folder window the shell reported
  as activated, instead of the foreground window (which is the taskbar at click
  time, or our own hidden window).
- `--menu` dumps the real menu for tests.

### build 5.2.0 - 2026-11-15

- Registry residue report: menu shows clean / N places, window lists each
  location with writer, path, contents and size, and can clean in place.
- `--status` prints the report; exit code 0 = clean, 1 = traces.

### build 5.1.0 - 2026-11-15

- Autostart honours and clears Windows' `StartupApproved` flag, so the tick mark
  matches reality after a Task Manager disable, and re-enabling works.

### build 5.0.0 - 2026-11-15

- Renamed to ExplorerF11. Zero registry writes in the default configuration;
  returning a setting to its default deletes it and prunes an empty key.
- `--clean`, automatic migration of the v4 key and Run value.

### build 4.0.0 - 2026-11-15

- Preferences persisted in `HKCU\Software\ExplorerF11Ultra`; the former
  `--no-initial` became a tray toggle; self-relaunch reuses the command line.

### build 3.1.0 - 2026-11-15

- Start-up sweep for windows that already existed; restore-from-minimized hook.

### build 3.0.0 - 2026-11-15

- New tabs: WinEvent hook on `ShellTabWindowClass` child creation.

### build 2.0.0 - 2026-11-15

- Hidden top-level window so `TaskbarCreated` reaches us; shell hook and tray
  survive an explorer restart.
- Per-window `SetPropW` marker instead of an HWND set; every `PostMessage`
  checked, with a recovery that can only ever exit fullscreen.

### build 1.0.0 - 2026-11-15

- First working build: shell-hook driven, posts two F11 cycles per folder window.

## Pre-history

Behavioural research on the F11 trick, the available third-party tools and the
rejected approaches (AutoHotkey scripts, ViVeTool feature flags) is documented in
[docs/RESEARCH.md](docs/RESEARCH.md). None of them shipped in this repository.
