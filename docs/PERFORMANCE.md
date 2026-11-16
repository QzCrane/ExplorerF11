# Performance

This document is the cost model for every behaviour the program has, what each
one measured, what was changed, and what was deliberately not changed. It exists
so a performance claim can be checked instead of believed: every number below
comes from `make bench` on a normal desktop, and the commands to reproduce it
are at the end.

The program is idle when nothing happens — no polling, no timers except the
one-shot recovery — so "performance" here means three different budgets:

| Budget | Behaviours | Target |
|---|---|---|
| per shell event | window created/destroyed/activated, tab created, restored, recovery | microseconds of our own work, at most one cross-process call |
| per user action | tray menu, apply, pause, toggles, language, report open/refresh/copy/clean | a few milliseconds, below what a menu animation hides |
| per process | start-up, `--status`, `--menu`, `--clean` | dominated by the Windows loader, not by us |

## The unit that matters

Almost everything expensive in this program is a **cross-process call into
explorer or the registry**. Measuring them individually is what turned the
optimisation list from guesswork into an order:

| Call | Cost (median, this machine) |
|---|---|
| `Shell_NotifyIconW(NIM_MODIFY)` | ~1.2–1.7 ms |
| `GetPropW` on one window | ~0.68 µs |
| `GetClassNameW` on one window | ~0.30 µs |
| `EnumWindows` over ~360 top-level windows | ~0.04–0.09 ms |
| one registry value enumeration step | ~2 µs |
| `RegOpenKeyExW` + one query | ~5 µs |
| `GetFileAttributesExW` | ~10 µs |

Two of these decide most of the design. A shell event may not spend 1.2 ms, so
the tray IPC has to be justified per event. And the 360-window walk is cheap
while *reading a property on each window* is not — the walk is 0.04–0.09 ms, the
same walk with one `GetPropW` per window is 0.26–0.33 ms. That 88% is the
property read, and it is the single hottest line in the program.

## Behaviour inventory

Every entry point, what it did in 1.0.3, and what it does now. "Push" means one
`NIM_MODIFY` carrying icon + tip.

### Passive: driven by the shell

| Behaviour | Work in 1.0.3 | Work now |
|---|---|---|
| `HSHELL_WINDOWCREATED` | filter + 4 posts + snapshot + 1 push | same, snapshot is a set lookup, push skipped when the tip is identical |
| `HSHELL_WINDOWDESTROYED` | `GetProp` gate + snapshot + 1 push | same, snapshot is a validated set |
| `HSHELL_WINDOWACTIVATED` | class + title check, remember target | unchanged (no snapshot, no IPC) |
| tab created (`EVENT_OBJECT_CREATE`) | class check on every window creation in the system, then 4 posts + push | unchanged; a non-tab costs one `GetClassNameW` |
| restored from minimized | class + title + 4 posts + push | same, push skipped when nothing changed |
| recovery timer (500 ms, one-shot) | token check + optional 2 posts + push | unchanged; push skipped when nothing was at risk |
| `TaskbarCreated` (explorer restart) | re-register + remove + add tray | add builds the tip once instead of twice |
| `NIN_POPUPOPEN` (hover) | full window walk + **1 push** | set lookup (~2 µs) + **no push** when the tip is unchanged |
| `NIN_POPUPCLOSE` | nothing | nothing |
| tray click | menu build (see below) | menu build, cheaper count |
| `WM_ENDSESSION` / `WM_DESTROY` | remove tray, unhook, free icons | unchanged |

### Active: driven by the user

| Behaviour | Work in 1.0.3 | Work now |
|---|---|---|
| open tray menu | snapshot + target search + **full 11-probe scan** + autostart check | set lookup + target search + **presence-only scan** + autostart check |
| apply to active window | target search + 4 posts + push | same, push skipped when nothing changed |
| apply to all | `EnumWindows` sweep + push | same, push skipped when nothing changed |
| pause / resume | push (icon + text change) | push (still changes) |
| tabs / initial / autostart toggle | registry write + report refresh | registry write + one coalesced refresh |
| switch language | tray push + report rebuild | tray push + report rebuild (both still needed) |
| open report | full scan + CRLF conversion + `SetWindowText` | unchanged |
| report refresh on event | **full scan per event** | **one full scan per burst** |
| copy all | a second full scan | reads the edit control |
| clean residues | clean + report + push | unchanged |

