# Usage

Everything a user needs. Technical details live in
[ARCHITECTURE.md](ARCHITECTURE.md); the footprint inventory is in
[FOOTPRINTS.md](FOOTPRINTS.md). 中文: [USAGE.zh-CN.md](USAGE.zh-CN.md).

## What it does

Every time Explorer opens a folder window, this tool performs one fullscreen
round trip on that window. New tabs and windows restored from the taskbar get the
same treatment. Afterwards, navigating in that window is noticeably smoother.

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
and compare it with one that was already open. Not convinced? Tray → *Clear all
traces and exit*, then delete the exe.

**Keep it running.** Double-click and leave it. It idles in the tray and handles
new windows as they appear.

**Run at logon.** Tray → *Run at logon*. That writes one value,
`HKCU\...\Run\ExplorerF11`, containing the quoted full path and no arguments.

The exe can live anywhere, but not in a folder that gets cleaned automatically.
If you move it after enabling autostart, tick the item again.

## Tray menu

Fixed five-part layout, top to bottom:

```
ExplorerF11  ·  accelerated 3 windows     <- grey, not clickable
────────────────────────────
Apply to all open windows
Apply to current window
Pause
────────────────────────────
✓ Accelerate new tabs
✓ Accelerate windows open at start-up
✓ Run at logon
────────────────────────────
Footprint report (2 items)…
Clear all traces and exit…
────────────────────────────
Exit
```

| Item | What it does |
|---|---|
| Status line | *running / accelerated N windows / paused*. Answers "is it working" without a click |
| Apply to all open windows | Forces a redo, including windows already done. Useful after a theme or scaling change |
| Apply to current window | Acts on the last folder window you used. Greys out when there is none, instead of doing nothing |
| Pause / Resume | Stops work temporarily, e.g. while opening a dozen windows. Not remembered |
| Accelerate new tabs | On by default. Turning it off avoids the brief flash on every `+` |
| Accelerate windows open at start-up | On by default. Off means only windows created later are handled |
| Run at logon | The tick reflects what will actually happen, even after a Task Manager disable |
| Footprint report | Opens the read-only inventory |
| Clear all traces and exit | Confirms, removes everything removable, exits |

*Clear* is deliberately not adjacent to *Exit*: one separator and a trailing `…`
in between. A misclick there costs a reinstall.

## The report window

*Footprint report (N items)…* opens exactly what `--status` prints, verdict first:

```
Verdict: this program wrote 2 item(s) (372 B); Windows recorded 4 item(s) (18.1 KB).
      "Clear everything" removes every removable item below; the exe stays.
```

Then four groups — written by this program, recorded by Windows, legacy leftovers,
program file — and per item: who wrote it, the full path, current contents, and a
one-line explanation. Paths carry the `HKCU\` prefix so they can be pasted straight
into regedit's address bar.

Three buttons: **Copy all / Clean up / Close**. Cleaning refreshes the list in
place and retitles the window to *cleaned* or *already clean*.

## Command line

| Option | Effect | Writes |
|---|---|---|
| none | run in the tray | nothing by default |
| `--install` | run in the tray, enable autostart | one Run value |
| `--uninstall` | remove the autostart entry only | deletes one value |
| `--status` | print the report; exit 0 = clean, 1 = traces | read-only |
| `--clean`, `--purge` | remove everything removable, then exit (stops a running instance first) | deletes |
| `--menu` | print the tray menu as text (tests) | read-only |
| `--lang zh\|en` | UI language for this run | read-only |
| `--log` | write `%TEMP%\ExplorerF11.log` | creates one file |
| `--no-initial` | skip windows that were already open (this run only) | read-only |
| `--quiet` | never show a dialog, for scripts | read-only |
| `--help`, `-h` | print help | read-only |
| `--version`, `-v` | print the version | read-only |

Scripting the verdict:

```powershell
ExplorerF11.exe --status --quiet
if ($LASTEXITCODE -eq 0) { "clean" } else { "traces present" }
```

## Language

Decided in this order:

1. `--lang zh` / `--lang en` (this run only);
2. `EXPLORERF11_LANG=zh` (portable installs, scripts);
3. Windows regional format, then UI language.

Regional format is consulted first because "English UI, Chinese region" is common
and those users expect Chinese. Language affects text only, never behaviour.

## Settings

Two, both on by default:

| Setting | Default | Stored in |
|---|---|---|
| Accelerate new tabs | on | `HKCU\Software\ExplorerF11\Tabs` (exists only while off) |
| Accelerate windows open at start-up | on | same key, `InitialSweep` |

Defaults are never written: returning a setting to its default deletes the value,
and an empty key is deleted too. In the registry, "reset to defaults" and "never
installed" are the same state.

## Troubleshooting

**A window opened but nothing got faster.**
Check the status line for *paused*. Then use *Apply to all open windows* — that
separates "never triggered" from "triggered but no effect". If a forced redo does
nothing, this Windows build changed the behaviour; `--log` records an
`accelerated:` line per window, which tells you whether the messages were posted.

**New tabs are not handled.**
Confirm *Accelerate new tabs* is ticked. If it is, the window was probably skipped
at start-up (it existed before the tool, with the start-up sweep disabled). Apply
once manually.

**The window flashes when I press `+`.**
That is the cost of the fullscreen round trip. Turn *Accelerate new tabs* off if it
bothers you; the window itself stays accelerated.

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
running instance, then removes settings, autostart, log, legacy leftovers, and the
records Windows made for it (tray icon cache, startup flag, compatibility store,
MuiCache, UserAssist, and Prefetch when elevated).

**Why is Prefetch still there after `--clean`?**
`%WINDIR%\Prefetch` is administrator-only. Without elevation the entries cannot be
deleted, and the report does not pretend otherwise.

**Will it mess up my registry?**
It touches only the 14 locations listed in [FOOTPRINTS.md](FOOTPRINTS.md), and
nothing else. When in doubt, run `--status`: that is the tool's own account of
itself.
