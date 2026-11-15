# Footprints

Everything this tool can leave on a machine, where it lives, who writes it, and
how to remove it. `ExplorerF11.exe --status` prints the same list with live values.

Four groups, fourteen items. **Nothing in the first three groups exists after a
fresh run with the default configuration** — the list is what *can* appear, not
what does.

## A. Written by this program

| # | Item | Location | Written when | Typical size | `--clean` |
|---|---|---|---|---|---|
| 1 | Settings key | `HKCU\Software\ExplorerF11` | you change a setting away from its default | 12 B per `DWORD`, ~28 B for `Language` | deleted |
| 2 | Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ExplorerF11` | you tick *Start with Windows* | 150–200 B (path length) | deleted |
| 3 | Log file | `%TEMP%\ExplorerF11.log` | you run with `--log` | ~200 B | deleted |
| 4 | Window marks | `ExplorerF11.Marked` property on Explorer windows | every accelerated window | 0 B (memory) | disappears with Explorer |

The settings key can hold at most three values: `Tabs`, `InitialSweep` and
`Language`. `--clean` deletes the whole key, so a clean also resets the UI
language to the system default.

Item 4 never touches disk. It is listed because a user who inspects the process
deserves to know it exists, and because it is the one piece of state that
survives the tool's own exit.

## B. Recorded by Windows because the exe ran

None of these are written by ExplorerF11. Windows creates them for any program
that starts, shows a tray icon, or is launched from Explorer. They are listed
because "I ran it once" is still a footprint, and because most cleanup tools
quietly ignore them.

| # | Item | Location | Written when | Typical size | `--clean` |
|---|---|---|---|---|---|
| 5 | Startup on/off flag | `HKCU\...\Explorer\StartupApproved\Run\ExplorerF11` | autostart exists and Task Manager touches it | 12 B | deleted |
| 6 | Tray icon cache | `HKCU\Control Panel\NotifyIconSettings\{GUID}` | the tray icon is shown | 1–3 KB | deleted |
| 7 | Compatibility Assistant | `HKCU\...\AppCompatFlags\Compatibility Assistant\Store` | first launch | ~90 B | deleted |
| 8 | Friendly name | `HKCU\...\Shell\MuiCache\<path>.FriendlyAppName` | first launch | ~120 B | deleted |
| 9 | Launch counter | `HKCU\...\Explorer\UserAssist\{GUID}\Count` | first launch | ~90 B | deleted |
| 10 | Prefetch | `%WINDIR%\Prefetch\EXPLORERF11.EXE-*.pf` | first launch (if enabled) | 10–30 KB | deleted if elevated |

Items 6–10 come back the next time the exe runs. That is OS behaviour, not a bug
in the cleanup: deleting them is a courtesy, not an uninstall.

Item 10 is only readable by administrators. Without elevation the report shows it
as absent and `--clean` skips it silently — it cannot delete what it cannot open.

## C. Legacy leftovers (v4 and earlier)

| # | Item | Location | `--clean` |
|---|---|---|---|
| 11 | Old settings key | `HKCU\Software\ExplorerF11Ultra` | deleted |
| 12 | Old autostart | `HKCU\...\Run\ExplorerF11Ultra` | deleted |
| 13 | Old startup flag | `HKCU\...\StartupApproved\Run\ExplorerF11Ultra` | deleted |

These exist only on machines that ran a pre-5.0 build, which used the product
name *ExplorerF11Ultra*. 6.x migrates them on first start (the autostart entry is
rewritten to point at the new exe), and `--clean` removes them.

## D. The program file

| # | Item | Location | Removed by |
|---|---|---|---|
| 14 | `ExplorerF11.exe` | wherever you put it | you, after `--clean` |

Not residue. It is the program. Deleting it is the last step of an uninstall and
is deliberately left to the user.

## Total

Everything removable, worst case: **under 6 KB** (prefetch excluded, it is a
cache Windows manages itself). Nothing grows with use: no history, no database,
no cache of our own, and no log unless you ask for one.

## Why the default is zero

Four rules, enforced in `config.cpp`:

1. A value is written **only** while it differs from its default.
2. Setting it back to the default **deletes** the value.
3. Deleting the last value **deletes the key**.
4. The UI language follows the same rule with the system language as its default,
   so picking your own language leaves no value at all.

So a fresh run creates nothing, and "reset everything" is byte-for-byte identical
to "never installed". Autostart is the same: unticked means no `Run` value at all,
not a value pointing at nothing.

## Verifying by hand

Registry: `Win+R` → `regedit` → paste a path from the table into the **address
bar** (not the search box). "Not found" means clean. To sweep everything at once:
`Ctrl+F`, search `ExplorerF11`, then `F3`.

Files:

```powershell
Test-Path "$env:TEMP\ExplorerF11.log"
Get-ChildItem "$env:WINDIR\Prefetch\EXPLORERF11.EXE-*.pf" -ErrorAction SilentlyContinue
```

Automated:

```powershell
ExplorerF11.exe --status           # full report
ExplorerF11.exe --status --lang en
if ($LASTEXITCODE -eq 0) { "clean" } else { "traces present" }
```

## Removing everything

```powershell
ExplorerF11.exe --clean     # removes groups A (1-3), B, C; leaves the exe
Remove-Item .\ExplorerF11.exe
```

`--clean` also stops a running instance first, and prints a per-category report of
what it removed. If a category is missing from that report, nothing of that kind
was there.
The tray window has the same button. It refreshes in place, so the report you are
reading turns into "clean" without reopening anything.
