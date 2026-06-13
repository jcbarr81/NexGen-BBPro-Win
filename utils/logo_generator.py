"""Utilities for generating team logos.

Logos are created using OpenAI's image generation API and written to
``logo/teams`` relative to the project root. Each logo is named after the
team's ID (lower-cased). Existing logos in the output directory are removed
before new ones are generated. If the OpenAI client is unavailable a fallback
to the legacy :mod:`images.auto_logo` generator can be enabled.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Callable, List, Optional

try:
    from PIL import Image, ImageChops  # type: ignore
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - allow running without Pillow
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

try:  # Allow running as a standalone script
    from utils.openai_client import client
    from utils.team_loader import load_teams
    from utils.path_utils import get_base_dir, get_data_dir
except ModuleNotFoundError:  # pragma: no cover - for direct script execution
    from openai_client import client
    from team_loader import load_teams
    from path_utils import get_base_dir, get_data_dir

def _trim_logo_bytes(png_bytes: bytes, pad_frac: float = 0.13) -> bytes:
    """Auto-crop the flat background margin off a generated logo so the mascot
    fills the frame consistently, then re-center on a square canvas with a small
    even pad. Image models leave wildly different margins per image; this
    normalizes them. Returns the original bytes on any failure / if nothing to trim."""
    if not _PIL_AVAILABLE:
        return png_bytes
    try:
        im = Image.open(BytesIO(png_bytes)).convert("RGB")
        w, h = im.size
        corners = [
            im.getpixel((0, 0)), im.getpixel((w - 1, 0)),
            im.getpixel((0, h - 1)), im.getpixel((w - 1, h - 1)),
        ]
        bg = max(set(corners), key=corners.count)
        diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
        mask = diff.point(lambda p: 255 if p > 28 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return png_bytes
        cropped = im.crop(bbox)
        cw, ch = cropped.size
        # Ignore essentially-full-frame art (already tight) to avoid a no-op recompress.
        if cw >= w * 0.96 and ch >= h * 0.96:
            return png_bytes
        side = max(cw, ch)
        pad = int(round(side * pad_frac))
        canvas_side = side + 2 * pad
        canvas = Image.new("RGB", (canvas_side, canvas_side), bg)
        canvas.paste(cropped, ((canvas_side - cw) // 2, (canvas_side - ch) // 2))
        out = BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return png_bytes


def normalize_team_logos(
    out_dir: str | None = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Re-frame ALL already-generated team logos in place (no AI): trim each
    logo's background margin so every team's mascot fills the frame consistently.
    Cheap + instant — keeps the existing artwork."""
    _require_pillow()
    target = Path(out_dir) if out_dir else get_data_dir() / "logo" / "teams"
    files = sorted(target.glob("*.png")) if target.is_dir() else []
    total = len(files)
    if progress_callback:
        progress_callback(0, total)
    for idx, fp in enumerate(files, start=1):
        try:
            data = fp.read_bytes()
            trimmed = _trim_logo_bytes(data)
            if trimmed is not data:
                fp.write_bytes(trimmed)
        except Exception:
            pass
        if progress_callback:
            progress_callback(idx, total)
    return str(target)


def _require_pillow() -> None:
    """Raise a helpful error if Pillow is not installed.

    Using a central guard avoids import-time crashes in the GUI and surfaces a
    clear message guiding the user to install the dependency.
    """

    if not _PIL_AVAILABLE:
        raise RuntimeError(
            "Pillow (PIL) is not installed. Install it with:\
  python -m pip install Pillow\n\n"
            "If you use virtual environments, ensure you install into the same\n"
            "environment that runs NexGen-BBPro."
        )



def _auto_logo_fallback(
    teams: List[object],
    out_dir: str,
    size: int,
    progress_callback: Optional[Callable[[int, int], None]],
) -> None:
    """Generate logos using the legacy ``images.auto_logo`` module."""

    _require_pillow()
    from images.auto_logo import (
        TeamSpec,
        generate_logo,
        save_logo,
        _seed_from_name,
    )  # pragma: no cover

    specs: List[TeamSpec] = []
    for t in teams:
        specs.append(
            TeamSpec(
                location=t.city,
                mascot=t.name,
                primary=t.primary_color,
                secondary=t.secondary_color,
                abbrev=t.team_id,
                template="auto",
                seed=_seed_from_name(t.city, t.name),
            )
        )

    total = len(specs)
    completed = 0

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(completed, total)

    for spec in specs:
        img = generate_logo(spec, size=1024)
        if size != 1024:
            img = img.resize((size, size), Image.LANCZOS)
        filename = (
            f"{spec.abbrev or (spec.location + ' ' + spec.mascot)}"
            .replace(" ", "_")
            .lower()
            + ".png"
        )
        path = out_dir / filename
        save_logo(img, str(path))
        completed += 1
        if progress_callback:
            progress_callback(completed, total)