### Command line

| Behaviour | Work | Note |
|---|---|---|
| `--version`, `--help` | build a string, write it | ~10 ms end to end, all loader |
| `--status` | one full scan + one write | the scan is the point |
| `--menu` | one presence scan + autostart check | same builder the tray uses |
| `--clean` | close running copy, delete, report | unchanged |
| `--install` / `--uninstall` | two registry writes / one delete | unchanged |
| no arguments | mutex, one config open, tray add (3 pushes), two hooks, sweep | one registry open instead of three |

## What changed, layer by layer

### 1. The marked-window set is maintained, not rediscovered

The count on the tooltip is "how many top-level windows carry our property".
1.0.3 answered it by walking every top-level window and reading the property on
each. Measured on a 360-window desktop: the walk alone 0.04–0.09 ms, the same
walk with one `GetPropW` per window 0.26–0.33 ms. **88% of the cost was the
property read**, and the answer changes only when a window is marked or
destroyed.

`Mark()` is now the only place the property is set, so it reports the handle to
`RecordWindowMark()`. Every read validates the recorded handles with
`IsWindow` + `GetPropW` and drops the ones that no longer qualify; the first read
seeds from one full walk, which is the one thing a maintained set cannot infer —
marks left behind by an earlier run of the program.

Measured back to back inside one process, so the window count and the shell load
are identical for both: **0.26 ms → 0.002 ms, 147×**.

The set cannot drift, and each way it could is closed:

| Way to be wrong | What stops it |
|---|---|
| a window is marked and never recorded | `Mark()` is the only writer and always records |
| a window is recorded twice | `RecordWindowMark` ignores a handle already present |
| a window is destroyed | read-time `IsWindow` |
| the property disappears (explorer restart) | read-time `GetPropW` |
| a handle is recycled into an unmarked window | the same `GetPropW` — properties do not transfer |
| a mistaken unmark under-counts for the rest of the process | `RecordWindowUnmark` refuses to drop a handle whose property is still set |
| marks predate this process | the seeding walk |

`tools/verify_marks.cpp` checks all seven against a live desktop, comparing the
set to a fresh walk in each state.

### 2. `UserAssist` is searched with a rotated needle

`UserAssist` stores one `Count` key per GUID whose value names are ROT13-encoded
paths. The 1.0.3 scan decoded every value name with `RoT13()` and then searched
the decoded string for `ExplorerF11.exe`.

ROT13 is a per-character bijection that commutes with case folding, so

```
ContainsI(RoT13(name), needle)  ==  ContainsI(name, RoT13(needle))
```

holds exactly — not as a heuristic but as an identity, because `towlower` and
ROT13 commute character by character. One rotation of the needle per scan
replaces a string construction and a per-character pass *per value*: **88 µs →
50 µs over the 309 names on this machine (−43%)**. The clean path
(`DeleteMatchingValues`) had the same waste and uses the same hoist.

`tools/bench_ua_match.cpp` proves the equivalence on the live registry and
prices four strategies on the same data:

| Strategy | µs per pass | Verdict |
|---|---|---|
| decode each name, then search (1.0.3) | 88.3 | — |
| **rotated needle, naive scan** | **50.2** | adopted |
| rotated needle, `StrStrIW` | 955.4 | 19× slower — measured, not assumed |
| rotated needle, first-char filter | 46.0 | 6–14% better than adopted, not worth the extra code |

`StrStrIW` is the "just use the system's search" answer and it is nineteen times
worse: it does full Unicode case folding per position. The first-character
filter is faster but only by ~4 µs on an 800 µs probe, and it is subtle code in
the one row that may not miss anything.

### 3. The tray surface is pushed only when it differs

`PushTraySurface()` compares the freshly built tip and icon with what the shell
was last told and returns before the IPC when they match. The comparison is
against **live state**, never against a cached belief: `BuildTrayTip()` still
reads the marked set every time, so if the count really moved, the strings differ
and the push happens. What disappears is the round trip for events that end in
the same two lines of text.

