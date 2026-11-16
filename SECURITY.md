# Security policy

ExplorerF11 runs with the token of the user who launched it and sends two window
messages to Explorer. This document states the resulting privilege boundary, the
inputs the program accepts, and how to check both claims against a downloaded
binary.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes — security fixes ship as later 1.0.x patches |
| Anything else | No. Numbers above 1.0.0 that predate the first release were internal build numbers and were never published. |

## Reporting a vulnerability

Use the private GitHub channel:

**https://github.com/QzCrane/ExplorerF11/security/advisories/new**

Do not open a public issue for anything exploitable before a fix exists. A useful
report includes:

- the Windows build number (`winver`) and architecture;
- the exact command line, and whether autostart was enabled;
- output of `ExplorerF11.exe --status --lang en`, plus the relevant lines from
  `%TEMP%\ExplorerF11.log` if it was started with `--log`;
- what an attacker gains that they did not already have. For a utility running
  under the user's own token, "it runs code as me" is not a vulnerability;
  "another process can make it run code" is.

This is an unfunded, single-maintainer project. Reports are handled on a
best-effort basis, usually within a week; there is no bug bounty.

## Privilege boundary

- **No elevation.** No `runas`, no `ShellExecuteEx` elevation request, no
  `IsUserAnAdmin` branch and no service. Everything runs on the launching
  user's token. Removing Prefetch entries is the only operation that may need
  elevation; without it, those entries are reported as skipped.
- **HKCU only.** `HKCU\Software\ExplorerF11` holds at most three values, and
  only when they differ from defaults. The autostart value lives under the
  per-user `Run` key. Windows' own `StartupApproved` flag is written when
  autostart is toggled in Task Manager.
- **One file on request.** `%TEMP%\ExplorerF11.log` is created only with
  `--log`.
- **Registry values are data, not code.** Malformed values fall back to
  defaults; nothing read from the registry is executed or interpreted as a
  command.

## What the binary does not contain

- **No network.** The import table is `KERNEL32`, `USER32`, `GDI32`, `SHELL32`,
  `ADVAPI32` and `msvcrt` — no WinINet, WinHTTP, `ws2_32` or DNS API. There is no
  update check and no telemetry, so nothing can be fetched into the process at
  run time.
- **No injection.** No `SetWindowsHookEx` with a DLL, no `CreateRemoteThread`,
  no `WriteProcessMemory`, no `QueueUserAPC`, no AppInit or shim. The only
  cross-process action is `PostMessageW`. The accelerator never posts
  `WM_CLOSE`; the report window closes only its own windows.
- **No run-time code loading.** No `LoadLibrary` of a path from disk, no script
  engine, no plugin directory.
- **No crossing of a privilege boundary.** UIPI filters `PostMessageW` exactly
  as Windows intends, so a window owned by another user or a higher integrity
  level is out of reach.

## Attack surface

| Surface | Input | Handling |
|---|---|---|
| Command line | `--lang`, `--install`, `--clean`, … | fixed option set; the first unplaceable token is echoed with a pointer to `--help` and exit code 2. `--lang` is matched against five tags and their aliases; an unresolved value is a usage error, and a following option is never consumed as a value |
| Registry | `Tabs`, `InitialSweep`, `Language`, `Run` value | read as data; unknown values fall back to defaults |
| Window messages | `TaskbarCreated`, shell-hook notifications, `WM_CLOSE` on the tool's own window | class and process identity are checked before acting |
| Tray | menu commands | the sole destructive command asks for confirmation and lists what it deletes |

## Verifying a release

Every release page attaches `SHA256SUMS.txt` alongside the exe. It is a GNU
`sha256sum` check-file: one line of `digest␠␠filename`, where the second space is
the text-mode flag, not padding. The filename itself is a convention with no
meaning to the tool — `sha256sum -c` reads any filename. What matters is that
the digest is paired with the asset name in the file *content*. On Windows:

```powershell
Get-FileHash .\ExplorerF11-1.0.5-win64.exe -Algorithm SHA256
(Get-Item .\ExplorerF11-1.0.5-win64.exe).VersionInfo.FileVersion   # 1.0.5.0
.\ExplorerF11-1.0.5-win64.exe --version                            # ExplorerF11 1.0.5
```

With Git Bash or a GNU userland, verify the whole manifest instead:

```sh
sha256sum -c SHA256SUMS.txt
```

The import table can be checked independently:

```powershell
dumpbin /imports .\ExplorerF11-1.0.5-win64.exe | Select-String "\.dll"
```

The binary is **not code-signed**, so SmartScreen warns on first run. That is
expected for an unsigned single-file utility: the published hash is the
integrity check that replaces a signature. Building from source is the stronger
option and takes one command — see [README](README.md#build).
[docs/SIGNING.md](docs/SIGNING.md) has the numbers behind that decision, and
states the one thing a certificate would not fix: a new release still warns
until its publisher reputation accumulates.

A hash proves the file matches the release page. It does not prove the release
page belongs to this project; check that you followed a link from the
repository before trusting either.

## Out of scope

- Explorer crashes or slowdowns caused by third-party shell extensions.
- Antivirus heuristics that flag any program calling `PostMessageW` or
  registering a shell hook. Report those to the vendor; the behaviour is
  documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- The absence of a Microsoft code-signing certificate.
- Any scenario where the attacker already runs code as the same user, at the
  same integrity level, with the ability to start processes. At that point the
  tool grants nothing that was not already available.
