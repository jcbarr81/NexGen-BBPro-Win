from __future__ import annotations

"""Draft configuration loader.

Provides minimal configuration for the Amateur Draft (rounds, pool size, seed)
with a JSON override at data/draft_config.json. Safe defaults are returned if
no file exists or the file is invalid.
"""

from pathlib import Path
import json
from typing import Dict, Any

from utils.path_utils import get_data_dir


DEFAULTS: Dict[str, Any] = {
    "rounds": 10,
    "pool_size": 200,
    "seed": None,
}


def _config_path() -> Path:
    return get_data_dir() / "draft_config.json"


def load_draft_config() -> Dict[str, Any]:
    path = _config_path()
    cfg = dict(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: raw[k] for k in ("rounds", "pool_size", "seed") if k in raw})
    except Exception:
        pass
    # coerce types
    try:
        if cfg.get("rounds") is not None:
            cfg["rounds"] = int(cfg["rounds"])  # type: ignore[arg-type]
    except Exception:
        cfg["rounds"] = DEFAULTS["rounds"]
    try:
        if cfg.get("pool_size") is not None:
            cfg["pool_size"] = int(cfg["pool_size"])  # type: ignore[arg-type]
    except Exception:
        cfg["pool_size"] = DEFAULTS["pool_size"]
    return cfg


def save_draft_config(cfg: Dict[str, Any]) -> None:
    """Persist draft config to `data/draft_config.json`.

    Only recognized keys (rounds, pool_size, seed) are written.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {}
    for key in ("rounds", "pool_size", "seed"):
        if key in cfg:
            payload[key] = cfg[key]
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        # Silent failure; caller may choose to notify UI
        pass


__all__ = ["load_draft_config", "save_draft_config", "DEFAULTS"]
