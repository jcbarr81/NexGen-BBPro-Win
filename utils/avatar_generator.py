"""Generate player avatars using OpenAI's image model."""
from __future__ import annotations

import base64
import csv
import shutil
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict, Tuple

try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - environment without Pillow
    Image = None  # type: ignore
    _PIL_AVAILABLE = False

try:  # Allow running as a standalone script
    from utils.openai_client import client
    from utils.team_loader import load_teams
except ModuleNotFoundError:  # pragma: no cover - for direct script execution
    from openai_client import client
    from team_loader import load_teams


# Hair color to hex mapping used for template recoloring
_HAIR_COLOR_HEX = {
    "black": "#2b2b2b",
    "brown": "#5b4632",
    "blonde": "#d8b25a",
    "red": "#a64b2a",
}

# Default hair colors present in the avatar templates keyed by ethnicity.
# These values represent the original hair color in the template images before
# any recoloring is applied.
_BASE_HAIR_HEX = {
    "Anglo": _HAIR_COLOR_HEX["brown"],
    "African": _HAIR_COLOR_HEX["black"],
    "Asian": _HAIR_COLOR_HEX["black"],
    "Hispanic": _HAIR_COLOR_HEX["brown"],
}

# Map various ethnicity strings to the available template directories. Any
# unrecognized value falls back to ``Anglo``.
_ETHNICITY_DIR = {
    "anglo": "Anglo",
    "caucasian": "Anglo",
    "african": "African",
    "african american": "African",
    "black": "African",
    "asian": "Asian",
    "asian american": "Asian",
    "pacific islander": "Asian",
    "hispanic": "Hispanic",
    "hispanic american": "Hispanic",
    "latino": "Hispanic",
    "latina": "Hispanic",
}

# Base colors present in the avatar templates that need to be replaced.
# These hex values correspond to the default hat and jersey colors in the
# shipped template images.  Any pixels matching these colors will be
# recolored to match the player's team colors.
_HAT_HEX = "#1B437E"
_JERSEY_HEX = "#B7B8B8"


def _select_template(ethnicity: str, facial_hair: str | None) -> Path:
    """Return the appropriate avatar template path.

    Parameters
    ----------
    ethnicity:
        Player ethnicity used to select the template directory. The string is
        normalized and mapped to one of the available template folders.
        Unrecognized values default to the ``Anglo`` templates.
    facial_hair:
        Style of facial hair. ``None`` or empty strings fall back to
        ``"clean.png"``. ``"clean_shaven"`` also maps to ``"clean.png"``.
    """

    base = Path("images/avatars/Template")
    key = ethnicity.strip().lower().replace("-", " ")
    ethnic_dir = base / _ETHNICITY_DIR.get(key, "Anglo")

    # ``facial_hair`` may be ``None`` or an empty string for clean-shaven
    # players. Normalize it before constructing the filename so that we use the
    # correct template directory rather than always falling back to the Anglo
    # set.
    fh_key = (facial_hair or "clean").strip().lower()
    hair_map = {"clean_shaven": "clean"}
    fname = hair_map.get(fh_key, fh_key) + ".png"
    path = ethnic_dir / fname
    if not path.exists():
        # Fall back to the clean template within the selected ethnicity before
        # ultimately defaulting to the Anglo clean template.
        path = ethnic_dir / "clean.png"
        if not path.exists():
            path = base / "Anglo" / "clean.png"
    return PurePosixPath(path.as_posix())


def _hex_to_bgr(h: str):
    h = h.lstrip("#")
    if len(h) != 6:
        raise ValueError("Hex color must be 6 characters like #E00000")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return b, g, r