Correctness argument: the shell's copy is only ever written by us. Every path
that changes it goes through `AddTray()` (which records what it installed) or
`PushTraySurface()` (which records what it pushed). `RemoveTray()` clears the
record, so the next push cannot be skipped. If the push fails, the record is not
updated and the next event retries.

### 4. The tray menu asks presence, not contents

The label shows a count of categories, but the builder ran the full scan,
including every value name of every `UserAssist` GUID, to produce it.
`CurrentResidueCategories()` runs the **same probe functions** with a
`presenceOnly` flag: each scan stops at its first hit and no detail text is
built. Presence rules are not duplicated — a row that is present in the report
is present in the count, by construction.

### 5. An event burst rebuilds an open report once

`RefreshStatusIfOpen()` marks the report dirty and posts one `WM_APP_REFRESH`
instead of rebuilding inline. Ten windows opening in a row used to re-probe
eleven locations ten times to paint one final state. The rebuild runs in the
same message dispatch and still reads live state, so nothing is cached and
nothing is stale — only the intermediate renders are gone.

Synchronous rebuilds remain where immediacy is the point: opening the window,
switching language, and the clean button.

### 6. Copy reads the screen

"Copy all" re-ran the whole probe pass to produce bytes the read-only edit
control was already holding. It now copies that text. One scan per copy instead
of two.

### 7. One registry open for both switches

Startup and `--menu` read `Tabs` and `InitialSweep` with two opens of the same
key; `CfgReadSwitches()` opens it once. Worth ~10 µs — listed because it is the
same class of waste as the rest, not because it is measurable.

## Measured results

A/B in one process, 400 iterations × 5 rounds, medians of four consecutive runs.
The two builds differ only in the code under test, so the window count, the
shell load and the registry cache are the same for both.

| Path | 1.0.3 | now | Change |
|---|---|---|---|
| mark lookup (the hover and event path) | 0.253–0.259 ms | **0.0017–0.0021 ms** | 147× |
| `BuildResidueReport` (full) | 1.521 ms | **1.032 ms** | −32% |
| `CollectResidues` (11 probes) | 1.529 ms | **1.041 ms** | −32% |
| tray menu open (presence scan) | 1.113 ms | **1.002 ms** | −10% |
| `UserAssist` match step | 88.3 µs | **50.2 µs** | −43% |
| tray hover (`NIN_POPUPOPEN`), tip unchanged | walk + 1 IPC | **~2 µs, no IPC** | — |
| state change that does not alter the tray | 1.2–1.7 ms | **0** IPC | — |
| state change that does alter it | 1.2–1.7 ms | 1.2–1.7 ms (unchanged, one call) | — |
| copy all | 1.1–1.3 ms of probing | **none** (the clipboard write is unchanged) | — |
| N events → open report | N × 1.5 ms | **1.0 ms** | — |

Structural claims (exact, not noisy): one `NIM_MODIFY` per state change and none
when the surface is unchanged; one probe pass per menu open and per report
rebuild; zero probe passes per copy; zero whole-desktop walks per read of the
marked set.

### Where the report time goes

Per-probe breakdown (`dist/bench_probes.exe`), median per call. These are the
raw registry walks, so they are the floor the report cannot go below:

| Probe | Cost | Share |
|---|---|---|
| `UserAssist` (every GUID × every value) | 0.42 ms | 50% |
| tray icon bookkeeping (every record, open each) | 0.24 ms | 29% |
| `MuiCache` value scan | 0.066 ms | 8% |
| log + exe `GetFileAttributesEx` | 0.043 ms | 5% |
| compatibility store scan | 0.028 ms | 3% |
| `Prefetch` glob | 0.026 ms | 3% |
| three single-value registry reads | 0.012 ms | 1% |
| **total** | **~0.83 ms** | |

What is left of a full build is that floor plus the window-mark lookup (~2 µs),
the eleven row structures and their prose (~0.13 ms of strings), and the CRLF
conversion.

## Memory

Speed has a wall that is not code: a full residue scan costs 1.9 ms on top of a
10.7 ms process start, so 85% of `--status` is Windows creating a process. Memory
has the same shape - most of it is not this program - but unlike speed it had one
thing left that could actually be removed, so it was worth measuring rather than
assuming.

