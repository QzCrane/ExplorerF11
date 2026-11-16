# Summary

<!-- One paragraph: what breaks or what is missing without this change. -->

## Kind of change

- [ ] Behaviour change (the tool does something different)
- [ ] Translation (a string, a term, a punctuation rule)
- [ ] Documentation only
- [ ] Build, CI or test infrastructure

## The three invariants

Every pull request has to keep these; a change that breaks one needs to say why
the invariant itself should change. See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

- [ ] **No polling.** Still driven by the shell hook or a WinEvent hook.
- [ ] **No injection.** Messages to other processes only — no DLL, no memory
      patching, no remote thread.
- [ ] **No unremovable residue.** A new registry value, file or cache entry has
      an entry in `src/residue.cpp`, a row in `docs/RESIDUE.md`, and is removed
      by `--clean`.

## Verification

```
make            # or build.bat
make test       # 11 gates: 3 static checks + 8 suites
```

- [ ] `make test` passes locally
- [ ] New or changed user-visible strings exist in all five languages, and
      `python tools\sync_i18n.py` has been run
- [ ] `CHANGELOG.md` has an entry under `Unreleased` if a user can see the change
- [ ] Screenshots regenerated if the menu, the tooltip or the report window changed

## Notes for the reviewer

<!-- Anything a reader cannot infer from the diff: a Win32 quirk, a rejected
     alternative, a number that was measured rather than guessed. -->
