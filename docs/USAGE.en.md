# Usage

Everything a user needs. Technical details live in
[ARCHITECTURE.md](ARCHITECTURE.md); the residue inventory is in
[RESIDUE.md](RESIDUE.md). 中文: [USAGE.zh-CN.md](USAGE.zh-CN.md).

## What it does

Every time Explorer opens a folder window, this tool performs one fullscreen
round trip on that window. New tabs and windows restored from the taskbar get the
same treatment. Afterwards, navigating in that window is noticeably smoother.

Acceleration is counted per **window**, not per tab: F11 is handled by the window
frame, so one round trip covers every tab in that window at once. A tab has no
F11 state of its own and is never accelerated on its own.

It posts keyboard messages and nothing else: no injection, no system files
touched, no administrator rights, and no change to Explorer's UI (it coexists
with ExplorerPatcher and StartAllBack).

## What it does not do

- **It is not a fix.** Microsoft has not addressed this behaviour; this automates
  a manual trick.
- **It does not change your settings.** Folder options, view modes and sorting
  are untouched.
- **It does not host Explorer.** If Explorer crashes, the tool merely sees the
  restart and re-registers.
- **It does not talk to the network.** There is no networking code.

## Three ways to use it

**Try it.** Double-click the exe; a tray icon appears. Open a new folder window
and compare it with one that was already open. If you decide against keeping it,
open *Residue report* from the tray, use *Clean residues…*, then delete the exe.

**Keep it running.** Double-click and leave it. It idles in the tray and handles
new windows as they appear.

**Run at logon.** Tray → *Start with Windows*. That writes one value,
`HKCU\...\Run\ExplorerF11`, containing the quoted full path and no arguments.

The exe can live anywhere, but not in a folder that gets cleaned automatically.
If you move it after enabling autostart, tick the item again.

## Tray menu

Fixed five-part layout, top to bottom:

```
ExplorerF11 1.0.0  ·  3 windows accelerated (5 tabs)   <- grey, not clickable
────────────────────────────
Apply to all open windows
Apply to the active window
Pause acceleration
────────────────────────────
✓ Re-accelerate the window on new tabs
✓ Accelerate windows open at start-up
✓ Start with Windows
Language  ▸  简体中文 / 繁體中文 / English / 日本語 / 한국어
────────────────────────────
Residue report (2 items)…
────────────────────────────
Exit
```

| Item | What it does |
|---|---|
| Status line | Name, version and *running, waiting for a folder window / N windows accelerated (M tabs) / paused*. Answers "is it working" without a click, and identifies the build in a bug report |
| Apply to all open windows | Forces a redo, including windows already done. Useful after a theme or scaling change |
| Apply to the active window | Acts on the last folder window you used. Greys out when there is none, instead of doing nothing |
| Pause / Resume acceleration | Stops work temporarily, e.g. while opening a dozen windows. Not remembered |
| Re-accelerate the window on new tabs | On by default. Pressing `+` redoes the **containing window**, not just that tab. Turning it off avoids the whole-window flash |
| Accelerate windows open at start-up | On by default. Off means only windows created later are handled |
| Start with Windows | The tick reflects what will actually happen, even after a Task Manager disable |
| Language | Five-way radio submenu: **简体中文**, **繁體中文**, **English**, **日本語**, **한국어**. Applies immediately and is remembered |
| Residue report | Opens the inventory. The report is read-only; the only action that deletes is *Clean residues…* inside it, and it asks first |

The destructive action is deliberately inside the report window, one separator
above *Exit*, and marked with a trailing `…`: the user sees exactly what will be
removed before confirming.

### The unit is the window, not the tab

The number in the status line counts **windows** (`CabinetWClass`, one Explorer
window frame), not tabs. That is a property of the mechanism, not a naming
choice:

- `F11` is handled by the window frame. One round trip applies to the whole
  window: eight tabs in one window still read as "1 window", and all eight share
  that window's accelerated state.
