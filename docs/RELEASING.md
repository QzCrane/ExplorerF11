# Releasing

The procedure for cutting a version. It exists because a version number lives in
four places, a release is only as trustworthy as the build behind it, and a
public artefact cannot be corrected after the fact — only superseded.

Versions follow [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`. The tool has
no API, so the practical reading is:

| Bump | When |
|---|---|
| MAJOR | a user-visible behaviour changes in a way the documentation cannot describe as "the same, only better" — a removed flag, a changed residue location, a different counting unit |
| MINOR | a new flag, a new language, a new report field |
| PATCH | a fix that keeps every documented statement true |

## 1. Version numbers

| File | What to change |
|---|---|
| `src/app.h` | `EF11_VERSION L"X.Y.Z"` — what `--version` prints |
| `src/app.rc` | `FILEVERSION X,Y,Z,0` and `PRODUCTVERSION X,Y,Z,0`, plus the `"X.Y.Z.0"` strings for `FileVersion` and `ProductVersion` |
| `CHANGELOG.md` | a `## X.Y.Z - YYYY-MM-DD` heading at the top, above the previous release |
| `.github/workflows/build.yml` | the `findstr /C:"ExplorerF11 X.Y.Z"` assertion in the smoke step |

The CI assertion is deliberately a literal: it fails the build if the binary and
the workflow disagree, which is the failure mode that actually happens (bumping
`app.h` and forgetting `app.rc`).

`test_icons.py` compares the version resource against `--version`, so a mismatch
between `app.h` and `app.rc` also fails locally.

## 2. Gates

Everything below must pass on the commit that will be tagged. `make test` runs
the eleven gates in this order:

| Gate | What it proves |
|---|---|
| `tools/check_i18n.py` | every `T()` key exists in all five languages, placeholders match, the generated table is current |
| `tools/audit_i18n.py` | wrong script, ASCII punctuation glued to CJK, mixed bracket styles, terminology drift |
| `tools/check_help_align.py` | the `--help` option column starts at the same offset in all five languages |
| `tests/test_lang_names.py` | the five language rows are byte-identical in every UI language, and each report header names the active language |
| `tests/test_menu_order.py` | menu structure, the five-row language radio, localised bodies, the counting unit, unknown-option handling |
| `tests/test_residue_report.py` | the report's structure and wording in all five languages |
| `tests/test_registry_policy.py` | nothing is written by default; values are deleted when returned to default |
| `tests/test_language.py` | command-line, environment and tray switching, live repaint, persistence |
| `tests/test_icons.py` | both icons and the version block are in the binary |
| `tests/test_tray_cleanup.py` | `--clean` removes this program's records and nothing else |
| `tests/test_smoke.py` | the event path end to end on a real Explorer window, plus the resource ceilings |

The suites drive the built binary, so build first. `test_smoke.py` opens and
closes a real folder window; run it on a desktop session, not over a service
account.

## 3. Build the artefact

Two build paths exist and both must produce a working binary; the release is
built with the one that is available on the release machine, and the notes state
which one it was.

```bat
build.bat
```

or

```sh
make -B
```

`make -B` rather than `make`: the target only depends on sources, and a stale
`dist\ExplorerF11.exe` from a previous version would otherwise be shipped. If the
linker reports `cannot open output file`, a running instance is holding the exe —
close it from the tray first.

Before tagging, verify the artefact itself:

```powershell
.\dist\ExplorerF11.exe --version                 # ExplorerF11 X.Y.Z
(Get-Item .\dist\ExplorerF11.exe).VersionInfo.FileVersion   # X.Y.Z.0
```

A clean-checkout build is the check that catches files that exist only on the
developer's machine — most often a generated file that `.gitignore` swallowed:

```sh
git ls-files -z | xargs -0 -I{} cp --parents {} /tmp/ef11-check/
cd /tmp/ef11-check && make -B && make test
```

## 4. Tag and release

```sh
git tag -a v1.0.0 -m "ExplorerF11 1.0.0"
git push origin main
git push origin v1.0.0
```

Tag name is `v` + the SemVer number; the release title is `ExplorerF11 1.0.0`.
The release body repeats the CHANGELOG entry in user-facing language and always
states:

- what the binary is (single exe, no installer, no runtime), the architecture
  and the build path used;
- that it is **unsigned**, so SmartScreen will warn, and the SHA-256 to check;
- the residue policy in one sentence;
- a link to `docs/USAGE.en.md` and the CHANGELOG.

Artifact naming: `ExplorerF11-<version>-win64.exe`, plus `SHA256SUMS.txt` with
the line `sha256  ExplorerF11-<version>-win64.exe`. Attach both; never re-upload
a different binary under the same tag.

```sh
sha256sum dist/ExplorerF11.exe
```

## 5. After publishing

- Download the published asset, check its hash, run `--version` and `--status`
  from the downloaded copy. A release that was not downloaded once is untested.
- Confirm the CI run on the tagged commit is green, not just the local one.
- Edit the release, not the tag, for a typo in the notes. For a bad binary:
  publish a new patch version and mark the old release as superseded — a deleted
  release teaches nobody what happened.
