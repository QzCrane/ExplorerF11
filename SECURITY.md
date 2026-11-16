# Security policy

ExplorerF11 posts two window messages to File Explorer windows. It is a small
program, but it runs next to the shell, so this document states exactly what it
does with your privileges, what it never does, and how to check both claims
against a downloaded binary.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes — security fixes land in the next 1.0.z patch |
| Anything else | No. Builds numbered above 1.0.0 before release were internal build numbers and were never published. |

## Reporting a vulnerability

Open a private report through GitHub:

**https://github.com/QzCrane/ExplorerF11/security/advisories/new**

Please do not open a public issue for anything that could be exploited before a
fix is available.

A useful report contains:

- the Windows build number (`winver`) and the architecture;
- the exact command line used, and whether autostart was enabled;
- the output of `ExplorerF11.exe --status --lang en` and, if you ran with
  `--log`, the lines from `%TEMP%\ExplorerF11.log`;
- what an attacker gains that they did not have before — for a local utility
  that runs with the user's own token, "it runs code as me" is not a
  vulnerability, but "another process can make it run code" is.

This is a single-maintainer project with no funding; reports are handled on a
best-effort basis, typically within a week. There is no bug bounty.

## What the program does with your privileges

- **It never elevates.** There is no `runas` launch, no `ShellExecuteEx`
  elevation request, no `IsUserAnAdmin` check and no service. Everything runs
  with the token of the user who started it. Removing Prefetch entries is the
  only operation that can require elevation, and without it those entries are
  simply reported as skipped.
- **It writes to `HKCU` only**, and only when a setting leaves its default:
  `HKCU\Software\ExplorerF11` (three values), the `Run` autostart value, and
  Windows' own `StartupApproved` flag when autostart is toggled.
- **It writes one file, and only on request**: `%TEMP%\ExplorerF11.log`, when
  started with `--log`.
- **It reads the command line and its own registry values.** Malformed values
  fall back to defaults; the program never treats stored data as code.

## What it never does

- **No network access.** The import table is `KERNEL32`, `USER32`, `GDI32`,
  `SHELL32`, `ADVAPI32`, `msvcrt` — no WinINet, WinHTTP, `ws2_32` or DNS API.
  There is no update check and no telemetry, so nothing can be fetched into the
  process at run time.
- **No injection.** No `SetWindowsHookEx` with a DLL, no `CreateRemoteThread`,
  no `WriteProcessMemory`, no `QueueUserAPC`, no AppInit/shim. The only
  cross-process action is `PostMessageW` (and `WM_CLOSE` is never posted by the
  accelerator; the report window closes only its own windows).
- **No code loading at run time.** No `LoadLibrary` of a path from disk, no
  script engine, no plugin directory.
- **No privilege boundary crossed.** It cannot affect a window owned by another
  user or another elevation level; `PostMessageW` is filtered by UIPI exactly as
  the operating system intends.

## Attack surface, in full

| Surface | Input | Handling |
|---|---|---|
| Command line | `--lang`, `--install`, `--clean`, … | fixed set; anything else is echoed back with a pointer to `--help` and exit code 2, never ignored; `--lang` is matched against five tags plus aliases, and an unresolvable tag is a usage error |
| Registry | `Tabs`, `InitialSweep`, `Language`, `Run` value | read as data, unknown values fall back to defaults |
| Window messages | `TaskbarCreated`, shell hook notifications, `WM_CLOSE` on its own hidden window | class and process checked before acting |
| Tray | menu commands | the only destructive command asks for confirmation and lists what it deletes |

## Verifying a release

Every release page lists a SHA-256 for the uploaded exe. Check it before running
the binary:

```powershell
Get-FileHash .\ExplorerF11-1.0.0-win64.exe -Algorithm SHA256
(Get-Item .\ExplorerF11-1.0.0-win64.exe).VersionInfo.FileVersion   # 1.0.0.0
.\ExplorerF11-1.0.0-win64.exe --version                            # ExplorerF11 1.0.0
```

To confirm the import table yourself:

```powershell
dumpbin /imports .\ExplorerF11-1.0.0-win64.exe | Select-String "\.dll"
```

**The binary is not code-signed.** Windows SmartScreen will therefore warn on
first run — that is expected for an unsigned single-file utility, and the hash on
the release page is the integrity check that replaces a signature. Building from
source is the stronger option, and the build is one command (see
[README](README.md#build)).

## Out of scope

- Explorer crashes or slowdowns caused by third-party shell extensions.
- Antivirus heuristics that flag any program calling `PostMessageW` or
  registering a shell hook. Report those to the vendor; the behaviour is
  documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- The absence of a Microsoft code-signing certificate.
- Anything that requires the attacker to already run code as the same user, with
  the same integrity level, and with the ability to start processes — at that
  point the tool grants nothing that was not already available.