### The ledger

Every number below is from `tools/measure_mem.cpp` reading a live process, all on
one machine at one sitting. `private` is committed private bytes, the number that
represents what the program actually owns; `ws` is the working set, which is what
Task Manager shows and is dominated by shared DLL pages.

Private bytes move by about 10 KB between runs - 1.76 and 1.77 MB are both this
build - so the documents quote the range. A document that pins one of them is
wrong half the time, and the release gate would then either fail on a machine
that sampled the other value or, worse, be ignored.

| State | private | ws |
|---|---|---|
| empty Win32 message loop, same flags | **1584 KB** | 7.8 MB |
| + tray icon (`Shell_NotifyIconW`) | 1764 KB | 8.9 MB |
| + one registry-and-window pass | 1776 KB | 9.0 MB |
| shipped tray process, before this release | 1912 KB | 11.3 MB |
| **shipped tray process, now** | **1812 KB** | **10.4 MB** |
| after opening the report window once | ~2390 KB | 17.3 MB |

The floor is the headline: **1584 of 1812 KB is what an empty program built with
these flags already commits.** That is the static CRT, the loader's private
copy-on-write pages, and the DLLs the process cannot exist without. The tray adds
~180 KB, a full registry pass adds ~8 KB, and this program's own data - the icon
handles, the window classes, the marked set, the i18n tables - is ~36 KB.

### What was removed

The two .ico files stored all nine sizes as PNG. `LoadImageW` decodes those
through WIC, and a single decode pulls `WindowsCodecs.dll` - 2.3 MB of code pages
- into a process whose visible bitmaps are 16x16. The sizes this program asks for
(16 through 48, every DPI a tray icon and a title bar use) are now uncompressed
DIB, where no decoder is involved; the large sizes stay PNG because Explorer
decodes those in its own process.

| | before | after |
|---|---|---|
| private | 1912 KB | **1812 KB** |
| working set | 11264 KB | **10384 KB** (−8%) |
| `WindowsCodecs` in module list | yes | **no** |
| disk | 370 KiB | 411 KiB (+41) |

The pixels are identical, and that is measured, not assumed: `icon_probe.exe`
loads the old and the new file, reads the bitmap back out of the HICON with
`GetDIBits`, and hashes it. Both icons, both states, same hash.

The disk cost is real and worth stating plainly: a DIB is bigger than the PNG it
replaces. 38 KiB of icon data buys 100 KB of commit and 880 KB of working set;
the other 3 KiB of the file is code: the maintained set, and the report's
button row measured from its labels instead of a fixed width.

### What cannot be removed, with the number that proves it

- **`msctf.dll`, 1.4 MB of working set.** Loaded because the program owns an
  ordinary top-level window; a message-only window would not load it, but it
  would also stop receiving the `WM_SETTINGCHANGE` / `WM_DISPLAYCHANGE` /
  `WM_THEMECHANGED` broadcasts that the DPI and theme handling depends on. A
  memory saving paid for with a behavioural regression is not a saving.
- **The report window's ~584 KB and 6 MB of working set.** Broken down by
  `tools/mem_floor.cpp` building the same window in pieces: 384 KB is the frame
  alone, 84 KB the EDIT control, 116 KB the three buttons, 8 KB the font. On
  Windows 11 a visible frame brings in the compositor's UI stack
  (`CoreUIComponents`, `WinTypes`, `comctl32`). It is paid once, on the first
  open, and no code in this program can avoid it short of not showing a window.
- **Building icons by hand instead of `LoadImageW`.** `CreateIconFromResourceEx`
  and `CreateIconIndirect` both avoid the decoder too, and both measured the same
  1280-1292 KB as a DIB `LoadImageW`. Parsing an .ico by hand to save the same
  zero bytes is not a trade worth the risk.
- **Trimming the working set when hidden.** Would trade resident pages for page
  faults on the next hover, which is the one interaction this program exists to
  make instant.

### Method

