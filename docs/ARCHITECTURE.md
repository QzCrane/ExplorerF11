# Architecture

This document describes what the shipped binary does. It is written against
version 1.0.3 and the source tree at that tag; where a claim depends on a Win32
detail, the detail is named so the claim can be checked. For user-facing
behaviour see [USAGE.en.md](USAGE.en.md); for the evidence behind the F11 trick
see [RESEARCH.md](RESEARCH.md).

## Constraints

The design is shaped by four constraints, in priority order:

1. **No polling and no injection.** Detection comes from shell and WinEvent
   hooks; the only cross-process write is `PostMessageW` into an Explorer
   window's own queue. This rules out `SendInput`, `SetWindowsHookEx` with a DLL,
   and memory patching — all of which need focus, elevation or a privilege
   boundary the tool must not cross.
2. **No residue that cannot be enumerated and removed.** Any state the tool
   creates must appear in `residue.cpp` and be reachable from `--clean`.
   Preferences are stored as deviations from defaults, so a default run leaves
   the registry untouched.
3. **One binary, no payload beyond the file.** Five UI languages are compiled in;
   there are no satellite DLLs, no runtime install and no service.
4. **Survive Explorer restarts without a second instance.** The shell hook
   registration and the tray icon both die with Explorer. Recovery must restore
   them without leaving an orphan icon or two resident copies.

If Microsoft ships native behaviour that makes the workaround unnecessary, the
correct action is to retire the tool rather than to keep maintaining it.

## Module boundaries

```
src/
  app.h           names written into the system (registry paths, class names, mutex)
  i18n.h          Lang enum, T(zh, en), LangName(), language resolution
  config.h/.cpp   settings and autostart, HKCU only
  residue.h/.cpp  enumerate, report and remove residual state
  main.cpp        hidden window, tray, hooks, menus, report window, CLI
```

Dependencies are one-way: `main` → `residue` → `config` → `app`/`i18n`. Neither
`config.cpp` nor `residue.cpp` creates a window or shows a dialog. That is what
lets their behaviour be exercised from a console and through `--status` without
a UI harness.

## Event model

Five entry points. There is no timer in the steady state and no enumeration
loop.

| Trigger | API | Why this mechanism |
|---|---|---|
| Folder window created | `RegisterShellHookWindow` → `HSHELL_WINDOWCREATED` | arrives at creation, desktop-wide, no polling cost |
| Tab created in an existing window | `SetWinEventHook(EVENT_OBJECT_CREATE)`, filtered to `ShellTabWindowClass` | a tab is a child window and fires no shell hook |
| Window restored from minimised | `SetWinEventHook(EVENT_SYSTEM_MINIMIZEEND)` | restored windows come back with rebuilt chrome |
| Tool started | `WM_APP_INITIAL`, posted after the message loop starts | covers windows that already existed |
| Explorer restarted | `TaskbarCreated` broadcast | both the shell hook and the tray icon are gone |

`HSHELL_WINDOWCREATED` has no per-class subscription, so every top-level window
arrives and is filtered with `GetClassNameW`. That is one string comparison per
window creation on the desktop — cheaper than `EVENT_OBJECT_SHOW`, which fires
much more often and still needs the same filter. `EVENT_OBJECT_CREATE` is the
one hook with a measurable per-event cost; it is also the only notification that
arrives before a new tab paints.

## Window marks and the de-duplication gate

Two window properties, `ExplorerF11.Marked` (presence) and `ExplorerF11.Tick`
(a `GetTickCount64()` sample), put the mark on the window itself rather than in
an `HWND` set kept by the tool. Three properties follow from that:

- The mark survives the tool's exit, so a restarted instance will not
  re-accelerate a window that was already handled.
- The mark disappears with the window, so there is no bookkeeping to leak and no
  confusion when Windows recycles an `HWND`.
- The mark is readable across processes without injection.

The stored tick is also used as a 1.2 s gate. A newly
created window creates its first tab immediately; without the gate the tab hook
would fire a second F11 cycle into a window whose first cycle was still
animating.

`MarkedWindows()` in `residue.cpp` is the only place that produces counts. It
walks top-level windows once, counts marked frames and their direct
`ShellTabWindowClass` children, and formats the sentence used by the tooltip,
the tray menu header and the report. Three surfaces call one function, so they
cannot disagree. The counted unit is the window because `PostF11Raw` targets the
frame: all tabs in it enter and leave fullscreen together.

## F11 delivery and recovery

Two press/release pairs are posted back to back with `PostMessageW`, and each
return value is checked. The first pair enters fullscreen, the second leaves it;
the rebuilt chrome is what remains. `SendInput` was rejected because it targets
the foreground window and would steal focus from whatever the user was doing.

