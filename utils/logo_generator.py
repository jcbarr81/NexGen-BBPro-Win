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
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - allow running without Pillow
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

try:  # Allow running as a standalone script
    from utils.openai_client import client
    from utils.team_loader import load_teams
    from utils.path_utils import get_base_dir
except ModuleNotFoundError:  # pragma: no cover - for direct script execution
    from openai_client import client
    from team_loader import load_teams
    from path_utils import get_base_dir

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
    """Return a richer logo prompt that highlights location and mascot."""

    city = getattr(team, "city", "") or ""
    name = getattr(team, "name", "") or ""
    abbrev = (
        getattr(team, "abbreviation", "")
        or getattr(team, "team_id", "")
        or ""
    )
    primary = getattr(team, "primary_color", "")
    secondary = getattr(team, "secondary_color", "")

    parts = [
        (
            "Design a professional illustrated baseball team logo for the "
            f"{city} {name}."
        ),
        (
            f"Depict the {name} mascot as a detailed character "
            "in an energetic baseball action pose, conveying motion and "
            "intensity."
        ),
        (
            "Integrate baseball equipment such as a ball, bat, glove, or "
            "diamond to reinforce the sport."
        ),
        (
            f"Include a subtle visual nod to {city} and weave the team "
            f"initials {abbrev.upper()} into the emblem as a supporting "
            "element."
        ),
        (
            "Use modern sports-brand styling with clean vector shapes, bold "
            "outlines, layered shading, and dramatic lighting suitable for "
            "merch and digital use."
        ),
        (
            f"Apply {primary} as the dominant color with {secondary} accents "
            "and harmonious contrast."
        ),
        (
            "Avoid typography-first or wordmark-only designs. Do not output "
            "plain text logos; lettering should remain secondary to the "
            "illustrated mascot emblem."
        ),
        (
            "Provide a polished emblem with a transparent background "
            "aesthetic and no busy scenery."
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
        out_dir = get_base_dir() / "logo" / "teams"
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
    if force_engine == "openai" and client is None:
        raise RuntimeError(
            "OpenAI client is not configured. Add an API key from Admin → "
            "Utilities → AI Renderer, or use the Simple Logos button."
        )

    if client is None:
        if allow_auto_logo:
            _notify_status("auto_logo")
            _auto_logo_fallback(teams, out_dir, size, progress_callback)
            return str(out_dir)
        raise RuntimeError("OpenAI client is not configured")

    total = len(teams)
    _notify_status("openai")
    if progress_callback:
        progress_callback(0, total)

    for idx, t in enumerate(teams, start=1):
        if prompt_builder is not None:
            prompt = str(prompt_builder(t))
        else:
            prompt = _build_openai_prompt(t)
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            background="transparent",
        )
        b64 = result.data[0].b64_json
        image_bytes = base64.b64decode(b64)
        path = out_dir / f"{t.team_id.lower()}.png"
        _require_pillow()
        with Image.open(BytesIO(image_bytes)) as img:
            if size != 1024:
                img = img.resize((size, size), Image.LANCZOS)
            img.save(path, format="PNG")
        if progress_callback:
            progress_callback(idx, total)

    return str(out_dir)


__all__ = ["generate_team_logos"]

