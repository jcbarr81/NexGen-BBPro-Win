# AGENTS instructions

## Testing
- Run targeted tests using `pytest` before commits
- Virtual envrionment exists in .venv, use this interpreter

## Development guidelines
- Use the .venv2 environment for python
- Use `rg` for searching the repository.
- Follow PEP8 style guidelines.
- Increment versoin in VERSION file for every change that is made
- Make sure that the version in the .iss file matches the VERSION
- Add changes to the releas_notes_draft file as they are made and versions are bumped
- Remember to create tutorials/guides and add them to the menu for new features
- To build release run: 
    .\.venv2\Scripts\python.exe scripts\build_release.py --clean
