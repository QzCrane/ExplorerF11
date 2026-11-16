# Usage

How to run ExplorerF11 and read what it reports. Behaviour at the Win32 level is
in [ARCHITECTURE.md](ARCHITECTURE.md), and the full residue inventory is in
[RESIDUE.md](RESIDUE.md). 中文: [USAGE.zh-CN.md](USAGE.zh-CN.md).

## What it does

When Explorer opens a folder window, restores a minimised one, or you create a
tab, the tool sends that window one F11 round trip: into fullscreen, then back.
Explorer rebuilds its XAML chrome in the process, and navigating in the rebuilt
window is faster. It keeps doing this for windows opened later; it does not
touch windows that were already open unless you ask it to.

The count refers to **windows**, not tabs. `F11` is handled by the window frame,
so one round trip covers every tab in that window and all of them share its
accelerated state. A tab has no F11 state of its own and is never accelerated
separately. The bracket in `1 window accelerated (2 tabs)` is how many tabs
those windows currently hold; it is not a second count of work done.

Only `PostMessageW` crosses a process boundary. There is no injection, no real
keyboard input, no change to Explorer's UI, and no network code. It runs with
your token and works alongside ExplorerPatcher and StartAllBack. It is a
workaround for a manual trick, not a Microsoft fix, and it changes none of your
folder options or view settings.

## Running it

Double-click `ExplorerF11.exe`. A tray icon appears; open a folder window to see
the tooltip change from *running, waiting for a folder window* to a window count.
The exe can live anywhere, but not in a directory that gets cleaned
automatically, and autostart must be re-ticked if you move it afterwards.

Tray → *Start with Windows* writes one value,
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ExplorerF11`, holding the
quoted full path and no arguments. The tick reflects whether the entry will
actually start at logon: if you disabled it in Task Manager, ticking it here
also removes Windows' `StartupApproved` disable flag.

To stop, use tray → *Exit*. To remove the program completely, run
`ExplorerF11.exe --clean` and delete the file; see [Uninstall](#uninstall).

## Tray menu

Right-clicking the tray icon builds a fixed five-part menu from
`BuildTrayMenu()`:

```
ExplorerF11 1.0.3  ·  3 windows accelerated (5 tabs)   <- grey, not clickable
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