`measure_mem.exe <pid>` groups committed pages by type, module and protecting and
lists the largest private regions. `mem_floor.exe <level>` builds the same
executable with progressively more of what the program does - loop, tray, scan,
window - so each layer has a measured boundary. `verify_handles.exe` calls the
real collection, report and mark readers 300 times each and fails if the handle
count grows; it did not, which is what ruled a leak out before anything was
attributed to one. `icon_probe.exe` proves the icon change at the pixel level.

## Decision log

Optimisation is mostly deciding what not to do. Each entry carries the number
that settles it, or the semantic reason no number can settle.

### Reversed after measuring

These were rejected in an earlier pass and are now done. What changed was
evidence, not opinion.

| Was rejected because | Now done, because |
|---|---|
| "An incremental count drifts the moment a window is destroyed while explorer is busy, and every surface would then lie." | The drift objection is correct for a **counter** and irrelevant for a **validated set**. Recording handles and re-checking `IsWindow` + `GetPropW` on every read costs ~1.2 µs per marked window and is self-correcting; the walk it replaces was 260 µs. `tools/verify_marks.cpp` shows the two agree in all seven states. |
| "`RoT13` per value name is what the format requires." | It is not: the search commutes with the rotation, so the decode can move from 309 value names to one needle. 43% of the match step, provably the same answer. |

### Rejected, and the number that settles it

| Rejected | Why |
|---|---|
| `-flto` | **Not available.** This toolchain's `cc1plus` reports "LTO support has not been enabled in this configuration". Not a trade-off — an impossibility on the build that ships. |
| `-Wl,--gc-sections` + `-ffunction-sections` | Measured: 379,392 → 375,808 bytes (−3,584 B, −0.9%), zero runtime effect, and reproducible across two builds. Declined because it changes a published size fact for no behavioural gain, and because it is a linker-level change to a static CRT binary that deserves its own full verification pass rather than a ride along a performance change. |
| `-O2` instead of `-Os` | Measured: 451,584 bytes, +19% over `-Os` for a workload that is 99% registry and IPC latency. The size is a documented feature; the speed is not there to buy. |
| `StrStrIW` for the value-name search | Measured 955 µs per pass against 50 µs for the rotated needle — 19× worse. It is the obvious answer and it is wrong. |
| First-character filter (`wmemchr` + compare) | Measured 46 µs against 50 µs: real but ~4 µs, on a probe that is already 780 µs. Not worth the subtle pointer arithmetic in the row that must not miss anything. |
| A second, hand-written presence implementation | Not a speed question. Two implementations of "is this row there" is exactly how the menu and the report start disagreeing; the flag goes through the same functions instead. The cheaper option that keeps one definition was available, so the duplication was never necessary. |
| Binary search / hash for the translation table | Measured: 56 ns per lookup, ~27 µs per report build. Below the noise floor, and it would touch the generated i18n pipeline. |
| Worker thread for the probe pass | Would make a 1 ms action asynchronous, and add a thread, a queue and a shutdown order to a program that has one thread by design. The action is already below the threshold where a human notices. |
| Keep the log file open for the process lifetime | The reason first written down ("an open handle makes `--clean` fail") was **wrong**: `DeleteFile` succeeds when the handle was opened with `FILE_SHARE_DELETE`. The real reason is that logging is off by default (`--log` only), so the open/close pair costs the default configuration nothing, and the diagnostic mode is the one place where losing a line to a buffered handle would matter. |
| Drop `TranslateMessage` | Saves nanoseconds per message; the loop stops being the idiomatic one. |
| Drop the title check on activation | `HSHELL_WINDOWACTIVATED` fires for every activation, and `GetWindowTextW` is a cross-process send. But Control Panel shares `CabinetWClass` with folder windows, and the title is the only cheap signal that separates them — without it the tool would "accelerate" Control Panel. The send happens only after the class already matched, so it is one call per folder activation. |
| Narrow the `EVENT_OBJECT_CREATE` hook | `SetWinEventHook` cannot filter by object type or class; the callback has to see the event and reject it. `WINEVENT_SKIPOWNPROCESS` is set, and the reject path is one comparison plus, for window objects only, one `GetClassNameW`. |

### Rejected on semantics, not speed

