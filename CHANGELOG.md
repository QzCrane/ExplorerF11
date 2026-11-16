# Changelog

All notable changes to this project. Versions follow [SemVer](https://semver.org/).

`1.0.0` is the first release. The numbers before it were internal build numbers
used while the tool was still being shaped; none of them was ever published, and
they are kept below as build history rather than as releases.

## 1.0.5 - 2026-11-16

The count of accelerated windows only ever went up. Closing a folder window left
the tray tooltip, the menu header and an open residue report showing the old
number until some later event happened to refresh them.

The shell reports `HSHELL_WINDOWDESTROYED` while the window still exists and
still carries the mark — measured: `IsWindow` and `IsMarked` both true, the
properties gone about 50 ms later. The handler rebuilt the surfaces at that
instant, so the read still counted the dying window; and because the report
refreshes from the snapshot taken at that instant, nothing read the desktop
again afterwards. The rebuild now waits for a 60 ms one-shot timer, by which
time `IsWindow` says the window is gone and the maintained set drops it. Bursts
of closes collapse into the one timer. The binary is 420,864 bytes (411 KiB),
the same as 1.0.4: the fix costs a timer and a message handler, not a structure.

### Tests: the mirror assertions are gone

Roughly fifty assertions in `test_robustness.py` and `test_icons.py` were of the
form "this exact line is in `main.cpp`". They went red when a rename preserved
behaviour and green when the guarded code was dead — which is what the count bug
above was: the line `IsMarked(gone)) OnStateChanged();` was present and its
contract test passed while the feature was broken.

Every guarantee that could be observed from outside now is:

- `test_smoke.py` opens and closes real windows and reads the report the program
  drew: the start-up sweep and `--no-initial`, the count following a close, and
  the tray surviving a `TaskbarCreated` (same pid, hook re-registered, events
  still arriving). It also asks the report window for its icons with
  `WM_GETICON` instead of grepping `WM_SETICON`.
- `test_residue_report.py` plants a UserAssist entry whose value name is
  `ROT13(path)`, the way Windows stores it, and requires the report's count to
  rise by exactly one — the rotation is the only thing that makes detection work.
- What is left in `test_robustness.py` is marked `WHITE-BOX`, one assertion per
  defect that has no outside trigger, each naming the observation that is
  missing. They assert a property (a call-site count, a forbidden pattern, an
  ordering), never a formatted line.

Each of the new assertions was checked by putting the defect back: reverting the
timer, ignoring `--no-initial`, dropping the tick comparison, removing the
memoised early return and adding a second `PROP_MARK` writer all go red.

## 1.0.4 - 2026-11-16

A pass over every behaviour, speed and memory alike, not just the two that had
been measured, plus one defect the pass exposed. Nothing here changes what the
program does: the tray, the menu, the report and the CLI print the same bytes.

### Memory

- **The icons no longer load the imaging stack.** Both .ico files stored all nine
  sizes as PNG, so `LoadImageW` decoded them through WIC, and that one call
  brought `WindowsCodecs.dll` (2.3 MB of code pages) into a tray process whose
  actual bitmaps are 16x16. The sizes this program loads - 16, 20, 24, 32, 40, 48,
  i.e. every DPI a tray icon and a title bar ask for - are now stored as
  uncompressed DIB, where no decoder is involved. The large sizes stay PNG:
  Explorer decodes those in its own process when it draws a thumbnail, so they
  cost this program nothing and keep the file small. Measured on the tray:
  private commit 1912 -> 1812 KB, working set 11264 -> 10384 KB (-8%), and
  `WindowsCodecs` is no longer in the module list. The pixels are identical -
  `LoadImageW` on the old and new files produces the same 16x16 BGRA bytes,
  checked by hash for both icons and both states. The cost is 41 KiB of disk
  (370 -> 411 KiB), 38 of them the two icon files themselves: a DIB is bigger
  than the PNG it replaces. `make-icons.py`
  now runs the conversion as part of generating the icons, so a regenerated icon
  is correct by construction; `make_ico_bmp.py` does the rewrite and refuses to
  write a file whose pixels differ. Regenerating from geometry reproduces the
  shipped bytes exactly.
- **What the memory audit could not improve, and why.** An empty Win32 message
  loop built with these flags already commits 1584 KB, so 87% of the 1812 KB is
  the floor of a static-CRT program plus the DLLs the loader brings; the tray's
  own share is ~180 KB and the program's data is ~36 KB. `msctf.dll` (1.4 MB)
  appears because the program owns an ordinary top-level window, and the
  alternative - a message-only window - would stop receiving the system
  broadcasts the DPI and theme handling depends on. The report window costs
  ~584 KB private and 6 MB of working set the first time it opens, of which
  ~384 KB is the frame alone: on Windows 11 a visible frame pulls in the
  compositor's UI stack. None of that is reachable from this code. Numbers and
  the method are in `docs/PERFORMANCE.md`.

### Performance

- **The marked-window set is maintained instead of rediscovered.** The count on
  the tooltip comes from walking every top-level window and reading our property
  on each one. On a 360-window desktop that walk measured ~0.26 ms, and 88% of
  it was `GetPropW` - the enumeration alone was 0.04-0.09 ms. `Mark()` is the
  only place the property is set, so it now reports the handle; every read
  re-validates the recorded handles with `IsWindow` + `GetPropW`, and the first
  read seeds from one full walk so marks left by an earlier run are still
  counted. Same answer, 0.26 ms -> 0.002 ms (measured back to back in one
  process, 147x). This is the path behind every hover and every state change, so
  it also takes the report and the menu with it: a full report build dropped
  1.52 ms -> 1.03 ms (-32%).
- **`UserAssist` is searched with a rotated needle.** ROT13 is a per-character
  bijection that commutes with case folding, so looking for the decoded name in
  the decoded string is exactly the same as looking for the rotated name in the
  raw string. One rotation per scan replaces a string build and a per-character
  pass per value: 88 us -> 50 us over the 309 names on this machine (-43%). The
  clean path uses the same hoist. `tools/bench_ua_match.cpp` proves the
  equivalence against the live registry and prices the alternatives -
  `StrStrIW`, the obvious "use the system's search" answer, was 19x slower.
- **The tray is pushed only when its surface changes.** Every update is a
  cross-process round trip to explorer (~1.2 ms), and most state changes end in
  the same two lines of text: apply-all over windows that are already marked, a
  second sweep, the recovery timer finding nothing at risk. `PushTraySurface()`
  compares the freshly built tip and icon with what the shell was last told and
  returns without an IPC when they match. The comparison is against live state,
  not a cache, so a stale surface still corrects itself on the next event or
  hover. `NIN_POPUPOPEN` now costs one mark lookup (~0.002 ms) and no round trip
  instead of a full walk plus a round trip.
- **The tray menu asks "is it there", not "what does it contain".** The label
  shows a count of residue categories, but the builder ran the full eleven-probe
  scan - every value of every UserAssist GUID, every tray record - to get it.
  `CurrentResidueCategories()` uses the same presence rules and stops at the
  first hit in each scan. Measured 1.29 -> 1.00 ms per menu open on this
  machine; the gain is larger on a machine where the program's own records
  exist early in a scan, which is every machine that has run it.
- **An event burst rebuilds an open report once.** A full rebuild re-probes
  eleven locations (~1.0 ms). Ten windows opening in a row used to run it ten
  times to paint one final state; the event now marks the report dirty and posts
  a single refresh. The rebuild still reads live system state - nothing is
  cached - so the window is never stale, only rendered once.
- **"Copy all" copies what is on screen instead of rebuilding it.** It used to
  run the whole probe pass a second time to produce bytes the edit control was
  already holding.
- **One registry open for both boolean settings.** Startup and `--menu` read
  `Tabs` and `InitialSweep` with two separate opens of the same key.
- **The code is about 3 KiB larger.** The executable went from 370 to 411 KiB,
  but 38 of those 41 are the icon files; the maintained set, its validation and
  the measured button row are the rest. `-flto` would have paid for it, but this
  toolchain is built without LTO support, so it is not an option here rather
  than a choice.

### Tests

- `tests/test_robustness.py` replaces the 1.0.3 "one IPC inside
  `OnStateChanged()`" contract with the sharper one: one push function, one
  `NIM_MODIFY`, no call at all when the surface is unchanged, and no accounting
  when the push failed. It also pins the coalesced refresh, the copy-without-
  rescan path, `--no-initial`, that the menu count always equals the report
  count, that `PROP_MARK` has exactly one writer which reports to the set, that
  reads validate with `IsWindow` + `GetPropW` and never re-enumerate, that the
  `UserAssist` scan keeps its needle rotation, and that both icon files keep
  their 16-48 sizes as DIB with the 256 size still present. Suite total: 369
  assertions.
- `tools/bench_probes.cpp` breaks the report cost down per probe, which is what
  showed `UserAssist` (48%) and the tray-icon store (28%) to be the two rows
  worth measuring at all.
- `tools/verify_marks.cpp` compares the maintained set against a fresh walk over
  a live desktop in seven states - leftover mark before the first read, double
  report, property removed behind the set's back, guarded unmark, real unmark,
  destroyed window - so the 147x is not bought with a wrong number.
- `tools/bench_ua_match.cpp` proves the ROT13 equivalence on the names actually
  present and prices four search strategies on the same data.
- `tools/measure_mem.cpp` walks a process's address space with `VirtualQueryEx`
  and groups committed pages by type, module and protecting. Working set alone
  cannot tell shared DLL pages from this program's own memory; this is what
  showed that 87% of the commit is a floor.
- `tools/mem_floor.cpp` builds the same executable with progressively more of
  what the program does - message loop, tray icon, registry scan, a report-shaped
  window with an EDIT - so each layer of memory has a measured boundary instead
  of an attributed guess.
- `tools/verify_handles.cpp` calls the real collection, report and mark readers
  300 times each in one process and fails if the handle count grows. It stayed at
  78 throughout, which is what ruled a handle leak out.
- `tools/icon_probe.cpp` loads one 16x16 icon three ways - `LoadImageW`,
  `CreateIconFromResourceEx`, `CreateIconIndirect` - and hashes the pixels back
  out of the HICON, so the icon change is proven identical at the pixel level
  rather than at the file level.

### Fixed

- **The English "Clean residues..." button no longer clips its label.** The
  report's three buttons were a fixed 118 px wide, which fits the five-character
  CJK labels but not their English translations; the English UI drew
  "lean residues..." because the first character fell outside the button. Each
  button is now measured from its own text in its own font, so every language
  gets a whole label and the row is no wider than it needs to be.
- `--no-initial` was parsed into `g_initial` and then overwritten two statements
  later by the persisted setting, so the flag had never skipped a sweep. It is a
  run-scoped flag now: this run's start-up sweep is skipped, the stored setting
  and the menu tick are untouched.

## 1.0.3 - 2026-11-16

Maintenance release. It lowers the cost of a tray hover, makes the residue
report test deterministic, and repairs the version-bump tool that had made
1.0.2's facts drift possible. The 370 KiB single-file profile is unchanged.

### Performance

- **One tray IPC per state change, not two.** `OnStateChanged()` is the funnel
  for nine behaviours — window created, destroyed, restored, new tab, pause,
  apply, apply-all, partial-post recovery and the start-up sweep. Each one used
  to send two `Shell_NotifyIconW(NIM_MODIFY)` cross-process round trips to
  explorer (icon, then tip). A single modify now carries `NIF_ICON | NIF_TIP |
  NIF_SHOWTIP` together — the same flag set `AddTray()` already uses — so the
  shell sees no difference. Measured cost of one `NIM_MODIFY` is ~1.2 ms; the
  merged path saves ~0.49 ms per state change (median of two 400-iteration A/B
  runs; Explorer's own message pump makes the absolute figure noisy, the
  call-count reduction is exact). `UpdateTrayTip()` remains for `NIN_POPUPOPEN`
  and language changes, which refresh text without touching the icon.
- **Tooltip refresh no longer walks every child of every window.** Tab counting
  used `GetWindow(GW_CHILD)` plus `GetClassNameW` on each sibling; it now uses
  `FindWindowExW` with `ShellTabWindowClass`, which does the class match inside
  user32 and returns only direct children. A/B on the same machine, 1000
  `NIN_POPUPOPEN` events per run: ~718/547 ms before, ~438/578 ms after
  (median ~633 -> ~508 ms, about 20% less CPU per hover).
- **One window snapshot per state change and per menu open.** `OnStateChanged()`
  and `BuildTrayMenu()` previously enumerated windows twice - once for the
  tooltip/header and again inside `BuildResidueReport()`/`CurrentTotals()`. The
  snapshot is now passed down; the report and the tooltip still refresh in the
  same message dispatch, so nothing is stale.
- **One allocation instead of four while building the report.** The eleven
  `Residue` rows are reserved up front and the report string reserves its
  typical size. No output changes.

### Tests and release tooling

- `tests/test_residue_report.py` now creates a marked `CabinetWClass` window
  with one `ShellTabWindowClass` child before taking the report. The tab-count
  assertion used to depend on whether an Explorer window happened to be open;
  it is now reproducible and checks both languages. The measured suite total
  is 329 assertions.
- `tools/bump_version.py` had an unreachable `SECURITY.md` rule that aborted a
  bump after five files had already been rewritten, and an `ASSET` rule whose
  replacement added a second `% VERSION`. Both are fixed; version-derived
  strings now come from one script and are checked by the facts gate.
- `tools/bench_hotpaths.cpp` (`make bench`) makes the performance figures above
  reproducible: warmed-up `QueryPerformanceCounter` medians per 1000 calls for
  every hot path. It is a measuring stick, not a gate. `test_robustness.py` adds
  seven source-contract checks pinning the single-IPC `OnStateChanged()` so the
  double round trip cannot return; the suite total is 329 assertions.

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

- **Compilation baseline is C++23.** MinGW and CI use `-std=c++23`; MSVC uses
  `/std:c++latest` because VS 18's `cl` rejects `/std:c++23` as an unknown
  option and then compiles as C++14, which fails on every inline variable in
  `app.h`. The sources use no C++20/23-only library facilities, so C++17 remains
  a one-flag fallback on older toolchains.

### Delivery

- Both READMEs now show the application icon. The PNG is generated from the
  same master as the embedded ICO by `tools/make-icons.py`.
- The 1.0.1 Release body was rewritten: it had been a verbatim copy of the 1.0.0
  text, with stale filenames, checksums and gate counts. Release verification
  now reads the published body back before a version is called done.
- Version-derived numbers now come from `tools/release_facts.py`. A new gate,
  `tools/check_release_facts.py`, fails the build when any current document
  disagrees; `make refresh-facts` re-derives the facts from the source, the
  built exe and a full test run. A version bump is `python
  tools/bump_version.py X.Y.Z`, not a search-and-replace across a dozen files.

### Measured

The C++23 binary is 370 KiB (378,368 bytes); the sampled resource profile is
unchanged at 135 handles, four transient threads settling to one, and under
2 MB private. The 1.0.1 figures below describe that build, not a regression.

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
