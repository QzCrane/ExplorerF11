# Residue

Every location this program can affect, who writes it, what it holds, and how to
check it by hand. `ExplorerF11.exe --status` prints the same inventory with live
values, and exits `1` if any removable item is present.

The inventory describes possible state, not a claim about the current machine.
It has 11 rows in three groups; a first run with default settings creates none
of the rows in A or B. `--status` prints absent rows too, because a report that
only listed present items could not prove the rest is clean.

## A. Written by this program

| # | Item | Location | Written when | Typical size | `--clean` |
|---|---|---|---|---|---|
| 1 | Settings key | `HKCU\Software\ExplorerF11` | a setting leaves its default | 12 B per `DWORD`, ~28 B for `Language` | deleted |
| 2 | Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ExplorerF11` | *Start with Windows* is ticked | 150–200 B (path length) | deleted |
| 3 | Log file | `%TEMP%\ExplorerF11.log` | started with `--log` | ~200 B | deleted |
| 4 | Window marks | `ExplorerF11.Marked` and `ExplorerF11.Tick` properties on Explorer windows | each accelerated window, once per window regardless of tab count | 0 B (in memory) | disappears with Explorer |

The settings key holds at most `Tabs`, `InitialSweep` and `Language`. `--clean`
deletes the whole key, which also resets the UI language to the system default.
`Language` exists only while it differs from the system language; its accepted
tags are `zh`, `zh-Hant`, `en`, `ja`, `ko`.

Row 4 never touches disk. It is listed because the marks survive the tool's own
exit — a restarted instance can see which windows were already handled — and
because a user inspecting the process deserves to know the state exists. A mark
is removed when recovery decides the window was not actually accelerated, so a
later sweep can retry it.

## B. Recorded by Windows because the exe ran

ExplorerF11 does not write any of these. Windows creates them for any program
that starts, shows a tray icon or is launched from Explorer. They are included
because "I ran it once" is still a residue and most cleanup tools ignore them.

| # | Item | Location | Written when | Typical size | `--clean` |
|---|---|---|---|---|---|
| 5 | Startup on/off flag | `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run\ExplorerF11` | autostart exists and Task Manager touches it | 12 B | deleted |
| 6 | Tray icon cache | `HKCU\Control Panel\NotifyIconSettings\{GUID}` | the tray icon is shown | 1–3 KB | deleted |
| 7 | Compatibility Assistant | `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store` | first launch | ~90 B | deleted |
| 8 | Friendly name | `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache\<path>.FriendlyAppName` | first launch | ~120 B | deleted |
| 9 | Launch counter | `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist\{GUID}\Count` | first launch | ~90 B | deleted |
| 10 | Prefetch | `%WINDIR%\Prefetch\EXPLORERF11.EXE-*.pf` | first launch, if Prefetch is enabled | 10–30 KB | deleted when elevated |

Rows 6–10 come back the next time the exe runs. That is operating-system
behaviour, not a cleanup failure: removing them is a courtesy, not an uninstall.

Row 10 is administrator-only. Without elevation the report shows it as skipped
and `--clean` reports that it could not be removed — it cannot delete what it
cannot open. Prefetch is excluded from the size total below because Windows
manages it as a system cache.

## C. The program file

| # | Item | Location | Removed by |
|---|---|---|---|
| 11 | `ExplorerF11.exe` | wherever you put it | you, after `--clean` |

The executable is not residue; it is the program. Deleting it is the last step
of an uninstall and is deliberately left to the user.

## Size and growth

Everything removable, worst case: **under 6 KB**, excluding Prefetch. Nothing
grows with use — there is no history, no database, no cache of the tool's own,
and no log unless `--log` was passed. The two icon resources account for about
60 KB of the executable itself, not of its residue.

## Write policy

Four rules, enforced in `config.cpp`:

1. A value is written **only** while it differs from its default.
2. Setting it back to the default **deletes** the value.
3. Deleting the last value **deletes the key**.
4. The UI language follows the same rule with the system language as its
   default, so picking the machine's own language leaves no value at all.

A fresh run therefore creates nothing, and "reset everything" is byte-for-byte
identical to "never installed". Autostart follows the same shape: unticked means
no `Run` value at all, not a value pointing at nothing.

## Verifying by hand

Registry: `Win+R` → `regedit` → paste a path from the table into the **address
bar**, not the search box. "Not found" means clean. To sweep everything at once,
use `Ctrl+F`, search for `ExplorerF11`, then `F3`.

Files:

```powershell
Test-Path "$env:TEMP\ExplorerF11.log"
Get-ChildItem "$env:WINDIR\Prefetch\EXPLORERF11.EXE-*.pf" -ErrorAction SilentlyContinue
```

Automated:

```powershell
ExplorerF11.exe --status           # full report
ExplorerF11.exe --status --lang en
if ($LASTEXITCODE -eq 0) { "clean" } else { "residues present" }
```

`--status` is read-only. It works with or without a console and never blocks a
script with a dialog unless there is no output handle at all.

## Removing everything

```powershell
ExplorerF11.exe --clean     # removes groups A (1-3) and B; never the exe
Remove-Item .\ExplorerF11.exe
```

`--clean` stops a running instance first and prints a per-category account of
what it removed. A category missing from that account had nothing to remove.
The report window exposes the same operation through its *Clean residues…*
button — the only deleting control in the UI. It lists the categories, asks for
confirmation, then refreshes the report in place: the tool keeps running and
the page you were reading turns clean without being reopened.