| Rejected | Why |
|---|---|
| Cache the ten registry probes while the report is open | Only **1 of the 11 rows** depends on window state (row 11, the in-memory marks), so a window event genuinely cannot change the other ten — the current rebuild is 1.0 ms of work to refresh one row. It is still declined, because the invalidation set cannot be made complete: launching a second copy of the exe (which exits on the mutex) is recorded by Windows in `UserAssist`, and nothing in this process observes that. A report that can be silently stale is the one thing this program may not ship. The honest alternative — re-probe on open, on language change, on clean, and on every write we perform — would be a product decision about what the window promises, not a performance change. |
| Cache residue probes for the process lifetime | Same reason, without even the partial invalidation argument. A report that can be minutes stale is worse than a report that costs 1 ms, and the program's whole claim is that it tells the truth about what it left behind. |
| Direct `RegQueryValueExW` lookup in `UserAssist` by ROT13 path | Could prove presence for one path, but the report needs a count and a byte total across every match, and a miss would fall back to the scan anyway. An unverifiable fast path on a "nothing may be missed" surface is not worth it. The needle rotation above takes the same cost out without giving up the scan. |

## The release pipeline

`make release` is sixteen stages. It took 135 s; a local rehearsal of it now
takes 12 s. Three things were being paid for without buying anything: the same
gates ran twice, the suites slept, and the compiler worked on one file
at a time.

### The gates ran twice

`refresh-facts` has to run every gate — it derives the assertion count from
them. `gates` then ran `make test`: the same commands, on a tree that
had changed only in the two files the first run wrote. Two runs of one question
answer it once.

`refresh-facts` now records what it proved and the bytes it proved it on.
`tools/treefp.py` fingerprints every file a gate can read; the `gates` stage
recomputes the fingerprint and reuses the record when it matches. Any other
bytes invalidate it, including a regenerated screenshot, so the reuse is exact
rather than optimistic. **62 s → 0.01 s.**

### The suites slept

One pass was 62.5 s: **46 s of `time.sleep`** and **17 s of starting a shell**
to do what one API call does. Per suite, before and after:

| Suite | Before | After | What the time was |
|---|---|---|---|
| `test_registry_policy` | 19.77 s | 0.44 s | 7 × 1.1 s `Stop-Process`, 7 × 0.4 s wait, 5 × 0.5 s after a menu command |
| `test_language` | 12.48 s | 0.63 s | 15 sleeps, 1.3 s for a start-up, 0.8 s per language switch |
| `test_residue_report` | 10.43 s | 2.34 s | 13 sleeps from 0.1 s to 1.4 s |
| `test_icons` | 9.69 s | 0.12 s | 8 version queries, each a shell start |
| `test_smoke` | 7.17 s | 0.96 s | 5.6 s of sleeps, two `taskkill`, one resource query through a shell |
| four static gates | 1.16 s | 0.82 s | — |
| **`make test`** | **62.5 s** | **6.2 s** | |

Every sleep was a guess about how long something takes, and each was wrong in
both directions: 1.6 s for a start-up that takes 45 ms, 1.2 s for a repaint that
had already happened. `tools/win32util.py` replaces the guesses with
observations, and each one is a different fact:

| Instead of | Wait for | Cost |
|---|---|---|
| `taskkill /F /IM` + 0.5 s | `TerminateProcess` + the process handle reaching exit | 13 ms |
| `Start-Sleep 1.6` after launch | the window exists **and** `WaitForInputIdle` returns | 45 ms |
| 0.5-0.8 s after a menu command | the registry value that command writes | 5 ms |
| shell `Get-Item ... .VersionInfo` | `VerQueryValueW` on the loaded image | 1 ms |
| shell `Get-Process` | `GetProcessMemoryInfo` + `GetProcessHandleCount` | 1 ms |

`WaitForInputIdle` is not optional. The start-up sweep is *posted* from
`WM_CREATE`, so a window that merely exists is one message too early: a test that
reads the registry at that moment can read it before the sweep. The idle check
returns when the queue is empty, which is the first moment the start-up work is
finished.

One case genuinely needs the clock. The report's header stamps the time it was
built, at one-second resolution, so a rebuild inside the same second produces
byte-identical text and the test cannot see it. The suite now waits for the
second to tick *before* posting the command (at most 0.5 s, average 0.5) and
then polls; the 1.2 s it replaced was slower and only passed when the rebuild
happened to land in a different second.