| Item | Behaviour |
|---|---|
| Status line | Version and one of *running, waiting for a folder window*, *N windows accelerated (M tabs)*, *paused*. Also tells you which build you are looking at in a bug report. |
| Apply to all open windows | Forces a round trip on every folder window, including already marked ones. Useful after a theme or DPI change. |
| Apply to the active window | Acts on the last folder window you used; greyed out when none exists. |
| Pause acceleration | Temporary stop, for example while opening many windows. Not persisted — a restart is running again. |
| Re-accelerate the window on new tabs | On by default. Pressing `+` redoes the **containing window**, not the tab. Turn off to avoid the whole-window flicker. |
| Accelerate windows open at start-up | On by default. Turning it off limits acceleration to windows created after launch. |
| Start with Windows | See [Running it](#running-it). |
| Language | Five-way radio submenu; applies immediately and is remembered. |
| Residue report | Opens the read-only inventory. Deletion lives only in the *Clean residues…* button inside that window. |

The destructive action is placed inside the report, not in the tray menu, so it
is always preceded by the list of what it will remove. It carries a trailing
`…` and asks for confirmation.

## Residue report

*Residue report (N items)…* opens the same text that `--status` prints. The
header states where the data comes from:

```
ExplorerF11 1.0.3 - residue report
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
with four fields per item:

```
[2] Autostart entry - present - removable
      who:    this program, when "Start with Windows" is ticked in the tray menu
      where:  HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ExplorerF11
      what:   "D:\Tools\ExplorerF11.exe" (164 B)
      note:   one REG_SZ value: the quoted full path to the exe, with no
              arguments. Unticking deletes it
```

- **who** — the writer and the condition that triggered it;
- **where** — the full path including `HKCU\`, pasteable into regedit's address bar;
- **what** — the current value; the line is omitted when the item does not exist;
- **note** — what the item is, whether cleanup removes it and whether Windows
  recreates it.

Absent locations are printed too, marked *absent*. A report that only showed
present items could not prove the rest is clean.

Three buttons: **Copy all / Clean residues… / Close**.

- *Clean residues…* is the only deleting operation in the program. It lists the
  categories it is about to remove and asks first; *No* changes nothing. On
  *Yes* the report refreshes in place and the tool keeps running, so you can
  verify the result without reopening it.
- The report rebuilds while it is open. Opening or closing folder windows,
  pause/resume, setting changes and language switches all update the body while
  keeping your scroll position.
- The title bar, taskbar and Alt+Tab use the program's own icon. The tray glyph
  is a blue bolt while running, grey while paused; hovering shows the state and
  the window count.

## Command line

| Option | Effect | Writes |
|---|---|---|
| none | run in the tray | nothing by default |
| `--install` | run in the tray, tick "Start with Windows" | one Run value |
| `--uninstall` | remove the autostart entry only | deletes one value |
| `--status` | print the full report; exit 0 = clean, 1 = removable residues | read-only |
| `--clean`, `--purge` | stop a running instance, remove everything removable, then exit | deletes |
| `--menu` | print the tray menu as text (tests and troubleshooting) | read-only |
| `--lang <tag>` | UI language for this run: `zh`, `zh-Hant`, `en`, `ja`, `ko` | read-only |
| `--log` | write `%TEMP%\ExplorerF11.log` | creates one file |
| `--no-initial` | skip windows that were already open (this run only) | read-only |
| `--quiet` | suppress message boxes, for scripts | read-only |
| `--help`, `-h`, `/?` | print help | read-only |
| `--version`, `-v` | print the version | read-only |

`--lang=<tag>` is accepted as well as `--lang <tag>`.

```powershell
ExplorerF11.exe --status --quiet
if ($LASTEXITCODE -eq 0) { "clean" } else { "residues present" }
```

| Exit code | Meaning |
|---|---|
| 0 | requested action succeeded; for `--status`, the machine is clean |
| 1 | `--status` found removable residues |
| 2 | usage error: unknown option, `--lang` without a value, or an unsupported language tag |

A usage error echoes the offending token and points at `--help`. Unknown
options are never ignored: `--cleen` must not start a tray instance that appears
to have done something. A bare `--lang` gets a dedicated "requires a language
tag" message, and `--lang --quiet` reports a missing value rather than treating
`--quiet` as a locale.

## Language

Four sources, highest priority first:

1. `--lang <tag>` (this run only);
2. `EXPLORERF11_LANG=<tag>` (this run only; portable copies and scripts);
3. the choice made in tray → *Language*, stored for later runs;
4. the system language — regional format first, then UI language.

Accepted tags are `zh`, `zh-Hant`, `en`, `ja` and `ko`; regional aliases such as
`zh-tw`, `zh-cn`, `ja-jp` and `ko-kr` map to the same five. The first two sources
are one-run instructions and override the stored choice; the stored choice
overrides the system language, which is how a tray click survives a restart.

`HKCU\Software\ExplorerF11\Language` exists only while the chosen language
differs from the system language. Selecting the system language again deletes
the value, and an empty key is deleted too. A user who never opens the submenu
writes nothing. Language affects text only, never behaviour.

## Settings

Three settings; the first two are on by default.

| Setting | Default | Stored in |
|---|---|---|
| Re-accelerate the window on new tabs | on | `HKCU\Software\ExplorerF11\Tabs` (exists only while off) |
| Accelerate windows open at start-up | on | same key, `InitialSweep` |
| UI language | follow the system | same key, `Language` (exists only while it differs) |

Returning a setting to its default deletes the value, and an empty key is
deleted as well. In the registry, "reset to defaults" and "never installed" are
the same state.

## Troubleshooting

**A window opened but nothing got faster.**
Look at the status line first: *paused* explains itself. Then use *Apply to all
open windows* — that separates "the hook never fired" from "it fired and had no
effect". If a forced redo also does nothing, this Windows build has changed the
behaviour. Start with `--log` and look for `accelerated:` lines: they record
whether the messages were actually posted.

**A newly opened tab was not handled.**
Check that *Re-accelerate the window on new tabs* is ticked. If it is, the window
was probably skipped at start-up — it existed before the tool, while the start-up
sweep was disabled. Apply once manually.

**The window flickers when I press `+`.**
That is the fullscreen round trip becoming visible. Turning off *Re-accelerate
the window on new tabs* removes the flicker; the window itself stays accelerated,
but new tabs no longer trigger a redo.

**Where do I change the language?**
Tray → *Language*. All five rows are written in their own script — 简体中文,
繁體中文, English, 日本語, 한국어 — so the menu remains usable after a switch to
a language you cannot read. The change is immediate; no restart.

**I switched the language but the menu did not change.**
Check for `--lang` on the command line or an `EXPLORERF11_LANG` variable. Both
are one-run instructions that outrank the tray choice. Remove them and the
stored choice takes effect.

**Does it conflict with ExplorerPatcher or StartAllBack?**
No. It posts messages and does not touch Explorer's UI. The test machine runs
ExplorerPatcher.

**It stops working after an Explorer restart.**
It listens for `TaskbarCreated`, re-registers the shell hook and rebuilds the
tray icon. If re-registration fails it relaunches itself with the original
command line. An icon that survives an Explorer restart but no longer responds
would indicate a failure in that path — please report it with the log.

**Multiple monitors / high DPI.**
The round trip happens on the monitor owning the target window; other windows
are not moved. The UI follows system DPI scaling.

## Uninstall

```powershell
ExplorerF11.exe --clean     # stops a running instance, removes groups A and B
Remove-Item .\ExplorerF11.exe
```

`--clean` removes settings (language included), autostart, the log and the
records Windows made for the exe: tray icon cache, startup flag, compatibility
store, MuiCache, UserAssist and Prefetch where elevation permits. It prints a
per-category account of what it removed. If a category is missing from that
account, nothing of that kind was present.

`%WINDIR%\Prefetch` is administrator-only. Without elevation those entries
remain and the report says so. The remaining locations are the ones in
[RESIDUE.md](RESIDUE.md); `--status` is the tool's own account of itself.
