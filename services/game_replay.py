"""Game replays: each played game's pitch-by-pitch record, kept beside its
box score (8.14.0, backlog #74).

The engine already logs every pitch of a game (``GameResult.pitch_log``)
and keeps the records a replay needs beside it (``play_records``: who
started where, who made each out or error, who stood on which base before
and after every play). The season sim used to throw all of it away once the
box score was built. Now the game runner packs it into a compact, gzipped
JSON document (see docs/replay/REPLAY_DATA_SPEC.md) and hands it back in the
game's meta under :data:`META_KEY`; whoever saves the box score saves the
replay next to it::

    boxscores/season/2027-04-02_BOS_at_NYY.html
    boxscores/season/2027-04-02_BOS_at_NYY.replay.json.gz

Building a replay reads the finished result only: it draws no random number
and changes nothing about the game. Set ``NEXGEN_GAME_REPLAY=0`` to skip it
(bulk research sims).
"""

from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from utils.path_utils import get_data_dir

SCHEMA = "nexgen.replay/1"
REPLAY_SUFFIX = ".replay.json.gz"
# The key the game runner puts the encoded replay under in a game's meta.
# Savers pop it before the meta goes anywhere else (the playoff bracket
# stores a game's meta).
META_KEY = "replay_gz"

# Pitch-log values kept to this many decimals (feet, mph, degrees): plenty
# for a picture, and it roughly halves the document.
_DECIMALS = 2


def replay_enabled() -> bool:
    return os.environ.get("NEXGEN_GAME_REPLAY", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _compact(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, _DECIMALS)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, (list, tuple)):
        return [_compact(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _compact(v) for k, v in value.items() if v is not None}
    return value


def _player_info(player: object) -> Dict[str, Any]:
    first = str(getattr(player, "first_name", "") or "")
    last = str(getattr(player, "last_name", "") or "")
    info: Dict[str, Any] = {
        "name": f"{first} {last}".strip(),
        "bats": str(getattr(player, "bats", "") or ""),
        "throws": str(getattr(player, "throws", "") or ""),
        "pos": str(getattr(player, "primary_position", "") or ""),
    }
    return {k: v for k, v in info.items() if v}


def _participant_ids(
    pitch_log: Iterable[Mapping[str, Any]],
    play_records: Mapping[str, Any],
    substitutions: Mapping[str, Any],
) -> list[str]:
    seen: dict[str, None] = {}

    def add(pid: object) -> None:
        if pid:
            seen.setdefault(str(pid), None)

    for side in ("away", "home"):
        for pid in (play_records.get("starting_positions") or {}).get(side, {}) or {}:
            add(pid)
    for entry in pitch_log:
        add(entry.get("pitcher_id"))
        add(entry.get("batter_id"))
    for record in (play_records.get("replay_bases") or {}).values():
        for key in ("before", "after", "scored"):
            for pid in record.get(key) or []:
                add(pid)
    for side in ("away", "home"):
        for sub in substitutions.get(side) or []:
            if isinstance(sub, Mapping):
                add(sub.get("in"))
                add(sub.get("out"))
    for row in play_records.get("errors") or []:
        if isinstance(row, (list, tuple)) and len(row) > 3:
            add(row[3])
    return list(seen)


def build_replay(
    result: Any,
    *,
    home_id: str,
    away_id: str,
    home_name: str = "",
    away_name: str = "",
    park_name: str | None = None,
    park_altitude_ft: float | None = None,
    seed: int | None = None,
    game_date: str | None = None,
    postseason: bool = False,
    engine_generation: object = None,
    players_lookup: Mapping[str, object] | None = None,
) -> Dict[str, Any]:
    """The replay document of a finished game (``physics_sim`` GameResult)."""

    pitch_log = list(getattr(result, "pitch_log", None) or [])
    play_records: Mapping[str, Any] = getattr(result, "play_records", None) or {}
    metadata: Mapping[str, Any] = getattr(result, "metadata", None) or {}
    substitutions = metadata.get("substitutions") or {}
    players_lookup = players_lookup or {}

    starting = play_records.get("starting_positions") or {}
    bases = play_records.get("replay_bases") or {}
    players: Dict[str, Any] = {}
    for pid in _participant_ids(pitch_log, play_records, substitutions):
        player = players_lookup.get(pid)
        players[pid] = _player_info(player) if player is not None else {}

    errors = []
    for row in play_records.get("errors") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            errors.append(
                {"i": row[0], "source": row[1], "pos": row[2], "fielder": row[3],
                 "side": row[4]}
            )

    return {
        "schema": SCHEMA,
        "game": _compact({
            "date": game_date or "",
            "home": home_id,
            "away": away_id,
            "home_name": home_name or home_id,
            "away_name": away_name or away_id,
            "park": park_name or "",
            "park_altitude_ft": park_altitude_ft,
            "seed": seed,
            "postseason": bool(postseason),
            "engine_generation": engine_generation,
        }),
        "players": players,
        "lineups": {
            side: [[pid, pos] for pid, pos in (starting.get(side) or {}).items()]
            for side in ("away", "home")
        },
        "substitutions": _compact(substitutions),
        "pitches": [_compact(entry) for entry in pitch_log],
        "bases": {str(i): _compact(rec) for i, rec in sorted(bases.items())},
        "fielded": {str(i): pos for i, pos in sorted(
            (play_records.get("fld_pos") or {}).items()
        ) if pos},
        "errors": errors,
        "final": _compact({
            "score": metadata.get("score") or {},
            "inning_runs": metadata.get("inning_runs") or {},
            "innings": metadata.get("innings"),
        }),
    }


def encode_replay(replay: Mapping[str, Any]) -> str:
    """Gzip (with a fixed timestamp, so a game always encodes to the same
    bytes) and base64: a short ASCII string that travels in a game's meta
    and through the parallel-day journal's JSON."""

    raw = json.dumps(replay, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=6, mtime=0)).decode("ascii")


def decode_replay(raw: bytes) -> Dict[str, Any]:
    """A replay document from a stored ``.replay.json.gz`` file's bytes."""

    return json.loads(gzip.decompress(raw).decode("utf-8"))


def pop_encoded_replay(meta: object) -> Optional[str]:
    """Remove and return the encoded replay from a game's meta (None if the
    game has none)."""

    if not isinstance(meta, MutableMapping):
        return None
    blob = meta.pop(META_KEY, None)
    return blob if isinstance(blob, str) and blob else None


def replay_path_for_boxscore(box_path: str | Path) -> Path:
    """``x.html`` -> ``x.replay.json.gz`` (same folder)."""

    path = Path(box_path)
    return path.with_name(path.stem + REPLAY_SUFFIX)


def save_game_replay(box_rel_path: str, blob: Optional[str]) -> Optional[str]:
    """Write ``blob`` (from :func:`encode_replay`) next to the box score at
    ``box_rel_path`` (league-relative, as ``save_boxscore_html`` returns it).
    Returns the replay's league-relative path, or None when there was
    nothing to write. A failure never breaks the sim: the game is already
    played and its box score saved."""

    if not blob or not box_rel_path:
        return None
    try:
        data_dir = get_data_dir()
        target = data_dir / replay_path_for_boxscore(box_rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(blob))
        return target.relative_to(data_dir).as_posix()
    except Exception:
        return None


__all__ = [
    "META_KEY",
    "REPLAY_SUFFIX",
    "SCHEMA",
    "build_replay",
    "decode_replay",
    "encode_replay",
    "pop_encoded_replay",
    "replay_enabled",
    "replay_path_for_boxscore",
    "save_game_replay",
]