A later pass over test quality moved the total back up: `make test` is 8.6 s,
because `test_smoke` now opens and closes real windows to observe three things
that used to be grepped out of `src/` (the start-up sweep and `--no-initial`, the
window count following a close, and the tray surviving a `TaskbarCreated`), and
`test_residue_report` plants a UserAssist entry to prove the ROT13 value names
are read. That is 2.4 s bought with assertions that fail when the behaviour is
wrong rather than when a line is formatted differently.

### The build compiled serially

The release build handed `src/*.cpp` and `src/app.rc` to a single `g++` command,
which compiles the four units one after another and then links. Measured, that
was 6.3 s of compilation and 0.12 s of linking — the link was never the expensive
part, and `make -j4` on the one-shot command changed nothing because the command
itself is one job.

Four object files give make four parallel jobs:

| | Before | After |
|---|---|---|
| `make -B` | 6.45 s | 2.6-3.1 s |
| `make`, one unit edited | 6.45 s | 2.05 s |

The bytes do not move. `g++ -c` per unit plus a separate link produces the digest
on the 1.0.4 release page (`477d3fb6…`), because nothing here depends on
cross-unit optimisation.

This document claimed the opposite until now — that splitting the units "would
change the binary" — and that claim is why the build stayed serial. It is
corrected here rather than deleted, because the numbers above were read from a
build that was held back by it.

### What is left, and why it stays

| Stage | Time | Why it cannot be cheaper |
|---|---|---|
| `build` | 2.6-3.1 s | Four parallel compiles and a 0.12 s link. A link is the floor: one pass over every object, no work to overlap. |
| `facts` | 4.8-6.5 s | Fourteen processes. The suites themselves are the floor, and they are serial on purpose: they share one registry key and one hidden window. |
| `preflight` | 1.2 s | Three network round trips - fetch, ls-remote, gh auth - issued at once. Serially they were 3.1 s; nothing else in the stage waits on the network. |
| `screenshots` | 1.9 s | Two app launches and four screen grabs. |
| `remote` | 2.2-2.4 s | Six `gh` queries, run at once; serially it was 8.0 s. |
| `gates` | 0.01 s | A fingerprint comparison, by construction. |
| **dry run to `notes`** | **11.7-12.5 s** | was 135 s, then 18.6 s before the build was split |

A real release adds `commit`, `push`, `ci`, `tag`, `package`, `publish` and
`verify`. `ci` is the only large one — 35-44 s — and it is a GitHub runner
building the same source with MSVC, which is a second toolchain asserting
something this machine cannot: that the code compiles under the compiler most
users would use. Nothing local can shorten it, so the pipeline prints it as its
own stage instead of hiding it inside a total.

Three rejected optimisations, with the number that settles them:

- **Run the gates in parallel** (would save ~4 s): they share one
  registry key, one hidden window and one autostart entry. Overlapping them
  would test the tests. The suite is 8.6 s; the risk is a flaky gate in the release
  path, which is the worst place to have one.
- **Run the static checks while the suites run** (would save under a second):
  every suite locates the application by window class, and a concurrent launch
  of the same binary is the one thing that can make that lookup answer with an
  instance the suite did not start. Under a second is not worth a race in the
  release path.
- **Cache the build against the tree fingerprint and the compiler version**
  (would save 3.1 s): the cache would be correct in the common case, and in the
  uncommon case it would ship a binary that no build on this machine produced.
  The release contract is "built from scratch", and 3.1 s is a cheap way to keep
  it.

The pipeline prints every stage's time and share at the end of a run and in
`dist/release-X.Y.Z.log`, so the next regression is a number in a log rather than
an impression.

## Invariants this design may not break

1. **No surface may show a cached snapshot.** Every rebuild re-probes. The two
   things that are remembered — what the shell was last *told*, and which handles
   carry our property — are not sources of truth about the system: the first is
   verified by recomputing the surface, the second by re-reading the property.
2. **One definition per surface.** The tip, the menu header and the report all
   call `AcceleratedText()` / `CollectResidues()`; the menu count uses the same
   probes with a cheaper depth.
