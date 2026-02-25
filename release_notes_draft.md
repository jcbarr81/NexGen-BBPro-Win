## v5.0.110
- Hardened backlog item 19 with automated tutorial/manual/doc consistency validation via `scripts/validate_help_surface.py`.
- Wired help-surface validation into `scripts/build_release.py` as a default pre-build gate (with `--skip-help-surface-validation` escape hatch and configurable report output path).
- Added help-surface validation report artifact output to `reports/release_validation/help_surface_validation.json`.
- Updated release process docs/checklists (`RELEASE.md`, `docs/post_installer_ui_checklist.md`) to include the automated validation step and artifact check.
- Fixed owner guide wording to match current change-request packaging (`ZIP bundle`).
- Added regression coverage in `tests/test_validate_help_surface.py` and expanded `tests/test_build_release.py` gating assertions.

## v5.0.111
- Implemented backlog item 18 as developer-only tooling: added `scripts/build_ui_handoff.py` to export per-screen handoff bundles under `reports/ui_handoff/`.
- Added manifest-driven graphics style controls in `config/graphics_style_manifest.json` with profile tokens, OpenAI defaults, validation thresholds, and golden reference mapping.
- Added developer OpenAI generation and gating workflows via `scripts/generate_consistent_graphics.py` and `scripts/validate_graphics_consistency.py` with strict failure support.
- Added consistency utility modules `utils/graphics_style.py` and `utils/graphics_consistency.py`, plus prompt override support in `utils/logo_generator.generate_team_logos`.
- Added golden baseline assets under `assets/graphics/golden/` and developer documentation in `docs/graphics_consistency_pipeline.md`.
- Updated `docs/ui_graphics_handoff_kit.md` and marked backlog item 18 complete in `docs/future_work.md` with explicit developer-only boundary.
- Added regression coverage for manifest validation, handoff export, generation flow, consistency checks, and runtime boundary protection.

## v5.0.112
- Tightened developer UI graphics prompt constraints to explicitly ban fake UI controls/text overlays and glow haze in generated assets.
- Hardened `retro_modern_v1` negative constraints and lighting rules in `config/graphics_style_manifest.json`.
- Increased UI validation strictness (`edge_density_min`) to reject overly soft/blurred outputs that drift from usable panel art.
