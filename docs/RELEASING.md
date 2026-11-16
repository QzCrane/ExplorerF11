# Releasing

A release is a tagged commit, a binary built from that commit, and a checksum
published alongside it. Once an artefact is public it cannot be corrected in
place — only superseded — so the checks below happen before the tag, not after.

## Running it

This checklist is executed by `tools/release.py`:

```sh
make release                  # build, gate, tag, publish, verify
make release ARGS=--dry-run   # build, gate and capture, then stop before commit
make release ARGS="--from tag"   # re-enter after an interruption
```

Its stages are `preflight, build, sign, facts, gates, screenshots, notes,
commit, push, ci, tag, package, publish, verify, remote, done` — in that order,
which is the order of the sections below. Each stage is idempotent: it inspects
the world before acting, so re-running after a failure is safe and `--from`
resumes rather than repeats. A failure stops the run at that stage and prints
the resume command.

Two of those stages exist because of specific incidents. `notes` renders the
release body from this build's measurements — the hash is substituted, never
typed — and commits it before the tag, so the tagged tree contains the text the
release page shows. `remote` compares all four GitHub-only surfaces against
`release_facts.py` with `tools/check_github_sync.py`.

`gates` does not run anything of its own. `facts` has to run all fourteen
commands already, because it derives the assertion count from them, and it
records the fingerprint of the tree it ran against (`tools/treefp.py`). The
`gates` stage recomputes that fingerprint and reuses the run when it matches;
anything that changes a byte — including a regenerated screenshot — invalidates
it and the suite runs again. Same bytes, same questions, same answer; running
it twice only made the pipeline slower.

The rest of this document is why each stage exists and what it refuses to
accept. Read it before changing the script.

## 0. One source of truth for the numbers

`tools/release_facts.py` is the only authoritative copy of every number that
appears in more than one place: version, asset name, checksum filename, gate and
assertion counts, binary size and resource ceilings. `tools/measurement.json`
holds the raw sample behind each measured value. Four tools keep the two in step
with reality:

| Command | Role |
|---|---|
| `python tools/bump_version.py X.Y.Z` | rewrite every version-derived string, seed the new CHANGELOG entry |
| `make -B` | rebuild the release exe |
| `make refresh-facts` | re-run all gates, re-measure, rewrite facts and manifest, then verify consistency |
| `python tools/check_release_facts.py` | gate: fail if any current document or build file disagrees with the facts |

Never hand-edit a version, filename, gate count or measured figure in a
document. Edit the source of truth, refresh, and commit all three together.
Historical CHANGELOG sections are exempt: they describe the binaries of their
day, and the gate deliberately leaves them alone.

The checksum file is named `SHA256SUMS.txt`. GNU `sha256sum` does not prescribe
a manifest filename — `sha256sum -c` accepts any name — it prescribes the line
format: `digest`, one separator space, one mode flag (`' '` text or `'*'`
binary), then the filename. `SHA256SUMS.txt` follows the Debian/kernel
`SHA256SUMS` convention with a `.txt` suffix so Windows users can open it;
`sha256sum -c SHA256SUMS.txt` works unchanged. Do **not** name the file after
the digest: that is content-addressed storage, where a resolver maps hash to
content, and offers no benefit on a release page where the digest must be
paired with a readable asset name.

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
fourteen gates in this order:

| Gate | What it proves |
|---|---|
| `tools/check_i18n.py` | every `T()` key exists in all five languages, placeholders match, the generated table is current |
| `tools/audit_i18n.py` | wrong script, ASCII punctuation glued to CJK, mixed bracket styles, terminology drift |
| `tools/check_help_align.py` | the `--help` option column starts at the same offset in all five languages |
| `tools/check_release_facts.py` | every release-facing number matches `tools/release_facts.py` and `tools/measurement.json` |
| `tools/check_gate_inventory.py` | every gate is classified CI or shell-dependent, CI runs exactly its share, and both tables below list the same fourteen gates |
| `tests/test_lang_names.py` | five language rows identical in every UI language; each report header names the active language |
| `tests/test_menu_order.py` | menu structure, language radio, localised bodies, counting unit, unknown-option handling |
| `tests/test_residue_report.py` | report structure and wording in all five languages |
| `tests/test_registry_policy.py` | nothing written by default; values deleted when returned to default |
| `tests/test_language.py` | command-line, environment and tray switching, live repaint, persistence |
| `tests/test_icons.py` | both icons and the version block are in the binary |
| `tests/test_tray_cleanup.py` | `--clean` removes this program's records and nothing else |
| `tests/test_smoke.py` | event path end to end on a real Explorer window, resource ceilings |
| `tests/test_robustness.py` | source contracts for the event-driven fixes; behavioural CLI checks |

`make refresh-facts` runs this same list, one command at a time, and records the
result with a fingerprint of the tree; `make test` runs it as one list. They
share the Makefile recipe, so the two can never disagree about what the gates
are. Run `make test` when you want to see it; the release pipeline only needs the
record.