3. **The default configuration writes nothing.** No optimisation may add a
   registry value, a file, or a cache on disk.
4. **A skipped call must be provably redundant.** Skipping an IPC is allowed
   only when the bytes it would send are identical to the bytes already sent.
5. **A remembered handle must be re-validated before it is counted.** The set is
   an index into the truth, never a substitute for it.

## Reproduce

```sh
make bench                 # builds dist/bench_hotpaths.exe
dist/bench_hotpaths.exe 400

g++ -std=c++23 -Os -I. tools/bench_probes.cpp src/residue.cpp src/config.cpp \
    src/i18n_extra.cpp -o dist/bench_probes.exe -static -static-libgcc \
    -static-libstdc++ -luser32 -lshell32 -ladvapi32
dist/bench_probes.exe 300

g++ -std=c++23 -Os -I. tools/bench_ua_match.cpp -o dist/bench_ua_match.exe \
    -static -static-libgcc -static-libstdc++ -ladvapi32 -lshlwapi
dist/bench_ua_match.exe 200

g++ -std=c++23 -Os -I. tools/verify_marks.cpp src/residue.cpp src/config.cpp \
    src/i18n_extra.cpp -o dist/verify_marks.exe -static -static-libgcc \
    -static-libstdc++ -luser32 -lshell32 -ladvapi32
dist/verify_marks.exe
```

Memory, against a running tray instance. Start it first, note its pid:

```
g++ -std=c++23 -Os -municode tools/measure_mem.cpp -o dist/measure_mem.exe \
    -static -static-libgcc -static-libstdc++ -lpsapi -luser32
dist/measure_mem.exe <pid>        # commit by type/module + largest private regions

g++ -std=c++23 -Os -municode -mwindows tools/mem_floor.cpp -o dist/mem_floor.exe \
    -static -static-libgcc -static-libstdc++ -s -luser32 -lshell32 -ladvapi32 \
    -lpsapi -lgdi32
dist/mem_floor.exe 0              # message loop only: the floor
dist/mem_floor.exe 1              # + tray icon
dist/mem_floor.exe 2              # + one registry and window pass
dist/mem_floor.exe 3              # + a report-shaped window (4 = stock font)

g++ -std=c++23 -Os -I. -Isrc tools/verify_handles.cpp src/residue.cpp \
    src/config.cpp src/i18n_extra.cpp -o dist/verify_handles.exe -static \
    -static-libgcc -static-libstdc++ -luser32 -lshell32 -ladvapi32 -lpsapi
dist/verify_handles.exe 300       # fails on any handle growth

g++ -std=c++23 -Os -municode tools/icon_probe.cpp -o dist/icon_probe.exe \
    -static -static-libgcc -static-libstdc++ -s -lgdi32 -luser32
dist/icon_probe.exe load src/ExplorerF11.ico hash
dist/icon_probe.exe resource src/ExplorerF11.ico hash
dist/icon_probe.exe indirect src/ExplorerF11.ico hash
```

Icons are generated from geometry by `make-icons.py`, which runs the DIB
conversion for the small sizes as part of writing them, so a regenerated icon
cannot regress to PNG-only by being regenerated:

```
python tools/make-icons.py        # writes both .ico files and the README PNG
```

`make_ico_bmp.py` is the conversion itself, usable on any PNG-compressed icon,
and it will not write a file whose decoded pixels differ from the input:

```
python tools/make_ico_bmp.py src/ExplorerF11.ico /tmp/out.ico
```

The benchmark tools warm up before timing, take the median of several
rounds, and print milliseconds per 1000 calls. None of them is a test gate: they
measure, they do not judge. `verify_marks.exe` and `verify_handles.exe` do judge —
they return non-zero on any mismatch or growth.

The guarantees they support are pinned by source contracts in
`tests/test_robustness.py`: one push function, one IPC, none when unchanged, one
coalesced refresh, copy without a rescan, menu count equal to report count,
`PROP_MARK` has exactly one writer which reports to the set, reads validate with
`IsWindow` + `GetPropW` and never re-enumerate the desktop, the `UserAssist`
scan keeps its needle rotation, and both icon files keep their 16-48 sizes as
uncompressed DIB while still carrying a 256 PNG for Explorer.
