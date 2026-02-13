# Release Checklist

1. Update `VERSION` to the new release number.
2. Capture updates while developing (repeat as needed):
```powershell
.\.venv2\Scripts\python.exe scripts\add_release_note.py "Describe the change here"
```
3. Clean previous build outputs (optional but recommended):
```powershell
Remove-Item -Recurse -Force build, dist
```
4. Build the EXE + installer (updates `packaging/NexGen-BBPro.iss` and appends `release_notes.md`):
```powershell
.\.venv2\Scripts\python.exe scripts\build_release.py --clean
```
5. Smoke test by launching the app, creating a new league, and confirming data is written to `%LOCALAPPDATA%\NexGen-BBPro\data`.
6. Run targeted tests:
```powershell
.\.venv2\Scripts\python.exe -m pytest tests\test_avatar_generator.py tests\test_avatar_generator_openai.py
```
7. Commit changes, including `VERSION`, `packaging/NexGen-BBPro.iss`, and any code updates for the release.
8. Tag and publish the release using the same version number.