- A tab is a child window (`ShellTabWindowClass`) with no F11 state of its own,
  so it cannot be accelerated separately. The tool does not pretend otherwise:
  *Re-accelerate the window on new tabs* redoes the **containing window**.
- Hence "1 window accelerated (2 tabs)": the figure before the bracket is the
  unit of the action; the bracket is how many tabs those windows currently hold.
  A window without tabs (an older Explorer) omits the bracket.

The residue report's fourth item, *Window marks*, prints the same sentence from
the same function, so the menu, the tooltip and the report cannot show two
different numbers.

Settings read as states, not verbs: a ticked box is the answer, and there is
nothing to translate in your head.

## The report window

*Residue report (N items)…* opens exactly what `--status` prints. It starts by
saying where the numbers come from:

```
ExplorerF11 1.0.0 - residue report
program: D:\Tools\ExplorerF11.exe
time:    2026-11-15 11:20:31 (local) - UI language: English
scope:   11 possible locations in 3 groups; every one is listed below with its
         result, present or absent.
================================================================

Verdict: 2 items to remove, 372 B in total.
      this program: 1 item (164 B); recorded by Windows: 1 item (208 B).
      Items marked "removable" are deleted by "Clean residues…" in this window; the exe is not.
```

Then three groups — written by this program, recorded by Windows, program file —
and per item four fields:

```
[2] Autostart entry - present - removable
      who:    this program, when "Start with Windows" is ticked in the tray menu
      where:  HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ExplorerF11
      what:   "D:\Tools\ExplorerF11.exe" (164 B)
      note:   one REG_SZ value: the quoted full path to the exe, with no
              arguments. Unticking deletes it
```

- **who** — who put it there, and when;
- **where** — the full path, with the `HKCU\` prefix, so it can be pasted straight
  into regedit's address bar;
- **what** — what it currently holds (the line is omitted when it does not exist);
- **note** — what it is, whether cleanup removes it, and whether it comes back.

Absent locations are listed too, marked *absent*: a report that only shows dirt
cannot prove that the rest is clean.

Three buttons: **Copy all / Clean residues… / Close**.

- **Clean residues…** is the only place in the program that deletes anything; the tray
  menu deliberately has no second copy. It asks first, listing each category it is
  about to remove. Answer *No* and nothing changes. On *Yes* the list refreshes in
  place and **the tool keeps running**, so you can check the result.
- **The report updates itself.** While the window is open, opening or closing
  folder windows, pausing or resuming acceleration, or switching language rebuilds
  the body immediately, keeping your scroll position. It never shows a count from
  two minutes ago.
- The title bar, taskbar and Alt+Tab carry the program's own icon. The tray glyph
  is a blue bolt while running and grey while paused, and the hover tooltip states
  the current state and window count.

## Command line

| Option | Effect | Writes |
|---|---|---|
| none | run in the tray | nothing by default |
| `--install` | run in the tray, tick "Start with Windows" | one Run value |
| `--uninstall` | remove the autostart entry only, nothing else | deletes one value |
| `--status` | print the full report; exit 0 = clean, 1 = removable residues | read-only |
| `--clean`, `--purge` | remove everything removable, then exit (stops a running instance first) | deletes |
| `--menu` | print the tray menu as text (tests and troubleshooting) | read-only |
| `--lang <tag>` | UI language for this run: `zh`, `zh-Hant`, `en`, `ja`, `ko` | read-only |
| `--log` | write `%TEMP%\ExplorerF11.log` | creates one file |
| `--no-initial` | skip windows that were already open (this run only) | read-only |
| `--quiet` | never show a dialog, for scripts | read-only |
| `--help`, `-h` | print help | read-only |
| `--version`, `-v` | print the version | read-only |

Scripting the verdict:

```powershell
ExplorerF11.exe --status --quiet
if ($LASTEXITCODE -eq 0) { "clean" } else { "residues present" }
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | the requested action succeeded; for `--status`, the machine is clean |
| 1 | `--status` found removable residues |
| 2 | usage error: an unknown option, `--lang` without a value, or a `--lang` value that names no supported language |

