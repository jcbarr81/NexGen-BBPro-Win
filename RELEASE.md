# Release Checklist

1. Update `VERSION` to the new release number.
2. Clean previous build outputs (optional but recommended):
```powershell
Remove-Item -Recurse -Force build, dist
```
3. Build the EXE:
```powershell
.\.venv\Scripts\python.exe build_exe.py
```
4. Update the installer version in `packaging/NexGen-BBPro.iss` to match `VERSION`.
5. Build the installer with Inno Setup.
6. Smoke test by launching the app, creating a new league, and confirming data is written to `%LOCALAPPDATA%\NexGen-BBPro\data`.
7. Run targeted tests:
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_avatar_generator.py tests\test_avatar_generator_openai.py
```
8. Commit changes, including `VERSION`, `packaging/NexGen-BBPro.iss`, and any code updates for the release.
9. Tag and publish the release using the same version number.
