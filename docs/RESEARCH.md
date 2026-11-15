# Research notes: the F11 trick

Why this project exists, what was measured, and what was rejected. Dated
2026-11-15, on Windows 11 26H2 build 26300.9974 with KB5132061 and KB5132688.

## The observation

Explorer's command bar, address bar and navigation pane are XAML. Every
navigation re-synchronises that layer. Pressing `F11` twice — fullscreen, then
back — destroys and rebuilds the top-level chrome, and the rebuilt window
navigates faster.

Measured with `PostMessage` on the test machine: window style
`0x14cf0000 → 0x140a0000`, rectangle becomes `1920×1080`, and a second press
restores it exactly. The performance difference is not a benchmark artefact; it is
visible when scrolling a folder with many shell extensions.

**Caveat, stated once and meant:** this is a workaround for undocumented
behaviour, not a fix. If Microsoft makes native Explorer fast, this project
should be deleted.

## Has Microsoft patched it?

As of 2026-11-15: **no update specifically targets the F11 difference.** No
release note mentions it, and there is no public A/B evidence that any cumulative
update closes the gap.

What 2026's updates did address, in the same neighbourhood:

| Update | What it changed |
|---|---|
| KB5074105, KB5089573 | shell responsiveness work, including a low-latency CPU profile for interactive threads |
| KB5095093, KB5101684 | Home and navigation rework; grey-flash removal on folder open |
| KB5124006, KB5132061 | redesigned, faster context menu |

Each removes a *symptom* that people blamed on the same root cause. None of them
makes the manual F11 round trip stop helping, which is the practical test.

## ViVeTool feature flags

Three flags circulate in threads about Explorer performance. Checked on the test
machine:

| ID | Purpose | State found | Relevance to F11 |
|---|---|---|---|
| 58989092 | low-latency CPU profile for shell interaction | no override; broadly enabled by default since mid-2026 | none — scheduling, not chrome rebuild |
| 60813048 | redesigned customisable context menu | enabled with KB5132061 | none |
| 58778013 | Explorer window preloading | not enabled; `ShouldPrelaunchFileExplorer` unset | cold start only |

Enabling these does not reproduce the F11 effect. They change the context menu,
cold start and thread scheduling; the F11 effect comes from the XAML chrome
leaving the navigation path entirely. Conflating the two is the most common
mistake in threads on the topic.

## Existing tools

Everything publicly findable, as of 2026-11-15. All of them simulate F11; none is
a patch.

| Project | Detection | Key injection | Blocking | Fatal flaw |
|---|---|---|---|---|
| [ExplorerF11Fix](https://github.com/schalkburger/ExplorerF11Fix) (344★) | none | AHK `Send` | none | one-shot launcher: handles only the window it opened |
| [ExplorerFast](https://github.com/YuanQinHongXin/ExplorerFast) (3★) | enumerate all top-level windows every 100 ms | AHK `Send` | `Sleep 2000` inside the callback | blocks its own thread for 2 s; never removes handled entries; unmaintained since 2024-01 |
| [Win11ExplorerFix](https://github.com/arjun-arihant/Win11ExplorerFix) | foreground window id every 1 s | AHK `Send` | 1 s timer | misses windows that open in the background |
| ExplorerAccel (repository 404) | `RegisterShellHookWindow` | `PostMessage` F11 ×2 | none | source unavailable; no pause; handle cleanup hourly |

ExplorerF11Fix has eight public forks (mirrors, translations, an AHK v2 upgrade);
the other two have none.

### What the comparison actually decides

Only two choices matter:

1. **Detection.** A shell hook beats a timer: zero idle CPU, zero latency.
2. **Injection.** `PostMessage` beats `Send`/`SendInput`: no focus theft, no real
   keyboard state, asynchronous.

ExplorerAccel had the right architecture and an unreachable repository. This
project rebuilds that architecture (the design was published under MIT) and fixes
its gaps.

## Approaches evaluated and rejected

These were built or scripted during the investigation and deliberately **not**
shipped. They are recorded here so nobody repeats them.

**AutoHotkey scripts (two variants).** One polled `CabinetWClass` every 300 ms and
took a 2 s nap in the callback; the other was event-driven via `ShellHook` and
avoided the polling entirely. Both still used `Send`, so both stole focus and
blocked on the target's message queue. They proved the event model was right and
the injection mechanism was wrong. Deleted; the C++ implementation supersedes
them.

**ViVeTool switch script.** A `.cmd` that enabled the three feature IDs above and
told the user to reboot. It does not address the problem (see the table), needs
administrator rights, and writes `FeatureManagement\Overrides` that are easy to
forget. Deleted.

**Registry "performance" tweaks.** Various `NtfsMemoryUsage`, `Superfetch` and
`ShellIconCache` recipes. None of them reproduced the effect, several have known
downsides on modern builds, and all of them are uninstall-resistant. Not
implemented.

**Replacing Explorer.** ExplorerPatcher (installed on the test machine) and
StartAllBack change the shell's UI, not the chrome rebuild path. They do not make
navigation faster, and they carry their own compatibility risk across Windows
builds (the installed 26100 build against a 26300 system is exactly that case).

## Implementation decisions

| Decision | Choice | Why |
|---|---|---|
| Detection | `RegisterShellHookWindow` | zero polling, arrives at window creation |
| Injection | `PostMessageW` × 4 (two press/release pairs) | no focus theft, works on a background window; `lParam = 0` and back-to-back posts both verified |
| Host window | hidden **top-level** window | message-only windows (`HWND_MESSAGE`) never receive the `TaskbarCreated` broadcast, so the tool would die silently on every Explorer restart |
| De-duplication | `SetPropW` window property | an HWND set misjudges after handle reuse; the property dies with the window |
| Tabs | `SetWinEventHook(EVENT_OBJECT_CREATE)` | a tab is a child window and fires no shell hook |
| Configuration | registry, **deviations only** | command-line preferences are lost on autostart and on self-relaunch; defaults should not be on disk |
| Recovery | 500 ms timer after a failed pair | can only ever *exit* fullscreen, so the worst case is "nothing happened" |

## Test-machine evidence

- `PostMessage` F11 changes the style and rectangle as quoted above, and a second
  press restores them exactly.
- End-to-end log: `started (tab hook ok)` → `accelerated: drivers - File Explorer`.
- Steady state: 1 thread, 148 handles, 3.5 MB private, 0.016 s cumulative CPU.
- Registry policy: zero writes on a default run, values deleted when returned to
  default, `--clean` returns to zero (see `tests/test_registry_policy.py`).

## The one thing this document cannot answer

**How much faster it is on your machine.** The difference depends on shell
extensions, folder size and the build in use. Measure it: open two identical
folders, apply the tool to one, scroll both. If the difference is under ~10%, do
not keep it resident — leave it in the tray for the folders where it matters.