The suites wait for observations, never for a stopwatch: the process handle
signals exit, the window appears, the menu command's effect is visible in the
registry, the report's body carries a new timestamp. `tools/win32util.py` holds
those primitives. A suite that needs a sleep has found a state it cannot
observe, and that is worth fixing rather than papering over — the fixed sleeps
were 46 of the suite's original 62 s.

Four are static checks; nine drive the built exe, so build first.
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

Signing, when it is enabled, happens here and not later. A signature rewrites the
image, so a byte count, KiB figure or SHA-256 measured before it would describe a
file that is never uploaded. `EF11_SIGN_CMD` receives the image path in
`EF11_FILE` and must rewrite it in place; the release script fails if the
security directory is still empty afterwards.
[docs/SIGNING.md](SIGNING.md) has the costs, the eligibility rules, and the one
thing a certificate does not buy: a new release still warns until its publisher
reputation accumulates.

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
Repository topics live outside git and are named separately:

```sh
gh api -X PUT repos/QzCrane/ExplorerF11/topics \
  -f 'names[]=cpp' -f 'names[]=cpp23' -f 'names[]=file-explorer' \
  -f 'names[]=i18n' -f 'names[]=mingw-w64' -f 'names[]=performance' \
  -f 'names[]=shell-hook' -f 'names[]=tray-icon' \
  -f 'names[]=win32' -f 'names[]=windows-11'
```

The workflow listens on `push` to `main` only, so pushing a tag does not start a
second run. The main-branch run on the tagged commit is the gate: confirm it is
green before publishing the release itself.

`gh release create` takes each asset's name from the local file's basename; it
has no display-name override. Copy the exe to the final asset name before
uploading, or the checksum and the docs will point at a file that does not exist
on the release page.

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
version must match the tag. A typo in the notes is fixed by editing the notes.

A bad binary gets a new patch version, with the old release marked as
superseded rather than deleted — a deleted release teaches nobody what
happened.

The tag stays where it is. Commits that land after a release are normal — prose,
screenshots, CI tweaks, build plumbing — and `make check-remote` accepts them.
Moving a public tag is a cost every existing clone has to reconcile, and v1.0.4
paid it five times for changes that were never part of the binary.

The source tree is the exception. If `src/` changes after the tag, the tagged
tree no longer holds the code the notes describe: that is a new patch version
under its own tag, not a re-point.

A re-point is reserved for `src/` moving without the binary moving — a comment,
a rename with no codegen effect — and the ruleset below makes it a deliberate
act rather than an accident. Prove the binary first, then lift the rule, move
the tag, put the rule back:

```sh
make -B && sha256sum dist/ExplorerF11.exe   # must equal the published digest
gh api repos/QzCrane/ExplorerF11/rulesets --jq '.[]|select(.target=="tag").id'
gh api -X DELETE repos/QzCrane/ExplorerF11/rulesets/<id>
git tag -f -a vX.Y.Z -m "ExplorerF11 X.Y.Z (re-pointed: src/ comment only)"
git push --force origin vX.Y.Z
gh api -X POST repos/QzCrane/ExplorerF11/rulesets --input - <<'JSON'
{"name":"published tags do not move","target":"tag","enforcement":"active",
 "conditions":{"ref_name":{"include":["refs/tags/v*"],"exclude":[]}},
 "rules":[{"type":"deletion"},{"type":"non_fast_forward"}]}
JSON
```

Never upload a different binary under an existing tag.

Two rulesets enforce this where the push happens, not in this document:

| Ruleset | Applies to | Rejects |
|---|---|---|
| `published tags do not move` | `v*` tags | deletion, non-fast-forward update |
| `main is append-only` | `main` | deletion, non-fast-forward push |

`make check-remote` requires both to be active, because a rule nobody checks is
a rule that gets removed by accident. Two things to know before editing them: a
push issued in the first seconds after creating a ruleset can still succeed, so
an immediate test is not evidence that the rule is wrong; and while the tag
ruleset is in place, moving a tag at all means deleting and recreating it — the
intended amount of friction for an operation this document says should happen
once in a project's life, if ever.

## 6. Confirm nothing on GitHub drifted

Five facts live only on GitHub and are invisible to `git status`: the tag's tree,
the release body, the uploaded assets, the repository description and the rules
that guard the published refs. The first four have drifted before — a body copied
from the previous release, a tag left one documentation commit behind, a
description still quoting an old binary size — and each time a reader found it
first. Check them mechanically:

```sh
make check-remote        # python tools/check_github_sync.py
```

It fails unless the tag is an ancestor of `HEAD` with `src/` unchanged since,
the asset's digest matches `SHA256SUMS.txt`, the notes quote this build's
version and byte count, the description quotes this build's size, and both
rulesets are active. Run it before announcing a release and again after any commit that lands
once one is published; documentation commits pass, a commit that touches `src/`
fails and means the release is due a new version.
