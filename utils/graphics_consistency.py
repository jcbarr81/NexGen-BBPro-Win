"""Consistency checks for developer-only generated graphics assets."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    from PIL import Image
except Exception:  # pragma: no cover - dependency guard
    Image = None  # type: ignore[assignment]

from utils.graphics_style import ROOT, get_profile


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    token = value.strip().lstrip("#")
    if len(token) != 6:
        raise ValueError(f"Invalid hex token: {value}")
    return tuple(int(token[idx : idx + 2], 16) for idx in (0, 2, 4))


def _load_rgba(path: Path) -> np.ndarray:
    if Image is None:
        raise RuntimeError("Pillow is required for graphics consistency checks.")
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        return np.array(rgba, dtype=np.uint8)


def _edge_density(gray: np.ndarray) -> float:
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    inner = np.zeros_like(gray, dtype=np.float32)
    inner[:-1, :-1] = np.hypot(gx[:-1, :], gy[:, :-1])
    return float(np.mean(inner > 18.0))


def _dct_basis(size: int) -> np.ndarray:
    basis = np.zeros((size, size), dtype=np.float64)
    factor = math.pi / (2.0 * size)
    scale0 = math.sqrt(1.0 / size)
    scale = math.sqrt(2.0 / size)
    for k in range(size):
        alpha = scale0 if k == 0 else scale
        for n in range(size):
            basis[k, n] = alpha * math.cos((2 * n + 1) * k * factor)
    return basis


_DCT32 = _dct_basis(32)
_LANCZOS = Image.Resampling.LANCZOS if Image is not None else 1


def _phash_from_rgba(rgba: np.ndarray) -> int:
    if Image is None:
        raise RuntimeError("Pillow is required for graphics consistency checks.")
    image = Image.fromarray(rgba, mode="RGBA").convert("L").resize((32, 32), _LANCZOS)
    matrix = np.array(image, dtype=np.float64)
    dct = _DCT32 @ matrix @ _DCT32.T
    low = dct[:8, :8]
    median = float(np.median(low[1:, 1:]))
    bits = (low > median).astype(np.uint8).flatten()
    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def _hamming_distance(lhs: int, rhs: int) -> int:
    return int((lhs ^ rhs).bit_count())


def _palette_delta(rgba: np.ndarray, palette_tokens: list[str]) -> float:
    rgb = rgba[:, :, :3].reshape(-1, 3).astype(np.float32)
    alpha = rgba[:, :, 3].reshape(-1)
    opaque = rgb[alpha > 16]
    if opaque.size == 0:
        return 255.0
    # Sample at most 4k pixels to keep checks fast.
    if opaque.shape[0] > 4096:
        step = max(1, opaque.shape[0] // 4096)
        opaque = opaque[::step]
    palette = np.array([_hex_to_rgb(token) for token in palette_tokens], dtype=np.float32)
    distances = np.linalg.norm(opaque[:, None, :] - palette[None, :, :], axis=2)
    return float(np.mean(np.min(distances, axis=1)))


def _golden_refs_for(
    manifest: dict[str, Any],
    *,
    category: str,
    profile_id: str,
) -> list[Path]:
    refs: list[Path] = []
    for item in manifest.get("golden_set", []):
        if (
            item.get("category") == category
            and item.get("profile") == profile_id
        ):
            refs.append(ROOT / str(item.get("path")))
    return refs


def validate_image(
    path: str | Path,
    *,
    category: str,
    manifest: dict[str, Any],
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Validate a single image path and return finding details."""

    asset_path = Path(path)
    selected_profile, profile = get_profile(manifest, profile_id)
    cfg = manifest["validation"][category]

    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    try:
        rgba = _load_rgba(asset_path)
    except Exception as exc:
        findings.append(
            {
                "severity": "error",
                "code": "image_unreadable",
                "message": f"Unable to read image: {exc}",
            }
        )
        return {
            "path": str(asset_path),
            "category": category,
            "status": "fail",
            "metrics": metrics,
            "findings": findings,
        }

    height, width = rgba.shape[0], rgba.shape[1]
    metrics["width"] = width
    metrics["height"] = height
    if width != int(cfg["width"]) or height != int(cfg["height"]):
        findings.append(
            {
                "severity": "error",
                "code": "dimension_mismatch",
                "message": (
                    f"Expected {cfg['width']}x{cfg['height']} but found "
                    f"{width}x{height}"
                ),
            }
        )

    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    transparent_ratio = float(np.mean(alpha < 0.10))
    metrics["transparent_ratio"] = transparent_ratio
    if bool(cfg["require_alpha"]):
        if transparent_ratio < float(cfg["min_transparent_ratio"]):
            findings.append(
                {
                    "severity": "error",
                    "code": "alpha_ratio_low",
                    "message": (
                        f"Transparent ratio {transparent_ratio:.3f} below required "
                        f"{cfg['min_transparent_ratio']:.3f}"
                    ),
                }
            )

    palette_delta = _palette_delta(rgba, list(profile["palette_tokens"]))
    metrics["palette_delta"] = palette_delta
    if palette_delta > float(cfg["palette_delta_max"]):
        findings.append(
            {
                "severity": "error",
                "code": "palette_drift",
                "message": (
                    f"Palette delta {palette_delta:.2f} exceeds max "
                    f"{cfg['palette_delta_max']:.2f}"
                ),
            }
        )

    gray = (
        0.2126 * rgba[:, :, 0].astype(np.float32)
        + 0.7152 * rgba[:, :, 1].astype(np.float32)
        + 0.0722 * rgba[:, :, 2].astype(np.float32)
    )
    density = _edge_density(gray)
    metrics["edge_density"] = density
    if density < float(cfg["edge_density_min"]) or density > float(cfg["edge_density_max"]):
        findings.append(
            {
                "severity": "error",
                "code": "edge_density_out_of_range",
                "message": (
                    f"Edge density {density:.4f} outside "
                    f"[{cfg['edge_density_min']:.4f}, {cfg['edge_density_max']:.4f}]"
                ),
            }
        )

    try:
        image_hash = _phash_from_rgba(rgba)
        golden_distances: list[int] = []
        for ref_path in _golden_refs_for(
            manifest,
            category=category,
            profile_id=selected_profile,
        ):
            if not ref_path.exists():
                continue
            ref_hash = _phash_from_rgba(_load_rgba(ref_path))
            golden_distances.append(_hamming_distance(image_hash, ref_hash))
        if golden_distances:
            min_distance = min(golden_distances)
            metrics["phash_distance_min"] = min_distance
            if min_distance > int(cfg["phash_max_distance"]):
                findings.append(
                    {
                        "severity": "error",
                        "code": "phash_drift",
                        "message": (
                            f"pHash distance {min_distance} exceeds max "
                            f"{cfg['phash_max_distance']}"
                        ),
                    }
                )
        else:
            metrics["phash_distance_min"] = None
    except Exception as exc:
        findings.append(
            {
                "severity": "warning",
                "code": "phash_unavailable",
                "message": f"pHash comparison skipped: {exc}",
            }
        )

    errors = [item for item in findings if item["severity"] == "error"]
    return {
        "path": str(asset_path),
        "category": category,
        "status": "pass" if not errors else "fail",
        "metrics": metrics,
        "findings": findings,
    }


def validate_assets(
    assets: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Validate many assets and return a structured report."""

    results: list[dict[str, Any]] = []
    for asset in assets:
        path = asset["path"]
        category = asset["category"]
        results.append(
            validate_image(
                path,
                category=category,
                manifest=manifest,
                profile_id=profile_id,
            )
        )

    errors = 0
    for result in results:
        errors += len([item for item in result.get("findings", []) if item.get("severity") == "error"])

    return {
        "status": "pass" if errors == 0 else "fail",
        "error_count": errors,
        "asset_count": len(results),
        "results": results,
    }


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    """Persist a JSON report and return the resolved path."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path
