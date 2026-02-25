"""Helpers for developer-only graphics style manifests and prompt assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "config" / "graphics_style_manifest.json"
REQUIRED_MANIFEST_KEYS = {
    "manifest_version",
    "default_profile",
    "openai",
    "profiles",
    "validation",
    "golden_set",
}
REQUIRED_PROFILE_KEYS = {
    "style_anchor",
    "negative_constraints",
    "palette_tokens",
    "shape_language",
    "lighting_rules",
}


def _validate_hex_token(value: str) -> bool:
    token = str(value or "").strip()
    if len(token) != 7 or not token.startswith("#"):
        return False
    try:
        int(token[1:], 16)
    except ValueError:
        return False
    return True


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def default_manifest_path() -> Path:
    """Return the default developer style manifest path."""

    return DEFAULT_MANIFEST_PATH


def resolve_manifest_path(path: str | Path | None = None) -> Path:
    """Resolve a manifest path, defaulting to config/graphics_style_manifest.json."""

    if path is None:
        return default_manifest_path()
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    return resolved


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the graphics style manifest."""

    manifest_path = resolve_manifest_path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Graphics style manifest not found: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _ensure(isinstance(payload, dict), "Manifest root must be a JSON object.")

    missing = sorted(REQUIRED_MANIFEST_KEYS - set(payload))
    _ensure(
        not missing,
        f"Manifest missing required keys: {', '.join(missing)}",
    )

    _ensure(
        isinstance(payload["manifest_version"], str) and payload["manifest_version"].strip(),
        "manifest_version must be a non-empty string.",
    )

    default_profile = payload["default_profile"]
    _ensure(
        isinstance(default_profile, str) and default_profile.strip(),
        "default_profile must be a non-empty string.",
    )

    openai_cfg = payload["openai"]
    _ensure(isinstance(openai_cfg, dict), "openai must be an object.")
    for key in ("model", "size", "background", "max_retries"):
        _ensure(key in openai_cfg, f"openai.{key} is required.")
    _ensure(
        isinstance(openai_cfg["max_retries"], int) and openai_cfg["max_retries"] >= 0,
        "openai.max_retries must be a non-negative integer.",
    )

    profiles = payload["profiles"]
    _ensure(isinstance(profiles, dict) and profiles, "profiles must be a non-empty object.")
    _ensure(default_profile in profiles, "default_profile must exist in profiles.")

    for profile_id, profile in profiles.items():
        _ensure(isinstance(profile, dict), f"profile '{profile_id}' must be an object.")
        missing_profile = sorted(REQUIRED_PROFILE_KEYS - set(profile))
        _ensure(
            not missing_profile,
            f"profile '{profile_id}' missing keys: {', '.join(missing_profile)}",
        )
        palette = profile.get("palette_tokens")
        _ensure(
            isinstance(palette, list) and palette,
            f"profile '{profile_id}' palette_tokens must be a non-empty list.",
        )
        for token in palette:
            _ensure(
                _validate_hex_token(str(token)),
                f"profile '{profile_id}' has invalid palette token: {token}",
            )

        for list_key in ("negative_constraints", "shape_language", "lighting_rules"):
            value = profile.get(list_key)
            _ensure(
                isinstance(value, list),
                f"profile '{profile_id}' {list_key} must be a list.",
            )

    validation = payload["validation"]
    _ensure(isinstance(validation, dict), "validation must be an object.")
    for category in ("logo", "ui"):
        _ensure(
            category in validation and isinstance(validation[category], dict),
            f"validation.{category} must be an object.",
        )
        category_cfg = validation[category]
        for key in (
            "width",
            "height",
            "require_alpha",
            "min_transparent_ratio",
            "palette_delta_max",
            "phash_max_distance",
            "edge_density_min",
            "edge_density_max",
        ):
            _ensure(
                key in category_cfg,
                f"validation.{category}.{key} is required.",
            )

    golden_set = payload["golden_set"]
    _ensure(isinstance(golden_set, list), "golden_set must be a list.")
    for item in golden_set:
        _ensure(isinstance(item, dict), "Each golden_set entry must be an object.")
        for key in ("id", "category", "path", "profile"):
            _ensure(key in item, f"golden_set entry missing key: {key}")
        _ensure(
            item["category"] in {"logo", "ui"},
            f"golden_set entry has invalid category: {item['category']}",
        )
        _ensure(
            item["profile"] in profiles,
            f"golden_set entry references unknown profile: {item['profile']}",
        )
    return payload


