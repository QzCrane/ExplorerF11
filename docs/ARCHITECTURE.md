# Architecture

## Goal and non-goals

**Goal.** Reproduce, automatically, the state Windows 11 File Explorer is in after
a manual `F11` round trip — for every folder window and every new tab — while
staying invisible, cheap, and removable.

**Non-goals.** Fixing the underlying shell behaviour, hooking Explorer, patching
memory, replacing the file manager UI, or bundling an installer. If Microsoft
ever ships a real fix, this project becomes unnecessary and should be deleted.

## Module map

```
src/
  app.h          every name the tool writes into the system, in one place
  i18n.h         language resolution + T(zh, en); switchable while running
  config.h/.cpp  settings and autostart (HKCU only)
  footprint.h/.cpp  enumerate, report and remove every trace
  main.cpp       window, tray, shell hooks, menu, report window, CLI
```

Dependencies point one way: `main` → `footprint` → `config` → `app`/`i18n`.
Nothing in `config.cpp` or `footprint.cpp` opens a window or shows a dialog, which
is what makes them testable from a console.

## Event model

Four entry points, all event-driven. There is no timer in the steady state and no
enumeration loop.

| Trigger | API | Handles |
|---|---|---|
| A folder window is created | `RegisterShellHookWindow` → `HSHELL_WINDOWCREATED` | the common case |
| A tab is created inside an existing window | `SetWinEventHook(EVENT_OBJECT_CREATE)` filtered to `ShellTabWindowClass` | the `+` button, `Ctrl+T`, middle-click |
| A window is restored from minimised | `SetWinEventHook(EVENT_SYSTEM_MINIMIZEEND)` | restored windows come back with rebuilt chrome |
| The tool starts | `WM_APP_INITIAL`, posted after the message loop starts | windows that already existed |
| Explorer restarts | `TaskbarCreated` broadcast | re-register the hook, rebuild the tray icon |

`HSHELL_WINDOWCREATED` is a desktop-wide broadcast: the shell does not offer
per-class subscription, so every window creation arrives and is filtered with
`GetClassNameW`. That is one string compare per new window on the desktop —
cheaper than any alternative, including a `SetWinEventHook` on `EVENT_OBJECT_SHOW`
(which fires far more often and needs the same filter).

Tabs are the exception that forces a second mechanism: a new tab is a child
`ShellTabWindowClass` window inside an existing `CabinetWClass`, so no top-level
window event fires. `EVENT_OBJECT_CREATE` is the only notification that arrives
before the tab paints.

## Why `PostMessage` and not `SendInput`

`SendInput` synthesises real keyboard input: it goes to the foreground window,
steals focus if the target is not in front, and can interleave with what the user
is typing. `PostMessageW(hwnd, WM_KEYDOWN, VK_F11, 0)` delivers the same message
the keyboard driver would, directly to the window's queue, without touching focus
or the input state. Two press/release pairs are posted, each return value checked.

If a pair does not land, a 500 ms one-shot timer checks whether the window is
still fullscreen and posts a single F11 to get it out. That recovery can only ever
*exit* fullscreen, so the worst case is "nothing happened", never "stuck in
fullscreen".

## Why a window property instead of an HWND set

`SetPropW(hwnd, L"ExplorerF11.Marked", ...)` stores the mark in the window
itself, for three reasons:

1. **It survives our exit.** Relaunching the tool does not re-accelerate windows
   that are already accelerated, so the start-up sweep can skip them.
2. **It dies with the window.** No bookkeeping to leak, no stale handles, no
   `HWND` reuse bug (a recycled handle would look "already done" in a set).
3. **It is readable across processes.** The report can count marked windows
   without injecting anything.

The mark also carries a tick count, used as a 1.2 s gate: when a window is created
it creates its first tab immediately, and the tab hook would otherwise fire a
second F11 cycle on a window that is still animating.

## What the count means

`MarkedWindows()` in `footprint.cpp` walks the top-level windows once, counts the
ones carrying the mark, and for each counts its direct `ShellTabWindowClass`
children. The same function formats the sentence ("1 window accelerated (2 tabs)"),
and the tooltip, the menu header and the footprint report all call it. No other
file builds a count of its own, so the three surfaces cannot disagree.

The unit is the window because the action is: `PostF11Raw` posts to the frame
(`CabinetWClass`), and the whole frame — every tab in it — enters and leaves
fullscreen together. A tab has no independent F11 state, so counting tabs as
separately accelerated would claim something the tool cannot do. The bracketed
figure describes what those windows currently hold, nothing more: a new tab is
handled by re-posting to its parent, never by poking the tab itself.

## Explorer restart

`explorer.exe` restarting destroys the shell hook registration and the tray icon.
A hidden top-level window — not `HWND_MESSAGE` — still receives the
`TaskbarCreated` broadcast; a message-only window does not, which is why v1 went
silent after every Explorer crash.

