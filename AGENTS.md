# AGENTS instructions

> **New here? Read `docs/CODEX_HANDOFF.md` first.** It is the full onboarding map:
> architecture, how to run/test/deploy, the current state, where development was
> left off, and the traps that will otherwise cost you hours.

## Testing
- Run targeted tests using `pytest` before commits.
- **The whole suite is only reliably green via `python scripts/run_tests_isolated.py`**
  (per-file process isolation). A single `pytest` run over everything shows ~50
  cross-file *pollution* failures that are NOT real bugs — see
  `docs/CODEX_HANDOFF.md` §5. Every file passes on its own.
- Run with `PYTHONHASHSEED=0`; never run sims/tests against a real user league,
  and clean stray data with `git clean -fdq data/leagues` (not just `git checkout`).
- Virtual envrionment exists in .venv, use this interpreter

## Development guidelines
- Use the .venv2 environment for python
- Use `rg` for searching the repository.
- Follow PEP8 style guidelines.
- Increment version in `VERSION` for code/behavior/build changes.
- Documentation-only changes do not require version bumps.
- When version is bumped, make sure the version in the `.iss` file matches `VERSION`.
- Add changes to the releas_notes_draft file as they are made and versions are bumped
- Add all backlog requests/items to `docs/future_work.md`.
- Remember to create tutorials/guides and add them to the menu for new features
- To build release run: 
    .\.venv2\Scripts\python.exe scripts\build_release.py --clean

## Versioning Policy (SemVer)
- Default: bump PATCH (`X.Y.Z -> X.Y.(Z+1)`) for bug fixes, installer/build fixes, tests, and small UX tweaks.
- Documentation-only changes do not require a version bump.
- Bump MINOR (`X.Y.Z -> X.(Y+1).0`) for backward-compatible, user-facing feature sets that are complete enough to announce.
- Bump MAJOR (`X.Y.Z -> (X+1).0.0`) for breaking changes, migrations, incompatible data/model changes, or major product shifts.
- If uncertain between PATCH and MINOR, ask before bumping.
- Never bump MAJOR without explicit confirmation.