def get_profile(manifest: dict[str, Any], profile_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """Return ``(profile_id, profile_data)`` from a manifest."""

    selected = profile_id or str(manifest["default_profile"])
    profiles = manifest["profiles"]
    if selected not in profiles:
        raise ValueError(f"Unknown style profile: {selected}")
    return selected, profiles[selected]


def compose_negative_constraints(profile: dict[str, Any]) -> str:
    """Render profile negative constraints as a compact sentence."""

    constraints = [str(item).strip() for item in profile.get("negative_constraints", []) if str(item).strip()]
    if not constraints:
        return ""
    return "Avoid: " + "; ".join(constraints) + "."


def build_logo_prompt(
    team: object,
    manifest: dict[str, Any],
    profile_id: str | None = None,
    *,
    corrective_suffix: str | None = None,
) -> str:
    """Build a manifest-locked logo prompt for a team."""

    _, profile = get_profile(manifest, profile_id)
    city = str(getattr(team, "city", "") or "").strip()
    name = str(getattr(team, "name", "") or "").strip()
    team_id = str(getattr(team, "team_id", "") or "").strip().upper()
    primary = str(getattr(team, "primary_color", "") or "").strip()
    secondary = str(getattr(team, "secondary_color", "") or "").strip()

    palette = ", ".join(profile.get("palette_tokens", []))
    shapes = ", ".join(str(item) for item in profile.get("shape_language", []))
    lighting = ", ".join(str(item) for item in profile.get("lighting_rules", []))
    negative = compose_negative_constraints(profile)
    correction = str(corrective_suffix or "").strip()

    parts = [
        str(profile.get("style_anchor", "")).strip(),
        f"Create a baseball team logo for {city} {name}.",
        f"Team id/initial cue: {team_id}.",
        (
            "Primary design colors must prioritize "
            f"{primary or 'team primary'} and {secondary or 'team secondary'}."
        ),
        f"Style palette tokens: {palette}.",
        f"Shape language: {shapes}.",
        f"Lighting rules: {lighting}.",
        "Return a clean emblem suitable for UI placement with transparent background.",
        negative,
    ]
    if correction:
        parts.append(f"Correction for this retry: {correction}")
    return " ".join(part for part in parts if part)


def build_ui_prompt(
    screen_bundle: dict[str, Any],
    manifest: dict[str, Any],
    profile_id: str | None = None,
    *,
    corrective_suffix: str | None = None,
) -> str:
    """Build a manifest-locked UI graphic prompt for one screen bundle."""

    _, profile = get_profile(manifest, profile_id)
    class_name = str(screen_bundle.get("class_name", "")).strip()
    relative_file = str(screen_bundle.get("relative_path", "")).strip()
    screenshot_hint = str(screen_bundle.get("screenshot_path", "")).strip()

    palette = ", ".join(profile.get("palette_tokens", []))
    shapes = ", ".join(str(item) for item in profile.get("shape_language", []))
    lighting = ", ".join(str(item) for item in profile.get("lighting_rules", []))
    negative = compose_negative_constraints(profile)
    correction = str(corrective_suffix or "").strip()

    parts = [
        str(profile.get("style_anchor", "")).strip(),
        "Generate a UI background/hero graphic for this PyQt screen redesign handoff.",
        "This must be background/panel art only, not a rendered screenshot or fake UI mockup.",
        f"Screen class: {class_name}.",
        f"Source file: {relative_file}.",
        (
            f"Screenshot placeholder path: {screenshot_hint}."
            if screenshot_hint
            else "Screenshot placeholder is not yet provided."
        ),
        f"Palette tokens: {palette}.",
        f"Shape language: {shapes}.",
        f"Lighting rules: {lighting}.",
        (
            "Do not render text, labels, letters, numbers, close buttons, tabs, input fields, "
            "or literal window controls."
        ),
        "Do not add glow haze or bloom fog around edges.",
        "Output should be clean, layered, readable, and suitable for desktop UI integration.",
        negative,
    ]
    if correction:
        parts.append(f"Correction for this retry: {correction}")
    return " ".join(part for part in parts if part)


def prompt_fingerprint(prompt: str) -> str:
    """Return a short stable fingerprint for prompt logging."""

    import hashlib

    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