On `TaskbarCreated` the tool deregisters (a second `RegisterShellHookWindow` in the
same process fails), re-registers, removes and re-adds the tray icon. If
re-registration fails, it relaunches itself with `GetCommandLineW()`, so every flag
survives. It never runs two copies: the mutex is released before spawning.

## Resource profile

Measured with `test_smoke.py` on 26300.9974, one folder window open:

| | Idle | Notes |
|---|---|---|
| Private bytes | 3.5 MB | no CRT heap growth after start-up |
| Handles | 148 | of which 1 is ours (the single-instance mutex); the rest are the window, hooks, tray icon and thread pool |
| Threads | 4 → 1 | 3 are `TpWorkerFactory` helpers that exit after ~45 s idle |
| CPU | 0 % | blocked in `GetMessageW` |
| Disk | 294 KB | static CRT, `-Os`, stripped |

## Settings

`HKCU\Software\ExplorerF11` holds **only deviations from the defaults**. Writing a
value equal to its default deletes it, and deleting the last value deletes the
key. A fresh run therefore creates nothing, and "reset to defaults" is
indistinguishable from "never installed". The key can hold three values: `Tabs`,
`InitialSweep` (both `REG_DWORD`) and `Language` (`REG_SZ`, `zh` or `en`).

`Language` uses the system language as its default: choosing the language the
machine already speaks deletes the value instead of writing it, so the language
feature cannot turn a zero-footprint install into a one-value install.

Autostart is one `REG_SZ` under the per-user `Run` key, containing a quoted path
and no arguments. Because preferences are in the registry rather than on the
command line, autostart and a manual double-click behave identically.

`StartupApproved\Run\ExplorerF11` is Windows' own enable/disable flag, written
when the user disables the entry in Task Manager. The tool treats "Run value
present **and** not disabled" as enabled, and deletes the flag when enabling, so
the tick mark always matches what will actually happen at logon.

## Language

`i18n.h` keeps a single enum plus one function:

```cpp
const wchar_t *T(const wchar_t *zh, const wchar_t *en);
```

Every user-visible string is written at its point of use with both translations
side by side. For a single-binary utility this beats a resource DLL: no build step,
no satellite files, no `LoadString` failure mode, and a reviewer can see at a
glance whether a string was forgotten in one language.

Resolution order, highest priority first:

| Source | Scope | Implemented by |
|---|---|---|
| `--lang zh\|en` | this run | argument parser sets `g_langExplicit` |
| `EXPLORERF11_LANG` | this run | `EnvLang()` |
| `Language` value | persistent | `LoadLanguage()` |
| system language | default | `LocaleLang()` |

The locale check consults the regional format before the UI language, because an
English UI on a Chinese region is common and those users expect Chinese.

**Switching while running** needs no re-layout, because nothing caches the text:

- the tray menu is rebuilt from `BuildTrayMenu()` on every right click, so it is
  localised by construction;
- the tooltip is `NIF_TIP` on a `NIM_MODIFY` call, refreshed whenever the state or
  the language changes;
- the report window is the only long-lived surface, so `RelocalizeStatus()` sets
  the title, the three buttons and the body again when the language changes.

The radio pair inside the submenu is deliberately written in each language's own
script (中文（简体） / English). A user who switches to a language they cannot read
still recognises the row that switches back.

## Tests

The test suite drives the built binary through its public surface (`--menu`,
`--status`, `WM_COMMAND` to the hidden window) instead of linking against
internals. Two consequences worth keeping:

- `--menu` prints the menu that `BuildTrayMenu()` actually built — including
  submenus, as indented rows — so the layout test cannot drift from the UI.
- every test that changes state restores it, including the autostart entry and
  the stored language, and the clean-button test refuses to run on a machine that
  has real traces.

Six suites, each asserting and returning a non-zero exit code on failure:

| Suite | Proves |
|---|---|
| `test_menu_order.py` | exact rows, groups, ticks, language radio pair |
| `test_footprint_report.py` | report truth, both languages, live relocalisation |
| `test_registry_policy.py` | zero writes by default, defaults delete themselves |
| `test_language.py` | resolution order, persistence, zero-write rule |
| `test_tray_cleanup.py` | cleanup is surgical, other programs' entries survive |
| `test_smoke.py` | real window accelerated, resource profile, clean exit |

## Known limits

- The acceleration depends on undocumented shell behaviour. A Windows build may
  change it; the tool then quietly does nothing rather than breaking anything.
- Windows opened before start-up need the start-up sweep. If it is disabled, or
  if the window was created while the tool was not running, that window stays
  unaccelerated until "Apply to all open windows".
- `EVENT_OBJECT_CREATE` fires for every object on the desktop; the handler filters
  on class name and process id, but this is the one hook with a measurable,
  if tiny, cost per event.
- Prefetch entries can only be removed with elevation. `--clean` reports the
  count it could not delete rather than pretending otherwise.