def _build_openai_prompt(team: object) -> str:
    """Return a MASCOT-forward logo prompt: depict the team's namesake creature/
    figure as a sports mascot emblem, not a generic baseball player, and with no
    text. Uses descriptive color names (image models render those far better than
    hex)."""

    name = getattr(team, "name", "") or "team"
    primary = getattr(team, "primary_color", "")
    secondary = getattr(team, "secondary_color", "")
    try:
        from utils.avatar_generator import _hex_to_color_name

        primary_c = _hex_to_color_name(primary) if primary else "a bold team color"
        secondary_c = _hex_to_color_name(secondary) if secondary else "a contrasting accent"
    except Exception:
        primary_c = primary or "a bold team color"
        secondary_c = secondary or "a contrasting accent"

    parts = [
        f"A bold, modern professional sports MASCOT logo for a team called the {name}.",
        (
            f"Center the design entirely on the {name} itself: illustrate the actual "
            f"{name} — the creature, animal, warrior, or figure the name refers to — "
            "as a fierce, dynamic mascot character or emblem with strong attitude. "
            "Do NOT draw a generic baseball player."
        ),
        (
            "Style: clean bold vector mascot emblem / team crest, thick confident "
            "outlines, layered shading, aggressive athletic energy, like a pro sports "
            "team cap or jersey logo."
        ),
        f"Color scheme: {primary_c} as the dominant color with {secondary_c} accents.",
        (
            "Composition: the mascot should be LARGE and fill most of the frame, "
            "centered, with only a small even margin — not a tiny emblem floating "
            "in empty space."
        ),
        "Single centered emblem on a plain flat solid background, no scenery, no photo background.",
        (
            "IMPORTANT: the image must contain NO text, NO letters, NO words, NO team "
            "name, NO city name, and NO numbers — mascot artwork only."
        ),
    ]
    return " ".join(part.strip() for part in parts if part.strip())


def generate_team_logos(
    out_dir: str | None = None,
    size: int = 512,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    allow_auto_logo: bool = True,
    status_callback: Optional[Callable[[str], None]] = None,
    prompt_builder: Optional[Callable[[object], str]] = None,
    force_engine: Optional[str] = None,
) -> str:
    """Generate logos for all teams and return the output directory.

    Parameters
    ----------
    out_dir:
        Optional output directory. Defaults to ``logo/teams`` relative to the
        project root.
    size:
        Pixel size for the square logos. Images are always generated at
        ``1024x1024`` and then resized to this value when saved.
    progress_callback:
        Optional callback receiving ``(completed, total)`` after each logo is
        saved.
    allow_auto_logo:
        When ``True`` (the default) and the OpenAI client is not configured,
        fall back to the older :mod:`images.auto_logo` generator. Set to
        ``False`` to raise a ``RuntimeError`` instead.
    status_callback:
        Optional callable invoked with ``"openai"`` or ``"auto_logo"`` to
        indicate which generation path was used.
    prompt_builder:
        Optional callback receiving a team object and returning a custom
        OpenAI prompt. When omitted, the default built-in prompt is used.
    """

    def _notify_status(value: str) -> None:
        if status_callback:
            try:
                status_callback(value)
            except Exception:
                pass

    _require_pillow()
    teams = load_teams("data/teams.csv")

    if out_dir is None:
        # Write to the user data dir so packaged installs (where
        # get_base_dir() lives under Program Files — read-only) can
        # still regenerate logos. The read side checks the data dir
        # first, then falls back to the seed logos bundled with the app.
        out_dir = get_data_dir() / "logo" / "teams"
    else:
        out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove any existing logos so stale files do not persist
    for existing in out_dir.glob("*.png"):
        existing.unlink(missing_ok=True)

    # Explicit engine selection wins over the auto-detect path. This lets
    # the UI force the simple/offline renderer even when an OpenAI key is
    # configured, or require OpenAI and fail loudly.
    if force_engine == "auto_logo":
        _notify_status("auto_logo")
        _auto_logo_fallback(teams, out_dir, size, progress_callback)
        return str(out_dir)

    # Detailed renderers: OpenAI gpt-image-1 (local/desktop, needs an API key) or
    # Vertex AI Imagen (cloud, GCP service-account auth — no key). Pick whichever
    # is configured; ``force_engine`` expresses a preference, not a hard pin, so
    # the "Detailed Logos" button works in the cloud (Vertex) and locally (OpenAI).
    openai_ok = client is not None
    vertex_ok = False
    try:
        from utils import vertex_image

        vertex_ok = vertex_image.is_available()
    except Exception:
        vertex_ok = False

    if force_engine == "vertex":
        engine = "vertex" if vertex_ok else ("openai" if openai_ok else None)
    else:  # "openai" or auto-detect → prefer OpenAI, else Vertex
        engine = "openai" if openai_ok else ("vertex" if vertex_ok else None)

    if engine is None:
        if allow_auto_logo:
            _notify_status("auto_logo")
            _auto_logo_fallback(teams, out_dir, size, progress_callback)
            return str(out_dir)
        raise RuntimeError(
            "No detailed logo renderer is configured. Add an OpenAI API key "
            "(Admin → Utilities → AI Renderer) or enable Vertex AI Imagen, or "
            "use the Simple Logos button."
        )

    total = len(teams)
    _notify_status(engine)
    if progress_callback:
        progress_callback(0, total)

    for idx, t in enumerate(teams, start=1):
        if prompt_builder is not None:
            prompt = str(prompt_builder(t))
        else:
            prompt = _build_openai_prompt(t)
        if engine == "openai":
            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1024",
                background="transparent",
            )
            image_bytes = base64.b64decode(result.data[0].b64_json)
        else:  # vertex
            from utils import vertex_image

            image_bytes = vertex_image.generate_png(prompt, size=1024)
        # Normalize framing: trim the model's background margin so every logo's
        # mascot fills the frame consistently.
        image_bytes = _trim_logo_bytes(image_bytes)
        path = out_dir / f"{t.team_id.lower()}.png"
        _require_pillow()
        with Image.open(BytesIO(image_bytes)) as img:
            if size != 1024:
                img = img.resize((size, size), Image.LANCZOS)
            img.save(path, format="PNG")
        if progress_callback:
            progress_callback(idx, total)

    return str(out_dir)


__all__ = ["generate_team_logos", "normalize_team_logos"]

