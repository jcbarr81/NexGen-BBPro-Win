# Developer-Only Graphics Consistency Pipeline

This workflow is internal tooling for developers redesigning UI visuals.

- It is not player-facing.
- It is not exposed in owner/admin/game menus.
- It does not change runtime gameplay flows.

## What It Delivers

1. UI handoff bundle export per top-level screen class.
2. OpenAI-driven generation for logos/UI graphics using a locked style profile.
3. Consistency validation against manifest thresholds and golden references.
4. Run artifacts for reproducibility (`prompts.jsonl`, `run_manifest.json`, `validation.json`).

## Files and Scripts

- Manifest: `config/graphics_style_manifest.json`
- Handoff export: `scripts/build_ui_handoff.py`
- Generation: `scripts/generate_consistent_graphics.py`
- Validation only: `scripts/validate_graphics_consistency.py`
- Style helpers: `utils/graphics_style.py`
- Validation engine: `utils/graphics_consistency.py`
- Golden references: `assets/graphics/golden/`

## Typical Workflow

1. Export UI handoff bundles:

```powershell
.\.venv2\Scripts\python.exe scripts\build_ui_handoff.py --include-source
```

2. Run generation + validation (strict):

```powershell
.\.venv2\Scripts\python.exe scripts\generate_consistent_graphics.py --mode all --strict
```

3. Optional validation-only pass:

```powershell
.\.venv2\Scripts\python.exe scripts\validate_graphics_consistency.py --input-dir reports/graphics_runs/<timestamp> --strict
```

4. Publish only validated outputs:

```powershell
.\.venv2\Scripts\python.exe scripts\generate_consistent_graphics.py --mode all --strict --publish
```

## Notes

- OpenAI API access is required for generation runs.
- Consistency comes from profile locks + golden references + hard checks.
- The pipeline can fail intentionally to block drift before assets are adopted.

