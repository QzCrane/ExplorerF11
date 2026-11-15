# Changelog

All notable changes to this project. Versions follow [SemVer](https://semver.org/).

## 6.0.0 - 2026-11-15

Repository and architecture release; same behaviour as 5.3 plus a complete
footprint model.

### Added
- **Bilingual UI** (Chinese / English), chosen from `--lang`, `EXPLORERF11_LANG`
  or the Windows display language. No resource DLL, no restart.
- **Full footprint report** (`--status`, tray window): 14 items in four groups -
  what this program wrote, what Windows recorded because it ran, legacy v4
  leftovers, and the program file itself. Each item shows who wrote it, the exact
  location, current contents and byte count.
- **`--clean` now removes everything removable**, including Windows' own
  bookkeeping: tray-icon cache, StartupApproved flag, Compatibility Assistant
  store, MuiCache name, UserAssist counters and Prefetch entries.
- `--help`, `--version`, `make test`, GitHub Actions build.

### Changed
- Source split into `main.cpp` / `config.cpp` / `footprint.cpp` with `app.h`,
  `i18n.h`; no behaviour change intended.
- Default build output moved to `dist/ExplorerF11.exe`.
- Tests moved to `tests/` and made path-independent.

### Fixed
- Report punctuation and singular/plural wording in the menu header.
- Language detection now also consults the regional locale, so an English UI on
  a Chinese region still gets Chinese.

## 5.3.0 - 2026-11-15

- Tray menu rebuilt: one grey status line, then actions / settings / maintenance /
  exit. Destructive item separated from Exit.
- "Apply to current window" now targets the last folder window the shell reported
  as activated, instead of the foreground window (which is the taskbar at click
  time, or our own hidden window).
- `--menu` dumps the real menu for tests.

## 5.2.0 - 2026-11-15

- Registry footprint report: menu shows clean / N places, window lists each
  location with writer, path, contents and size, and can clean in place.
- `--status` prints the report; exit code 0 = clean, 1 = traces.

## 5.1.0 - 2026-11-15

- Autostart honours and clears Windows' `StartupApproved` flag, so the tick mark
  matches reality after a Task Manager disable, and re-enabling works.

## 5.0.0 - 2026-11-15

- Renamed to ExplorerF11. Zero registry writes in the default configuration;
  returning a setting to its default deletes it and prunes an empty key.
- `--clean`, automatic migration of the v4 key and Run value.

## 4.0.0 - 2026-11-15

- Preferences persisted in `HKCU\Software\ExplorerF11Ultra`; the former
  `--no-initial` became a tray toggle; self-relaunch reuses the command line.

## 3.1.0 - 2026-11-15

- Start-up sweep for windows that already existed; restore-from-minimized hook.

## 3.0.0 - 2026-11-15

- New tabs: WinEvent hook on `ShellTabWindowClass` child creation.

## 2.0.0 - 2026-11-15

- Hidden top-level window so `TaskbarCreated` reaches us; shell hook and tray
  survive an explorer restart.
- Per-window `SetPropW` marker instead of an HWND set; every `PostMessage`
  checked, with a recovery that can only ever exit fullscreen.

## 1.0.0 - 2026-11-15

- First working build: shell-hook driven, posts two F11 cycles per folder window.

## Pre-history

Behavioural research on the F11 trick, the available third-party tools and the
rejected approaches (AutoHotkey scripts, ViVeTool feature flags) is documented in
[docs/RESEARCH.md](docs/RESEARCH.md). None of them shipped in this repository.
