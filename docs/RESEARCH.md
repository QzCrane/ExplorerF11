# Research notes: the F11 trick

Observations, update history and rejected approaches behind ExplorerF11. Recorded
on 2026-11-15 against Windows 11 26H2 build 26300.9974 with KB5132061 and
KB5132688 installed. Claims about other builds are not implied.

## Observation

Explorer's command bar, address bar and navigation pane are XAML. Each
navigation re-synchronises that layer. Pressing `F11` twice — into fullscreen,
then back — destroys the chrome and rebuilds it, and the rebuilt window
navigates faster. On the test machine `PostMessage` changed the window style
from `0x14cf0000` to `0x140a0000` and the rectangle to `1920×1080`; a second
press restored both exactly. The difference is most visible when scrolling a
folder with several shell extensions installed.

This is a workaround for undocumented behaviour, not a fix. If Microsoft makes
native Explorer fast enough, the tool should be retired.

## Has Microsoft patched it?

As of 2026-11-15, no update specifically targets the F11 difference. No release
note mentions it, and there is no public A/B evidence that a cumulative update
closes the gap.

Updates in 2026 addressed symptoms people attributed to the same cause:

| Update | What it changed |
|---|---|
| KB5074105, KB5089573 | shell responsiveness work, including a low-latency CPU profile for interactive threads |
| KB5095093, KB5101684 | Home and navigation rework; removed the grey flash on folder open |
| KB5124006, KB5132061 | redesigned, faster context menu |

Each removes a symptom. None makes the manual F11 round trip stop helping,
which is the practical test.

## ViVeTool flags

Three flags recur in threads about Explorer performance. Checked on the test
machine:

| ID | Purpose | State found | Relevance to F11 |
|---|---|---|---|
| 58989092 | low-latency CPU profile for shell interaction | no override; broadly enabled by default since mid-2026 | none — scheduling, not chrome rebuild |
| 60813048 | redesigned customisable context menu | enabled with KB5132061 | none |
| 58778013 | Explorer window preloading | not enabled; `ShouldPrelaunchFileExplorer` unset | cold start only |

Enabling them does not reproduce the F11 effect. They change the context menu,
cold start and thread scheduling; the F11 effect comes from the XAML chrome
leaving the navigation path altogether. Treating the two as the same thing is
the most common error in discussions of the topic.

## Existing tools

Everything publicly findable as of 2026-11-15. All simulate F11; none is a
patch.

| Project | Detection | Key injection | Blocking | Fatal flaw |
|---|---|---|---|---|
| [ExplorerF11Fix](https://github.com/schalkburger/ExplorerF11Fix) (344★) | none | AHK `Send` | none | one-shot launcher: handles only the window it opened |
| [ExplorerFast](https://github.com/YuanQinHongXin/ExplorerFast) (3★) | enumerate all top-level windows every 100 ms | AHK `Send` | `Sleep 2000` inside the callback | blocks its own thread for 2 s, never removes handled entries, unmaintained since 2024-01 |
| [Win11ExplorerFix](https://github.com/arjun-arihant/Win11ExplorerFix) | foreground window id every 1 s | AHK `Send` | 1 s timer | misses windows opened in the background |
| ExplorerAccel (repository 404) | `RegisterShellHookWindow` | `PostMessage` F11 ×2 | none | source unavailable; no pause; hourly handle cleanup |

ExplorerF11Fix has eight public forks (mirrors, translations, an AHK v2
upgrade); the other two have none.

Only two choices in that comparison matter: detection and injection. A shell
hook beats a timer because it has zero idle cost and zero latency. `PostMessage`
beats `Send`/`SendInput` because it does not steal focus or touch real keyboard
state. ExplorerAccel had the right architecture and an unreachable repository;
this project rebuilt that architecture, which was published under MIT, and
closed its gaps.

## Approaches evaluated and rejected

These were built or scripted during the investigation and deliberately not
shipped. They are recorded so nobody repeats them.

**AutoHotkey scripts, two variants.** One polled `CabinetWClass` every 300 ms and
slept for 2 s inside the callback; the other used `ShellHook` and avoided
polling. Both used `Send`, so both stole focus and blocked on the target's
message queue. They established that the event model was right and the
injection mechanism wrong. Deleted; the C++ implementation supersedes them.

**ViVeTool switch script.** A `.cmd` enabling the three feature IDs above and
asking for a reboot. It does not address the problem, needs administrator
rights, and leaves `FeatureManagement\Overrides` behind. Deleted.

**Registry "performance" tweaks.** `NtfsMemoryUsage`, `Superfetch`,
`ShellIconCache` and similar recipes. None reproduced the effect, several have
known downsides on modern builds, and all resist uninstall. Not implemented.

**Replacing Explorer.** ExplorerPatcher (installed on the test machine) and
StartAllBack change the shell UI, not the chrome rebuild path. They do not make
navigation faster and carry their own compatibility risk across builds — an
installed 26100 build on a 26300 system is exactly that case.

## Implementation decisions

| Decision | Choice | Reason |
|---|---|---|
| Detection | `RegisterShellHookWindow` | zero polling, arrives at window creation |
| Injection | `PostMessageW` × 4 (two press/release pairs) | no focus theft, works on a background window; `lParam = 0` and back-to-back posts both verified |
| Host window | hidden top-level window | `HWND_MESSAGE` windows never receive `TaskbarCreated`, so the tool went silent on every Explorer restart |
| De-duplication | `ExplorerF11.Marked` + `ExplorerF11.Tick` window properties | an `HWND` set misjudges after handle reuse; the tick also gates the tab hook for 1.2 s after creation |
| Recovery | 500 ms timer, all at-risk windows, `(hwnd, tick)` identity | can only exit fullscreen; a recycled handle is never poked or unmarked |
| Tabs | `SetWinEventHook(EVENT_OBJECT_CREATE)` | a tab is a child window and fires no shell hook |
| Configuration | registry, deviations only | command-line preferences are lost on autostart and on self-relaunch; defaults should not be on disk |
| Console output | `WriteConsoleW` to consoles, UTF-8 `WriteFile` to pipes | no code-page transcoding; the `CONOUT$` fallback handle is closed after use |

## Evidence from the test machine

- `PostMessage` F11 changes the style and rectangle as quoted above; a second
  press restores them exactly.
- End-to-end log: `started (tab hook ok)` → `accelerated: drivers - File Explorer`.
- Steady state shortly after start-up: 1.76-1.77 MB private, 129 handles, 4 threads
  (three `TpWorkerFactory` helpers settle out after roughly 45 s idle), 0.03 s
  cumulative CPU per two minutes.
- Registry policy: zero writes on a default run, values deleted when returned
  to default, `--clean` returns to zero — see `tests/test_registry_policy.py`.

## What this document cannot answer

**How much faster it is on your machine.** The difference depends on shell
extensions, folder size and the Windows build. Measure it yourself: open two
identical folders, apply the tool to one, and scroll both. If the difference is
under roughly 10%, there is little reason to keep it resident — leave it in the
tray and use it only for the folders where it matters.