A usage error echoes the offending token and points at `--help`. Unknown options
are never ignored: `ExplorerF11.exe --cleen` must not start a tray instance that
looks like it did something.

## Language

Four sources, highest priority first:

1. `--lang <tag>` (this run only);
2. `EXPLORERF11_LANG=<tag>` (this run only; portable copies and scripts);
3. the choice made in tray → *Language* (stored, used on the next start);
4. the system language (regional format, then UI language).

Accepted tags are `zh`, `zh-Hant`, `en`, `ja` and `ko`; common regional aliases
such as `zh-tw`, `zh-cn`, `ja-jp` and `ko-kr` are normalised to the same five
languages. The first two sources are "do it this time" instructions, so they
override the stored choice; the stored choice overrides the system language,
which is what makes a tray click survive a restart.

**Storage follows the same rule as every setting.** `HKCU\Software\
ExplorerF11\Language` exists only while the chosen language differs from the
system language; picking the system language again deletes the value, and an
empty key is deleted too. A user who never opens that submenu writes nothing.

Regional format is consulted before the UI language because "English UI, Chinese
region" is common and those users expect Chinese. Language affects text only,
never behaviour.

## Settings

Three; the first two are on by default.

| Setting | Default | Stored in |
|---|---|---|
| Re-accelerate the window on new tabs | on | `HKCU\Software\ExplorerF11\Tabs` (exists only while off) |
| Accelerate windows open at start-up | on | same key, `InitialSweep` |
| UI language | follow the system | same key, `Language` (exists only while it differs) |

Defaults are never written: returning a setting to its default deletes the value,
and an empty key is deleted too. In the registry, "reset to defaults" and "never
installed" are the same state.

## Troubleshooting

**A window opened but nothing got faster.**
Check the status line for *paused*. Then use *Apply to all open windows* — that
separates "never triggered" from "triggered but no effect". If a forced redo does
nothing, this Windows build changed the behaviour; `--log` records an
`accelerated:` line per window, which tells you whether the messages were posted.

**A newly opened tab is not handled.**
Confirm *Re-accelerate the window on new tabs* is ticked. If it is, the window was
probably skipped at start-up (it existed before the tool, with the start-up sweep
disabled). Apply once manually.

**The window flashes when I press `+`.**
That is the cost of the fullscreen round trip. Turn *Re-accelerate the window on
new tabs* off if it bothers you; the window itself stays accelerated.

**Where do I change the language?**
Tray → *Language*. All five rows are written in their own script — 简体中文,
繁體中文, English, 日本語 and 한국어 — so the menu stays usable even after
switching to a language you do not read. The change is immediate; no restart.

**I switched the language but the menu did not change.**
Check whether you started it with `--lang`, or have `EXPLORERF11_LANG` set: both
are one-run instructions that outrank the tray choice. Clear them and the stored
choice takes effect.

**Does it conflict with ExplorerPatcher or StartAllBack?**
No. It posts messages and never touches the UI. The test machine runs
ExplorerPatcher.

**It stops working after an Explorer restart.**
It should not: the tool listens for `TaskbarCreated`, re-registers the shell hook
and rebuilds the tray icon, and relaunches itself with the original command line
if registration fails.

**Multiple monitors / high DPI.**
The fullscreen round trip happens on the monitor that owns the window; other
windows are not pushed around. The UI scales with the system DPI.

**How do I uninstall?**
Two steps: `ExplorerF11.exe --clean`, then delete the exe. `--clean` stops a
running instance, then removes settings (language included), autostart, log,
and the records Windows made for it (tray icon cache, startup flag, compatibility
store, MuiCache, UserAssist, and Prefetch when elevated).

**Why is Prefetch still there after `--clean`?**
`%WINDIR%\Prefetch` is administrator-only. Without elevation the entries cannot be
deleted, and the report does not pretend otherwise.

**Will it mess up my registry?**
It touches only the 11 locations listed in [RESIDUE.md](RESIDUE.md), and
nothing else. When in doubt, run `--status`: that is the tool's own account of
itself.
