"""Generate player avatars using OpenAI's image model."""
from __future__ import annotations

import base64
import csv
import logging
import os
import shutil
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
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
    from utils.path_utils import resolve_app_path
except ModuleNotFoundError:  # pragma: no cover - for direct script execution
    from openai_client import client
    from team_loader import load_teams
    from path_utils import resolve_app_path


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

    # Template images live inside the install tree (bundled by PyInstaller
    # in packaged builds, or in the repo during dev). Resolve via
    # get_base_dir() so the relative CWD doesn't matter.
    try:
        from utils.path_utils import get_base_dir as _get_base_dir
    except ModuleNotFoundError:  # direct-script invocation
        from path_utils import get_base_dir as _get_base_dir
    base = _get_base_dir() / "images" / "avatars" / "Template"
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


def _png_size(path: Path) -> tuple[int, int] | None:
    """Read a PNG's (width, height) from its IHDR header without decoding the
    image. Returns None if the file is missing/unreadable or not a PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(head[16:20], "big")
    height = int.from_bytes(head[20:24], "big")
    return (width, height)


def generate_player_avatars(
    out_dir: str | None = None,
    progress_callback=None,
    initial_creation: bool = False,
    engine: str = "template",
    status_callback=None,
    only_player_ids: set[str] | None = None,
    only_failed: bool = False,
) -> str:
    """Generate avatars for all players.

    ``only_player_ids`` restricts generation to a specific set of players (used
    by the amateur draft to render JUST the new draftees, rather than rescanning
    and regenerating the whole league).

    Two engines:
      * ``"template"`` — recolor a bundled face template (free, instant, exact
        team colors, but only 16 base faces so same-ethnicity players repeat).
      * ``"ai"`` — a UNIQUE AI portrait per player (Vertex AI Imagen / OpenAI)
        from their ethnicity/skin/hair/facial-hair + team colors. Paced + billed
        per image, so it's incremental: with ``initial_creation=False`` it only
        generates players missing an avatar (reused forever once made).

    Parameters
    ----------
    out_dir / progress_callback / initial_creation:
        As before; ``initial_creation=True`` wipes existing avatars first.
    engine:
        ``"template"`` (default) or ``"ai"``.
    status_callback:
        Optional callable invoked with the engine actually used.
    """

    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster
    from utils.path_utils import get_data_dir

    use_ai = str(engine).strip().lower() == "ai"
    if not use_ai:
        import cv2  # only the template engine needs OpenCV
    if status_callback:
        try:
            status_callback("ai" if use_ai else "template")
        except Exception:
            pass

    players = {
        p.player_id: p for p in load_players_from_csv("data/players.csv")
    }

    # Default to the user data dir so packaged installs (Program Files =
    # read-only) can still regenerate avatars. Callers that pass an
    # explicit path still win.
    if out_dir is None:
        out_path = get_data_dir() / "images" / "avatars"
    else:
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
            if only_player_ids is not None and pid not in only_player_ids:
                continue
            player_team_pairs.append((pid, team_id))

    total = len(player_team_pairs)

    def _report_progress(done: int) -> None:
        if progress_callback is not None:
            progress_callback(done, total)

    if progress_callback is not None:
        _report_progress(0)
    if not player_team_pairs:
        return str(out_path)

    _log = logging.getLogger("nexgen.avatars")

    # Thread-safe progress counter. The AI path runs in a worker pool (each
    # image is dominated by network latency), so progress must be incremented
    # under a lock rather than from a sequential index.
    _progress_lock = threading.Lock()
    _counter = {"done": 0}

    def _tick() -> None:
        with _progress_lock:
            _counter["done"] += 1
            n = _counter["done"]
        _report_progress(n)

    def _render_one(pid: str, team_id: str) -> None:
        player = players.get(pid)
        if not player:
            return
        out_file = out_path / f"{pid}.png"
        if only_failed:
            # Only (re)generate players who don't already have a real AI
            # portrait. AI avatars are saved at 512x512; a template/failed
            # fallback is the recolored 1024x1024 base (or missing), so anything
            # that isn't 512x512 gets regenerated and the good ones are left be.
            if out_file.exists() and _png_size(out_file) == (512, 512):
                return
        elif not initial_creation and out_file.exists():
            return

        ethnicity = player.ethnicity or _infer_ethnicity(
            f"{player.first_name} {player.last_name}"
        )
        colors = _team_colors(team_id)

        if use_ai:
            # Unique AI portrait from the player's own traits + team colors.
            prompt = _build_avatar_prompt(
                f"{player.first_name} {player.last_name}",
                ethnicity,
                getattr(player, "skin_tone", None),
                player.hair_color,
                player.facial_hair,
                colors,
            )
            img_bytes = _ai_avatar_bytes(prompt, size=512)
            if not _PIL_AVAILABLE:
                raise RuntimeError("Pillow (PIL) is required to save avatars")
            with Image.open(BytesIO(img_bytes)) as im:
                if im.size != (512, 512):
                    im = im.resize((512, 512))
                out_file.parent.mkdir(parents=True, exist_ok=True)
                im.save(out_file, format="PNG")
            return

        # Template engine: recolor a bundled face template to team/player colors.
        if not _render_template_avatar(
            ethnicity,
            player.hair_color,
            player.facial_hair,
            colors["primary"],
            colors["secondary"],
            out_file,
        ):
            _log.warning(
                "avatar template missing/unreadable for player %s — skipping", pid
            )

    def _worker(pair: Tuple[str, str]) -> None:
        pid, team_id = pair
        try:
            _render_one(pid, team_id)
        except Exception as exc:  # pragma: no cover - per-player resilience
            _log.warning("avatar render failed for player %s: %s", pid, exc)
        finally:
            _tick()

    # The AI path is throttled by Vertex's per-minute quota but each request is
    # mostly network wait, so running several concurrently overlaps that wait
    # and roughly doubles throughput (the throttle in utils.vertex_image paces
    # request *starts*, not the in-flight responses). The template path is
    # already instant, so it stays single-threaded.
    if use_ai:
        try:
            workers = max(1, int(os.getenv("NEXGEN_AVATAR_WORKERS", "6")))
        except ValueError:
            workers = 6
    else:
        workers = 1

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_worker, player_team_pairs))
    else:
        for pair in player_team_pairs:
            _worker(pair)

    return str(out_path)


def _render_template_avatar(
    ethnicity: str | None,
    hair_color: str | None,
    facial_hair: str | None,
    primary_hex: str,
    secondary_hex: str,
    out_file: Path,
) -> bool:
    """Recolor a bundled face template to the given team/player colors and write
    it to ``out_file``. Returns False (without writing) if the template image is
    missing/unreadable. Pure of any team-color cache — callers pass exact hexes
    so this is safe in the multi-tenant cloud."""
    import cv2

    template = _select_template(ethnicity or "Anglo", facial_hair or "clean_shaven")
    img = cv2.imread(str(template), cv2.IMREAD_UNCHANGED)
    if img is None:
        return False
    img = _recolor_by_hex(img, _HAT_HEX, primary_hex)
    img = _recolor_by_hex(img, _JERSEY_HEX, secondary_hex)
    hair_key = (hair_color or "").strip().lower()
    hair_hex = _HAIR_COLOR_HEX.get(hair_key)
    if hair_hex:
        base_hex = _BASE_HAIR_HEX.get(template.parent.name, _HAIR_COLOR_HEX["brown"])
        img = _recolor_by_hex(img, base_hex, hair_hex)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_file), img)
    return True


def generate_one_template_avatar(
    player_id: str,
    *,
    ethnicity: str | None,
    hair_color: str | None,
    facial_hair: str | None,
    primary_color: str,
    secondary_color: str,
    out_dir: str | None = None,
) -> str | None:
    """Generate ONE player's avatar via the instant local template engine.

    Used by the amateur draft so each freshly-created player immediately gets a
    unique recolored avatar instead of falling back to the generic default.png.
    Colors are passed in explicitly (the drafting team's), so this never touches
    the process-global team-color cache. Returns the written path, or None on
    failure (caller should treat the avatar as best-effort)."""
    from utils.path_utils import get_data_dir

    out_path = Path(out_dir) if out_dir else get_data_dir() / "images" / "avatars"
    out_file = out_path / f"{player_id}.png"
    try:
        ok = _render_template_avatar(
            ethnicity, hair_color, facial_hair, primary_color, secondary_color, out_file
        )
    except Exception:
        return None
    return str(out_file) if ok else None


def regenerate_one_avatar(player_id: str, out_dir: str | None = None) -> str:
    """Regenerate a SINGLE player's avatar via the AI engine (Vertex/OpenAI).

    Used by the per-player "regenerate avatar" action so admins can spot-check
    the look/colors cheaply. Returns the written file path. Raises ValueError if
    the player isn't found or isn't on a roster.
    """
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster
    from utils.path_utils import get_data_dir

    players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
    player = players.get(player_id)
    if not player:
        raise ValueError(f"Unknown player {player_id!r}")

    # Find the player's team by scanning rosters (same as the bulk generator).
    team_id = None
    for tid in _load_team_color_map():
        roster = load_roster(tid)
        if player_id in (roster.act + roster.aaa + roster.low + roster.dl + roster.ir):
            team_id = tid
            break
    if team_id is None:
        raise ValueError(f"Player {player_id!r} is not on any roster")

    colors = _team_colors(team_id)
    ethnicity = player.ethnicity or _infer_ethnicity(
        f"{player.first_name} {player.last_name}"
    )
    prompt = _build_avatar_prompt(
        f"{player.first_name} {player.last_name}",
        ethnicity,
        getattr(player, "skin_tone", None),
        player.hair_color,
        player.facial_hair,
        colors,
    )
    img_bytes = _ai_avatar_bytes(prompt, size=512)
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow (PIL) is required to save avatars")
    out_path = Path(out_dir) if out_dir else get_data_dir() / "images" / "avatars"
    out_path.mkdir(parents=True, exist_ok=True)
    out_file = out_path / f"{player_id}.png"
    with Image.open(BytesIO(img_bytes)) as im:
        if im.size != (512, 512):
            im = im.resize((512, 512))
        im.save(out_file, format="PNG")
    return str(out_file)


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
        names_path = resolve_app_path("data/names.csv")
        with names_path.open(newline="", encoding="utf-8") as f:
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


# Saturated hue anchors (name -> representative hue in degrees) for translating
# team hex into words the image model actually understands. NEUTRAL/dark colors
# are handled separately by lightness (below) — a raw nearest-RGB match wrongly
# maps near-black like #282A28 to "forest green".
_HUE_ANCHORS = [
    (0, "red"), (15, "orange"), (32, "burnt orange"), (45, "gold"),
    (55, "yellow"), (90, "green"), (140, "green"), (165, "teal"),
    (185, "cyan"), (205, "sky blue"), (220, "blue"), (240, "royal blue"),
    (270, "purple"), (290, "violet"), (320, "magenta"), (340, "pink"), (360, "red"),
]


def _hex_to_rgb_triplet(hex_str: str) -> Tuple[int, int, int] | None:
    h = (hex_str or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _hex_to_color_name(hex_str: str) -> str:
    """Descriptive color name for a hex value, for AI prompts. Uses HSV so dark
    and low-saturation colors map to black/gray/white instead of a random hue."""
    import colorsys

    rgb = _hex_to_rgb_triplet(hex_str)
    if rgb is None:
        return str(hex_str)
    h, s, v = colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)

    # Near-black and neutral (low-saturation) colors → lightness-based names.
    if v < 0.20:
        return "black"
    if s < 0.18:
        if v < 0.32:
            return "charcoal"
        if v < 0.62:
            return "gray"
        if v < 0.86:
            return "silver"
        return "white"

    # Saturated → pick the nearest hue anchor, then darken/soften by value.
    deg = h * 360
    name = min(_HUE_ANCHORS, key=lambda a: abs(a[0] - deg))[1]
    if v < 0.45:  # dark saturated variants read better with these names
        name = {
            "red": "maroon", "blue": "navy blue", "royal blue": "navy blue",
            "green": "forest green", "orange": "brown", "burnt orange": "brown",
        }.get(name, name)
    return name


def _build_avatar_prompt(
    name: str,
    ethnicity: str,
    skin_tone: str | None,
    hair_color: str | None,
    facial_hair: str | None,
    colors: dict,
) -> str:
    """Rich per-player prompt for the AI avatar engine — unique faces driven by
    the player's own ethnicity/skin/hair/facial-hair, plus team colors (as NAMES
    so the model reproduces them accurately, with cap vs jersey made explicit)."""
    tone_part = f"{skin_tone}-skinned " if skin_tone else ""
    trait_bits = []
    if hair_color:
        trait_bits.append(f"{hair_color} hair")
    fh = (facial_hair or "").strip().lower()
    if fh and fh not in {"clean", "none", "shaven", "clean-shaven"}:
        trait_bits.append(f"a {facial_hair}")
    traits = (" with " + " and ".join(trait_bits)) if trait_bits else ""
    descriptor = f"{tone_part}{ethnicity} baseball player".strip()
    cap_color = _hex_to_color_name(colors.get("primary", ""))
    jersey_color = _hex_to_color_name(colors.get("secondary", ""))
    # Realistic semi-realistic illustration (digital painting), NOT cartoon, with
    # framing/background/lighting locked down so every player's portrait shares
    # one consistent style. The trait phrase keeps each face unique. Explicit
    # "head and shoulders / no full body / no hands" stops Imagen from
    # occasionally rendering a full-body figure.
    return (
        f"A realistic semi-realistic digital painting portrait of {name}, a "
        f"{descriptor}{traits}. Head and shoulders only, centered, facing "
        "forward with a calm friendly expression. He wears a plain "
        f"{cap_color} baseball cap and a plain {jersey_color} jersey with no "
        "logos, letters, or numbers. Detailed realistic facial features and natural "
        "skin texture, painterly digital-illustration style (not a cartoon, not "
        "a photo), soft even studio lighting, plain neutral light-gray "
        "background, subject centered and cropped at the chest. Consistent art "
        "style across portraits. No text, no watermark, no full body, no hands, "
        "no border."
    )


def _ai_avatar_bytes(prompt: str, size: int) -> bytes:
    """Generate a unique avatar PNG via the best available AI engine: Vertex AI
    Imagen (cloud, no key) preferred, else OpenAI gpt-image-1 (local)."""
    try:
        from utils import vertex_image

        if vertex_image.is_available():
            return vertex_image.generate_png(prompt, size=size)
    except Exception:
        pass
    if client is not None:
        api_size = 1024 if size <= 512 else size
        result = client.images.generate(
            model="gpt-image-1", prompt=prompt, size=f"{api_size}x{api_size}"
        )
        return base64.b64decode(result.data[0].b64_json)
    raise RuntimeError(
        "No AI image engine is configured (Vertex AI Imagen or an OpenAI key)."
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