A partial delivery — one pair landed, the other did not — leaves a window stuck
in fullscreen. Recovery is deliberately one-directional: it can only **exit**
fullscreen, so the worst outcome is "nothing happened", never "stuck".

The 1.0.0 implementation used a single `g_risk` slot and one 500 ms timer. Two
failures inside the same window overwrote each other, and the recovery trusted
`IsWindow()` alone, so an `HWND` recycled onto an unrelated window could be sent
F11 and have its marks removed. The current implementation keeps
`std::vector<RiskEntry> g_risks`, where each entry is `{HWND, tick}`:

- The partial-post branch in `Accelerate()` appends `{h, MarkedAt(h)}` to the
  vector — one entry per at-risk window — and re-arms the timer. A duplicate
  `(hwnd, tick)` pair is not added twice.
- `WM_TIMER` swaps the vector into a local batch before processing it. A risk
  recorded during the loop arms a fresh timer with a fresh batch, so no entry is
  lost to a re-entrant post.
- Each entry is accepted only if `IsWindow(r)` **and** `IsMarked(r)` **and**
  `MarkedAt(r) == e.tick`. A recycled handle, or a window re-accelerated in the
  meantime, fails the token check and is left untouched.
- An accepted entry is checked with `LooksFullscreen(r)`; only then is a single
  F11 pair posted to exit. Its mark is removed either way, because a partial
  delivery means the window was not accelerated. Dropping the mark lets a later
  start-up sweep, restore or *Apply to all* retry it; keeping it would hide the
  window forever.

## Explorer restart

`explorer.exe` restarting destroys both the shell hook registration and the
tray icon. A hidden **top-level** window is required to receive `TaskbarCreated`;
an `HWND_MESSAGE` message-only window does not, which is why an earlier revision
went silent after every Explorer crash.

On `TaskbarCreated` the tool deregisters (a second `RegisterShellHookWindow` in
the same process fails), re-registers, and only then rebuilds the tray:

- registration successful → `RemoveTray(h)` + `AddTray(h)`;
- registration failed → log the Win32 error, call `RelaunchSelf()`, and return
  immediately.

`RelaunchSelf()` calls `DestroyWindow` synchronously, which dispatches
`WM_DESTROY` (tray removed, hooks unhooked, quit posted) before returning. The
`h` in the handler is dead on return. The 1.0.0 code rebuilt the tray with that
dead handle, producing an icon that could not be clicked or removed. The failure
branch now returns without touching `h`; the new instance rebuilds the tray in
its own `WM_CREATE`. The command line is preserved through `GetCommandLineW()`,
and the mutex is released before spawning, so no second copy can start.

## Tray icon and tooltip

Both icons are nine-frame multi-size resources (16 through 256 px), regenerated
from geometry by `tools/make-icons.py`. The same script writes
`docs/images/app-icon.png` from the running master: GitHub does not render `.ico`
inline in a README, so the documentation needs a PNG frame rather than a
hand-placed image that can drift from the shipped icon. The tray loads `SM_CXSMICON`, the report
window `SM_CXICON` and `SM_CXSMICON`, so Windows selects a real frame at each
scaling level instead of stretching one. Without the resource all four surfaces
showed the generic document icon.

Icon ownership matters at teardown. `LoadAppIcon()` falls back to
`LoadIconW(NULL, IDI_APPLICATION)` when the resource is missing; that handle is
owned by the system, but `WM_DESTROY` destroys every icon in `g_icon*`
unconditionally. The fallback now takes a private copy via `DuplicateIcon`, so
the system cache survives the tool's exit; if that call fails, the shared icon
is kept rather than leaving an empty tray slot.

The tooltip is the only surface visible without opening anything, and the shell
caches its text at `NIM_ADD`. Two mechanisms keep it current:

1. Every state change — window created or destroyed, restore, new tab, recovery
   timer, pause, apply, apply-all, start-up sweep — funnels through
   `OnStateChanged()`, which refreshes the tooltip, the tray image and any open
   report in one call. It issues **one** `NIM_MODIFY` carrying `NIF_ICON |
   NIF_TIP | NIF_SHOWTIP` instead of two separate calls: a `NIM_MODIFY` is a
   cross-process round trip to explorer (~1.2 ms measured), so halving it was
   the single largest cross-behaviour saving in the program. `UpdateTrayTip()`
   remains only for `NIN_POPUPOPEN` and language changes, where the icon must
   stay untouched.