def _make_hsv_range(src_hex: str, tol_h=12, tol_s=60, tol_v=60):
    import numpy as np
    import cv2

    src_bgr = np.uint8([[list(_hex_to_bgr(src_hex))]])
    src_hsv = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2HSV)[0, 0]
    h, s, v = int(src_hsv[0]), int(src_hsv[1]), int(src_hsv[2])
    low_h = h - tol_h
    high_h = h + tol_h
    ranges = []
    if low_h >= 0 and high_h <= 179:
        ranges.append(
            (
                np.array([low_h, max(0, s - tol_s), max(0, v - tol_v)], dtype=np.uint8),
                np.array([high_h, min(255, s + tol_s), min(255, v + tol_v)], dtype=np.uint8),
            )
        )
    else:
        ranges.append(
            (
                np.array(
                    [
                        max(0, low_h) if low_h >= 0 else 0,
                        max(0, s - tol_s),
                        max(0, v - tol_v),
                    ],
                    dtype=np.uint8,
                ),
                np.array([179, min(255, s + tol_s), min(255, v + tol_v)], dtype=np.uint8),
            )
        )
        ranges.append(
            (
                np.array([0, max(0, s - tol_s), max(0, v - tol_v)], dtype=np.uint8),
                np.array(
                    [
                        high_h - 179 if high_h > 179 else high_h,
                        min(255, s + tol_s),
                        min(255, v + tol_v),
                    ],
                    dtype=np.uint8,
                ),
            )
        )
    return ranges


def _recolor_by_hex(img, src_hex: str, dst_hex: str, feather: float = 3.0,
                    sat_blend: float = 0.5):
    import numpy as np
    try:
        import cv2  # type: ignore
    except Exception:  # pragma: no cover - environment without OpenCV
        # Fallback: no recoloring, but preserve alpha channel and shape
        return np.array(img, copy=True)

    has_alpha = img.shape[2] == 4
    bgr = img[:, :, :3]
    alpha = img[:, :, 3] if has_alpha else None

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    ranges = _make_hsv_range(src_hex)
    mask = None
    for lower, upper in ranges:
        part = cv2.inRange(hsv, lower, upper)
        mask = part if mask is None else cv2.bitwise_or(mask, part)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), feather)

    target_bgr = np.uint8([[list(_hex_to_bgr(dst_hex))]])
    target_hsv = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2HSV)[0, 0]
    th, ts = int(target_hsv[0]), int(target_hsv[1])
    h, s, v = cv2.split(hsv)
    alpha_f = mask.astype(np.float32) / 255.0
    h_f = h.astype(np.float32)
    s_f = s.astype(np.float32)
    target_s = (sat_blend * s_f + (1.0 - sat_blend) * ts).astype(np.float32)
    h_new = (alpha_f * th + (1 - alpha_f) * h_f).astype(np.uint8)
    s_new = (alpha_f * target_s + (1 - alpha_f) * s_f).astype(np.uint8)
    hsv_new = cv2.merge([h_new, s_new, v])
    bgr_new = cv2.cvtColor(hsv_new, cv2.COLOR_HSV2BGR)
    if has_alpha:
        # ``cv2.merge`` expects individual single-channel arrays, but ``bgr_new``
        # is already a 3-channel image. Passing it directly with ``alpha``
        # triggers an OpenCV assertion error. ``np.dstack`` safely appends the
        # alpha channel while preserving existing channels and size.
        bgr_new = np.dstack((bgr_new, alpha))
    return bgr_new


