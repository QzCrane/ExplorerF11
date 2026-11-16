# Releasing

A release is a tagged commit, a binary built from that commit, and a checksum
published alongside it. Once an artefact is public it cannot be corrected in
place — only superseded — so the checks below happen before the tag, not after.

Versions follow [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`. The tool has
no API, so the practical reading is:

| Bump | When |
|---|---|
| MAJOR | a documented behaviour changes: a flag is removed, a residue location changes, the counting unit changes |
| MINOR | a new flag, language or report field |
| PATCH | a fix that leaves every documented statement true |

## 1. Move the version

Four files carry the number. All four must change in the same commit:

| File | Field |
|---|---|
| `src/app.h` | `EF11_VERSION L"X.Y.Z"` — what `--version` prints |
| `src/app.rc` | `FILEVERSION X,Y,Z,0`, `PRODUCTVERSION X,Y,Z,0` and the `"X.Y.Z.0"` string values |
| `CHANGELOG.md` | `## X.Y.Z - YYYY-MM-DD` above the previous release |
| `.github/workflows/build.yml` | the `findstr /C:"ExplorerF11 X.Y.Z"` assertion in the smoke step |

The CI assertion is intentionally a literal: it fails the build when the binary
and the workflow disagree, which is the failure that actually happens when
`app.h` is bumped and `app.rc` is forgotten. `test_icons.py` compares the version
resource against `--version`, so the same mismatch also fails locally.

Documentation that names the current artefact — both READMEs, SECURITY.md,
both usage documents and the issue template — needs the new filename and
version too. Historical entries and the release procedure's examples do not.

## 2. Clear the gates

Every gate must pass on the exact commit that will be tagged. `make test` runs
twelve gates in this order:

| Gate | What it proves |
|---|---|
| `tools/check_i18n.py` | every `T()` key exists in all five languages, placeholders match, the generated table is current |
| `tools/audit_i18n.py` | wrong script, ASCII punctuation glued to CJK, mixed bracket styles, terminology drift |
| `tools/check_help_align.py` | the `--help` option column starts at the same offset in all five languages |
| `tests/test_lang_names.py` | five language rows identical in every UI language; each report header names the active language |
| `tests/test_menu_order.py` | menu structure, language radio, localised bodies, counting unit, unknown-option handling |
| `tests/test_residue_report.py` | report structure and wording in all five languages |
| `tests/test_registry_policy.py` | nothing written by default; values deleted when returned to default |
| `tests/test_language.py` | command-line, environment and tray switching, live repaint, persistence |
| `tests/test_icons.py` | both icons and the version block are in the binary |
| `tests/test_tray_cleanup.py` | `--clean` removes this program's records and nothing else |
| `tests/test_smoke.py` | event path end to end on a real Explorer window, resource ceilings |
| `tests/test_robustness.py` | source contracts for the event-driven fixes; behavioural CLI checks |

Three are static checks; nine drive the built exe, so build first.
`test_smoke.py` opens and closes a real folder window and needs a desktop
session, not a service account.

A clean-checkout build catches files that exist only on the developer's machine,
most often a generated file that `.gitignore` swallowed:

```sh
git ls-files -z | xargs -0 -I{} cp --parents {} /tmp/ef11-check/
cd /tmp/ef11-check && make -B && make test
```

If a change affects the menu, tooltip or report window, regenerate the
screenshots before committing; they are in the documentation and carry the
version number in their headers.

## 3. Build the artefact

Two build paths exist and both must produce a working binary. The release is
built with whichever is available on the release machine, and the notes state
which one:

```bat
build.bat
```

or:

```sh
make -B
```

Use `make -B`, not `make`: the target depends on sources, and a stale
`dist\ExplorerF11.exe` from the previous version would otherwise be shipped. If
the linker reports `cannot open output file`, a running instance is holding the
exe — close it from the tray first.

Check the artefact before tagging:

```sh
./dist/ExplorerF11.exe --version          # ExplorerF11 X.Y.Z
sha256sum dist/ExplorerF11.exe
```

`--status` should also be run from this binary. Any test that changed state
during verification must be followed by a clean run before the release build is
copied.

## 4. Tag and publish

Push `main` first and wait for its CI to go green. Only then tag: a tag on a
commit that failed CI makes the release page point at a build nobody verified.

```sh
git push origin main
# wait for the CI run on this commit to complete successfully
git tag -a vX.Y.Z -m "ExplorerF11 X.Y.Z"
git push origin vX.Y.Z
```

The tag is `v` plus the SemVer number; the release title is `ExplorerF11 X.Y.Z`.
The tag push triggers a second CI run — confirm that one is green before
publishing the release itself.

Name the asset `ExplorerF11-<version>-win64.exe` and attach a `SHA256SUMS.txt`
containing:

```
<sha256>  ExplorerF11-<version>-win64.exe
```

Never upload a different binary under an existing tag. The release notes repeat
the CHANGELOG entry in user-facing language and state:

- what the binary is (single exe, no installer, no runtime), the architecture
  and the build path used;
- that it is **unsigned**, so SmartScreen will warn, and the SHA-256 to check;
- the residue policy in one sentence;
- links to `docs/USAGE.en.md`, `docs/USAGE.zh-CN.md` and the CHANGELOG.

The previous release is left in place as history; GitHub marks the newest one
as Latest.

## 5. Verify the published release

Download the published asset and run it. A release that has not been downloaded
once is untested.

```sh
sha256sum ExplorerF11-<version>-win64.exe
./ExplorerF11-<version>-win64.exe --version
./ExplorerF11-<version>-win64.exe --status
```

The hash must match both `SHA256SUMS.txt` and the value in the notes; the
version must match the tag. Fix a typo by editing the release notes, never the
tag. A bad binary gets a new patch version, with the old release marked as
superseded rather than deleted — a deleted release teaches nobody what
happened.