2. `NIM_SETVERSION` sets `NOTIFYICON_VERSION_4`, which delivers `NIN_POPUPOPEN`
   just before the shell draws the tooltip; the handler rebuilds the text there.
   Under version 4 the shell suppresses the standard tooltip unless `NIF_SHOWTIP`
   is set, and `NIM_MODIFY` **replaces** the flag set rather than merging it — so
   every modify that carries `NIF_TIP` re-asserts `NIF_SHOWTIP`. Omitting it made
   the tooltip disappear entirely.

The glyph is a blue bolt while running and grey while paused.

## Configuration and residue

`HKCU\Software\ExplorerF11` holds **only deviations from defaults**. Writing a
value equal to its default deletes it, and deleting the last value deletes the
key. A fresh run creates nothing, and "reset to defaults" is indistinguishable
from "never installed". The key can hold `Tabs` and `InitialSweep` (`REG_DWORD`)
plus `Language` (`REG_SZ`, one of `zh`, `zh-Hant`, `en`, `ja`, `ko`).

Autostart is one `REG_SZ` under the per-user `Run` key: a quoted path, no
arguments. Because preferences live in the registry rather than on the command
line, autostart and a manual double-click behave identically, and so does the
self-relaunch after a failed Explorer recovery. `StartupApproved\Run\ExplorerF11`
is Windows' own enable/disable flag; the tool treats "Run value present **and**
not disabled" as enabled and deletes the flag when enabling, so the menu tick
matches what will actually happen at logon.

The full inventory of 11 locations — including the ones Windows writes on the
tool's behalf — is in [RESIDUE.md](RESIDUE.md).

## Language pipeline

`i18n.h` keeps one enum and one function:

```cpp
const wchar_t *T(const wchar_t *zh, const wchar_t *en);
```

Simplified Chinese and English are written at the call site, so the default and
the fallback need no lookup. Traditional Chinese, Japanese and Korean live in
`tools/translations.json`, keyed by the exact Simplified Chinese source string;
`tools/gen_i18n.py` emits `src/i18n_extra.cpp`. Source-text keys, rather than
numeric ids, mean inserting a `T()` call mid-file cannot shift translations out
of alignment.

`tools/check_i18n.py` is a build gate: it extracts every `T()` call, requires
all five languages to be present and non-empty, checks `%d` and environment
placeholders, and fails if the generated table is stale. `tools/audit_i18n.py`
covers what a coverage gate cannot see — a value in the wrong script, ASCII
punctuation glued to CJK, mixed bracket styles and terminology drift.

`LangName()` is the single source for language names. Menu rows and the report
header use the same endonym, and the name is a constant rather than a translated
string: a selection control must stay readable after a mis-click, and a state
description must agree with the control that produced it.

| Source | Scope | Implemented by |
|---|---|---|
| `--lang <tag>` | this run | argument parser sets `g_langExplicit` |
| `EXPLORERF11_LANG` | this run | `EnvLang()` |
| `Language` value | persistent | `LoadLanguage()` |
| system language | default | `LocaleLang()` |

The locale check consults regional format before UI language, because an English
UI on a Chinese region is common and those users expect Chinese. Switching while
running needs no re-layout: the menu is rebuilt on every right-click, the
tooltip is a `NIF_TIP` on `NIM_MODIFY`, and `RelocalizeStatus()` rewrites the
report window's title, buttons and body.

Per-language punctuation is part of the contract: zh-Hant and ja use full-width
`，。：；（）`; ko uses ASCII `, . : ( )`. Report labels are padded to a common
column within a language, never across languages, and `check_help_align.py`
applies the same rule to the `--help` option column.

## Console output and argument parsing

`Emit()` writes wide characters with `WriteConsoleW` to a console and UTF-8 with
`WriteFile` to a pipe or redirected file. `ConsoleOut()` resolves the handle in
three steps: `GetStdHandle`, `AttachConsole(ATTACH_PARENT_PROCESS)` then
`GetStdHandle`, finally `CreateFileW(L"CONOUT$")`. It returns an `owned` flag;
only a handle created on the third path is closed by `Emit()`. The 1.0.0 code
leaked that handle on every invocation that reached the fallback.

The argument parser records the first token it cannot place and reports it
after localisation, with exit code 2. Unknown options are never treated as "no
options": `ExplorerF11.exe --cleen` must not start a tray instance that looks as
though it did something. `--lang` is a value-taking option with two special
cases, both fixed in 1.0.1:

- a bare trailing `--lang` produces a dedicated "requires a language tag"
  message in all five languages instead of "unknown option";
- a following token beginning with `-` is not consumed as a value, so
  `--lang --quiet` reports a missing value and still parses `--quiet`.

## Resource profile

Measured with `test_smoke.py` on build 26300.9974, one folder window open,
shortly after start-up:

| | Measured | Notes |
|---|---|---|
| Private bytes | under 2 MB | no CRT heap growth after start-up |
| Handles | 135 | window, hooks, tray icon, mutex and thread pool |
| Threads | 4 transient, 1 settled | three `TpWorkerFactory` helpers exit after roughly 45 s idle |
| CPU | 0.03 s cumulative / 2 min | start-up cost; steady state is blocked in `GetMessageW` |
| Disk | 370 KiB | static CRT, `-Os`, stripped; 60 KB is the two icon resources |

The binary imports `KERNEL32`, `USER32`, `GDI32`, `SHELL32`, `ADVAPI32` and
`msvcrt` — no networking library, no scripting host, no dynamic code loading.

## Tests

The suite drives the built binary through its public surface (`--menu`,
`--status`, `WM_COMMAND` to the hidden window) rather than linking against
internals. `--menu` prints the menu that `BuildTrayMenu()` actually built,
including submenus as indented rows, so the layout test cannot drift from the UI.
Every suite restores the state it changed, including autostart and the stored
language; the clean test only ever answers *No* to the confirmation.

Thirteen gates, 329 assertions, each returning non-zero on failure:

| Gate | Proves |
|---|---|
| `tools/check_i18n.py` | every `T()` key translated in five languages, placeholders intact, generated table current |
| `tools/audit_i18n.py` | no wrong-script characters, no ASCII punctuation in CJK prose, no contradicting term |
| `tools/check_help_align.py` | the `--help` option column starts at one offset in every language |
| `test_lang_names.py` | one name per language, identical in all five UI languages, matching the report header |
| `test_menu_order.py` | exact rows, groups, ticks, five-way language radio group |
| `test_residue_report.py` | report truth, five languages, live refresh, single confirmed clean entry |
| `test_registry_policy.py` | zero writes by default, defaults delete themselves |
| `test_language.py` | resolution order, persistence, zero-write rule |
| `test_icons.py` | icons and version block in the exe, tooltip refresh contract |
| `test_tray_cleanup.py` | cleanup is surgical, other programs' entries survive |
| `test_smoke.py` | real window accelerated, resource ceilings, clean exit |
| `test_robustness.py` | source contracts for the event-driven fixes, behavioural CLI checks |

The first three are static checks; the other nine need the built exe, and
`test_smoke.py` additionally needs a desktop session. Event-driven paths cannot
be reproduced deterministically on a CI runner, so `test_robustness.py` pins
their source contracts — recovery entries, tick validation, handle ownership,
icon ownership and argument boundaries — rather than pretending to drive real
shell events. This is a deliberate limit of the verification story.

## Performance measurement

Performance claims are reproducible, not adjectives. `make bench` builds
`tools/bench_hotpaths.cpp` into a diagnostic executable (deliberately **not** a
gate — it has no pass/fail threshold). It times each hot path over several
warmed-up rounds with `QueryPerformanceCounter` and reports the median ms per
1000 calls, so one Explorer hiccup cannot move a published figure.

Measured on this machine (build 26300.9974, one folder window open; medians of
two 400-iteration runs):

| Path | ms / 1000 | Where it is used |
|---|---|---|
| `CollectResidues` (11 probes) | ~1500 | menu open, report refresh, `--status` |
| — Win32 registry/file probes only | ~960 | the irreducible part of the above |
| — string + struct construction | ~130 | rows that `CurrentTotals` discards |
| `MarkedWindows` (`EnumWindows`) | ~235 | tooltip, menu header, report |
| top-level window filter | ~130 | window create / activate |
| one `NIM_MODIFY` IPC | ~1200 | each state change (now one, was two) |

Three conclusions shaped 1.0.3. The tab-count fix targeted `MarkedWindows`
(~0.23 ms), the cheapest of these; it was shared by three surfaces, which is
why the tooltip A/B moved all of them. The dominant per-event cost was the pair
of `NIM_MODIFY` calls, now merged. The residue probes remain un-cached on
purpose: caching could cut a report refresh fourfold, but a snapshot shown two
minutes late is worse than none, and a 1.5 ms scan on a user-initiated menu
open is not worth a staleness bug.

## Known limits

- Acceleration depends on undocumented shell behaviour. A Windows build may
  change it; the tool then quietly does nothing rather than breaking anything.
- Windows opened before start-up need the start-up sweep. With that option off,
  those windows stay unaccelerated until *Apply to all open windows*.
- `EVENT_OBJECT_CREATE` fires for every object on the desktop; the handler
  filters on class name and process id, but this is the one hook with a
  measurable, if small, per-event cost.
- Prefetch entries can only be removed with elevation. `--clean` reports the
  entries it could not delete instead of claiming success.
- The event-driven fixes were verified by source contracts and live smoke
  testing, not by an automated A/B on a Windows CI runner.