def generate_player_avatars(
    out_dir: str = "images/avatars",
    progress_callback=None,
    initial_creation: bool = False,
) -> str:
    """Generate avatars for all players using template images.

    The function selects the correct template based on a player's ethnicity and
    facial hair and recolors the hat, jersey, and hair to match team and player
    attributes.

    Parameters
    ----------
    out_dir:
        Directory where avatar images will be written.
    progress_callback:
        Optional callable to receive progress updates as ``(done, total)``.
    initial_creation:
        When ``True`` all existing player avatars in ``out_dir`` are deleted
        before generation (the ``Template`` folder is preserved).  When
        ``False`` avatars are only generated for players missing an image.
    """

    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    import cv2

    players = {
        p.player_id: p for p in load_players_from_csv("data/players.csv")
    }

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    if initial_creation:
        for item in out_path.iterdir():
            if item.name in {"Template", "default.png"}:
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    # Collect all player IDs across rosters
    team_colors = _load_team_color_map()
    player_team_pairs = []
    for team_id in team_colors:
        roster = load_roster(team_id)
        ids = roster.act + roster.aaa + roster.low + roster.dl + roster.ir
        for pid in ids:
            player_team_pairs.append((pid, team_id))

    total = len(player_team_pairs)

    def _report_progress(done: int) -> None:
        if progress_callback is not None:
            progress_callback(done, total)

    if progress_callback is not None:
        _report_progress(0)
    if not player_team_pairs:
        return str(out_path)

    for idx, (pid, team_id) in enumerate(player_team_pairs, start=1):
        player = players.get(pid)
        if not player:
            _report_progress(idx)
            continue

        out_file = out_path / f"{pid}.png"
        if not initial_creation and out_file.exists():
            _report_progress(idx)
            continue

        ethnicity = player.ethnicity or _infer_ethnicity(
            f"{player.first_name} {player.last_name}"
        )
        template = _select_template(ethnicity, player.facial_hair)
        img = cv2.imread(str(template), cv2.IMREAD_UNCHANGED)
        if img is None:
            _report_progress(idx)
            continue

        colors = _team_colors(team_id)
        img = _recolor_by_hex(img, _HAT_HEX, colors["primary"])
        img = _recolor_by_hex(img, _JERSEY_HEX, colors["secondary"])

        hair_key = (player.hair_color or "").strip().lower()
        hair_hex = _HAIR_COLOR_HEX.get(hair_key)
        if hair_hex:
            base_hex = _BASE_HAIR_HEX.get(template.parent.name, _HAIR_COLOR_HEX["brown"])
            img = _recolor_by_hex(img, base_hex, hair_hex)

        cv2.imwrite(str(out_file), img)

        _report_progress(idx)

    return str(out_path)


_TEAM_COLOR_MAP: Dict[str, Dict[str, str]] = {}
_TEAM_COLOR_MAP_LOADED = False


def _load_team_color_map() -> Dict[str, Dict[str, str]]:
    """Return team color mapping when available, otherwise an empty map."""
    global _TEAM_COLOR_MAP_LOADED, _TEAM_COLOR_MAP
    if _TEAM_COLOR_MAP_LOADED:
        return _TEAM_COLOR_MAP
    _TEAM_COLOR_MAP_LOADED = True
    try:
        teams = load_teams("data/teams.csv")
    except Exception:
        _TEAM_COLOR_MAP = {}
        return _TEAM_COLOR_MAP
    _TEAM_COLOR_MAP = {
        t.team_id: {
            "primary": t.primary_color,
            "secondary": t.secondary_color,
        }
        for t in teams
    }
    return _TEAM_COLOR_MAP


# Preload ethnicity data from names.csv for quick lookups.
# Mapping: (first_name, last_name) -> Counter of ethnicities
_NAME_ETHNICITY_FULL: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)
# Mapping: individual name -> Counter of ethnicities
_NAME_ETHNICITY_SINGLE: Dict[str, Counter[str]] = defaultdict(Counter)
_NAME_ETHNICITY_LOADED = False


