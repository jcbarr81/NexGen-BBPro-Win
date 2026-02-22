# AGENTS instructions

## Testing
- Run targeted tests using `pytest` before commits
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
