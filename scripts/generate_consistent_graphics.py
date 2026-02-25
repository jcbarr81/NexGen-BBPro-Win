#!/usr/bin/env python3
"""Generate developer-only graphics with manifest-locked consistency checks."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.graphics_consistency import validate_image
from utils.graphics_style import (
    build_logo_prompt,
    build_ui_prompt,
    get_profile,
    load_manifest,
    prompt_fingerprint,
)
from utils.openai_client import client, get_client_status_message
from utils.team_loader import load_teams

try:
    from PIL import Image
except Exception:  # pragma: no cover - dependency guard
    Image = None  # type: ignore[assignment]
_LANCZOS = Image.Resampling.LANCZOS if Image is not None else 1


DEFAULT_RUN_ROOT = ROOT / "reports" / "graphics_runs"
DEFAULT_HANDOFF_DIR = ROOT / "reports" / "ui_handoff"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Developer-only OpenAI graphics generation with hard drift checks.",
    )
    parser.add_argument(
        "--manifest",
        default="config/graphics_style_manifest.json",
        help="Path to graphics style manifest.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional style profile id. Defaults to manifest default_profile.",
    )
    parser.add_argument(
        "--mode",
        choices=("logos", "ui", "all"),
        default="all",
        help="Which asset groups to generate.",
    )
    parser.add_argument(
        "--handoff-dir",
        default=str(DEFAULT_HANDOFF_DIR),
        help="UI handoff bundle directory for --mode ui/all.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional run output directory. Defaults to reports/graphics_runs/<timestamp>/.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override max retries from manifest openai.max_retries.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish passing outputs to logo/teams and assets/ui/generated.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any generated asset fails consistency checks.",
    )
    return parser


def _parse_square_size(token: str) -> int:
    parts = str(token or "").lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid OpenAI size token: {token}")
    width = int(parts[0])
    height = int(parts[1])
    if width != height:
        raise ValueError(f"Only square sizes are supported, got {token}")
    return width


def _save_b64_png(path: Path, b64_data: str, *, target_size: int) -> None:
    if Image is None:
        raise RuntimeError("Pillow is required for graphics generation.")
    raw = base64.b64decode(b64_data)
    with Image.open(BytesIO(raw)) as image:
        rgba = image.convert("RGBA")
        if rgba.size != (target_size, target_size):
            rgba = rgba.resize((target_size, target_size), _LANCZOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(path, format="PNG")


def _retry_suffix(findings: list[dict[str, Any]]) -> str:
    hints: list[str] = []
    for finding in findings:
        if finding.get("severity") != "error":
            continue
        code = str(finding.get("code", "")).strip()
        if code == "palette_drift":
            hints.append("Constrain colors closer to the specified palette tokens.")
        elif code == "phash_drift":
            hints.append("Match silhouette, composition, and icon balance closer to reference style.")
        elif code == "alpha_ratio_low":
            hints.append("Increase transparency around the emblem and remove solid background.")
        elif code == "edge_density_out_of_range":
            hints.append("Adjust line detail density to match expected style complexity.")
        elif code == "dimension_mismatch":
            hints.append("Return exactly the requested output dimensions.")
    return " ".join(hints) or "Tighten composition to match the manifest profile and golden references."


def _log_prompt(log_file: Path, payload: dict[str, Any]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _load_ui_bundles(handoff_dir: Path) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for path in sorted(handoff_dir.glob("*/metadata.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            bundles.append(payload)
    return bundles


def _generate_one(
    *,
    asset_id: str,
    category: str,
    prompt_builder,
    target_path: Path,
    manifest: dict[str, Any],
    profile_id: str,
    model: str,
    openai_size: str,
    openai_background: str,
    max_retries: int,
    prompts_log: Path,
) -> dict[str, Any]:
    corrective_suffix: str | None = None
    attempts: list[dict[str, Any]] = []
    target_size = _parse_square_size(openai_size)

    for attempt in range(max_retries + 1):
        prompt = prompt_builder(corrective_suffix=corrective_suffix)
        _log_prompt(
            prompts_log,
            {
                "asset_id": asset_id,
                "category": category,
                "attempt": attempt + 1,
                "prompt_fingerprint": prompt_fingerprint(prompt),
                "prompt": prompt,
            },
        )
        try:
            response = client.images.generate(  # type: ignore[union-attr]
                model=model,
                prompt=prompt,
                size=openai_size,
                background=openai_background,
            )
            b64 = response.data[0].b64_json
            _save_b64_png(target_path, b64, target_size=target_size)
            validation = validate_image(
                target_path,
                category=category,
                manifest=manifest,
                profile_id=profile_id,
            )
        except Exception as exc:
            validation = {
                "path": str(target_path),
                "category": category,
                "status": "fail",
                "metrics": {},
                "findings": [
                    {
                        "severity": "error",
                        "code": "generation_error",
                        "message": str(exc),
                    }
                ],
            }
        attempts.append(validation)
        if validation["status"] == "pass":
            break
        corrective_suffix = _retry_suffix(validation.get("findings", []))

    final = attempts[-1]
    return {
        "asset_id": asset_id,
        "category": category,
        "path": str(target_path),
        "status": final["status"],
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def _publish_assets(results: list[dict[str, Any]], *, category: str) -> int:
    published = 0
    if category == "logo":
        destination_root = ROOT / "logo" / "teams"
    else:
        destination_root = ROOT / "assets" / "ui" / "generated"
    destination_root.mkdir(parents=True, exist_ok=True)

    for result in results:
        if result.get("category") != category:
            continue
        if result.get("status") != "pass":
            continue
        source = Path(str(result.get("path")))
        if not source.exists():
            continue
        dest = destination_root / source.name
        shutil.copy2(source, dest)
        published += 1
    return published


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    profile_id, _ = get_profile(manifest, args.profile)

    if client is None:
        detail = get_client_status_message() or "OpenAI client is not configured."
        raise SystemExit(f"OpenAI client required for developer graphics pipeline. {detail}")

    openai_cfg = manifest["openai"]
    model = str(openai_cfg["model"])
    openai_size = str(openai_cfg["size"])
    openai_background = str(openai_cfg["background"])
    max_retries = int(args.max_retries if args.max_retries is not None else openai_cfg["max_retries"])

    if args.out_dir:
        run_dir = Path(args.out_dir)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
    else:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_dir = DEFAULT_RUN_ROOT / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    prompts_log = run_dir / "prompts.jsonl"
    results: list[dict[str, Any]] = []

    if args.mode in {"logos", "all"}:
        teams = load_teams("data/teams.csv")
        for team in teams:
            team_id = str(getattr(team, "team_id", "") or "").strip().lower()
            if not team_id:
                continue
            output_path = run_dir / "logos" / f"{team_id}.png"
            result = _generate_one(
                asset_id=team_id,
                category="logo",
                prompt_builder=lambda corrective_suffix, team=team: build_logo_prompt(
                    team,
                    manifest,
                    profile_id,
                    corrective_suffix=corrective_suffix,
                ),
                target_path=output_path,
                manifest=manifest,
                profile_id=profile_id,
                model=model,
                openai_size=openai_size,
                openai_background=openai_background,
                max_retries=max_retries,
                prompts_log=prompts_log,
            )
            results.append(result)

    if args.mode in {"ui", "all"}:
        handoff_dir = Path(args.handoff_dir)
        if not handoff_dir.is_absolute():
            handoff_dir = ROOT / handoff_dir
        if not handoff_dir.exists():
            raise SystemExit(
                f"UI handoff directory not found: {handoff_dir}. "
                "Run scripts/build_ui_handoff.py first."
            )
        bundles = _load_ui_bundles(handoff_dir)
        for bundle in bundles:
            screen_id = str(bundle.get("screen_id", "")).strip()
            if not screen_id:
                continue
            output_path = run_dir / "ui" / f"{screen_id}.png"
            result = _generate_one(
                asset_id=screen_id,
                category="ui",
                prompt_builder=lambda corrective_suffix, bundle=bundle: build_ui_prompt(
                    bundle,
                    manifest,
                    profile_id,
                    corrective_suffix=corrective_suffix,
                ),
                target_path=output_path,
                manifest=manifest,
                profile_id=profile_id,
                model=model,
                openai_size=openai_size,
                openai_background=openai_background,
                max_retries=max_retries,
                prompts_log=prompts_log,
            )
            results.append(result)

    error_count = 0
    for result in results:
        latest = result.get("attempts", [])[-1] if result.get("attempts") else {}
        error_count += len([item for item in latest.get("findings", []) if item.get("severity") == "error"])
    status = "pass" if error_count == 0 else "fail"

    published = {"logos": 0, "ui": 0}
    if args.publish:
        published["logos"] = _publish_assets(results, category="logo")
        published["ui"] = _publish_assets(results, category="ui")

    report = {
        "status": status,
        "error_count": error_count,
        "developer_only": True,
        "mode": args.mode,
        "profile": profile_id,
        "manifest_path": str(args.manifest),
        "run_dir": str(run_dir),
        "model": model,
        "openai_size": openai_size,
        "openai_background": openai_background,
        "max_retries": max_retries,
        "published": published,
        "results": results,
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    (run_dir / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "developer_only": True,
                "manifest_path": str(args.manifest),
                "profile": profile_id,
                "mode": args.mode,
                "model": model,
                "openai_size": openai_size,
                "openai_background": openai_background,
                "max_retries": max_retries,
                "strict": bool(args.strict),
                "publish": bool(args.publish),
                "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Generation status: {status} (errors: {error_count})")
    print(f"Run directory: {run_dir}")

    if args.strict and status != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