def _ensure_name_ethnicity_loaded() -> None:
    global _NAME_ETHNICITY_LOADED
    if _NAME_ETHNICITY_LOADED:
        return
    _NAME_ETHNICITY_LOADED = True
    try:
        with Path("data/names.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ethnicity = row.get("ethnicity")
                first = (row.get("first_name") or "").strip().lower()
                last = (row.get("last_name") or "").strip().lower()
                if not ethnicity or not (first or last):
                    continue
                _NAME_ETHNICITY_FULL[(first, last)][ethnicity] += 1
                if first:
                    _NAME_ETHNICITY_SINGLE[first][ethnicity] += 1
                if last:
                    _NAME_ETHNICITY_SINGLE[last][ethnicity] += 1
    except OSError:
        return


def _infer_ethnicity(name: str) -> str:
    """Return the most probable ethnicity for ``name``.

    The lookup prioritizes an exact match of both first and last name and then
    falls back to individual name statistics. "unspecified" is returned when no
    data exists for the provided name.
    """

    parts = [p.strip().lower() for p in name.split() if p.strip()]
    if not parts:
        return "unspecified"

    _ensure_name_ethnicity_loaded()
    first, last = parts[0], parts[-1]

    scores: Counter[str] = Counter()
    scores.update(_NAME_ETHNICITY_FULL.get((first, last), {}))
    scores.update(_NAME_ETHNICITY_SINGLE.get(first, {}))
    scores.update(_NAME_ETHNICITY_SINGLE.get(last, {}))

    if not scores:
        return "unspecified"

    return scores.most_common(1)[0][0]


def _team_colors(team_id: str) -> Dict[str, str]:
    return _load_team_color_map().get(
        team_id, {"primary": "#000000", "secondary": "#ffffff"}
    )


def generate_avatar(
    name: str,
    team_id: str,
    out_file: str,
    size: int = 512,
    style: str = "illustrated",
    skin_tone: str | None = None,
    hair_color: str | None = None,
    facial_hair: str | None = None,
) -> str:
    """Generate an avatar for ``name`` and save it to ``out_file``.

    The avatar uses an off-white background and depicts a player in a plain cap
    and jersey in team colors without any logos, images, letters, names, or
    numbers. The image must contain no text overlays.

    Parameters
    ----------
    name:
        Player's full name.
    team_id:
        Identifier of the player's team to derive colors.
    out_file:
        Path where the resulting PNG should be written.
    size:
        Pixel size for the square avatar. This value is passed directly to the
        OpenAI image API.
    style:
        Art style for the portrait (e.g., ``"illustrated"``). The prompt always
        requests a cartoon style.
    skin_tone:
        Optional descriptor for the player's complexion (e.g., ``"light"``).
    hair_color:
        Optional hair color descriptor.
    facial_hair:
        Optional facial hair style (e.g., ``"goatee"``).
    """
    if client is None:  # pragma: no cover - depends on external package
        raise RuntimeError("OpenAI client is not configured")

    colors = _team_colors(team_id)
    ethnicity = _infer_ethnicity(name)

    tone_part = f"{skin_tone}-skinned " if skin_tone else ""
    trait_bits = []
    if hair_color:
        trait_bits.append(f"{hair_color} hair")
    if facial_hair:
        trait_bits.append(f"a {facial_hair}")
    traits = ""
    if trait_bits:
        traits = " with " + " and ".join(trait_bits)

    descriptor = f"{tone_part}{ethnicity} baseball player"
    prompt = (
        f"{style.capitalize()} portrait of {name}, a {descriptor}{traits}, "
        "wearing a plain ball cap and jersey in team colors "
        f"{colors['primary']} and {colors['secondary']}. The cap has no logo, "
        "image, or letters and the jersey has no names, letters, or numbers. "
        "The image contains no text overlays or names on an off-white background "
        "in a cartoon style."
    )
    api_size = 1024 if size == 512 else size
    result = client.images.generate(
        model="gpt-image-1", prompt=prompt, size=f"{api_size}x{api_size}"
    )
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow (PIL) is required to decode and save avatars")
    b64 = result.data[0].b64_json
    image_bytes = base64.b64decode(b64)
    with Image.open(BytesIO(image_bytes)) as img:
        if img.size != (size, size):
            img = img.resize((size, size))
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_file, format="PNG")
    return out_file

__all__ = ["generate_avatar", "generate_player_avatars"]
