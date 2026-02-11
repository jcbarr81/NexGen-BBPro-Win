from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

import bcrypt

from utils.path_utils import get_data_dir

_DEFAULT_MODE = "single_player"
_OWNER_MODE = "owner_league"


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _settings_path(path: Path | str | None = None) -> Path:
    return Path(path) if path is not None else (get_data_dir() / "league_settings.json")


def load_league_settings(path: Path | str | None = None) -> Dict[str, Any]:
    target = _settings_path(path)
    if not target.exists():
        return {"mode": _DEFAULT_MODE}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": _DEFAULT_MODE}
    if not isinstance(payload, dict):
        return {"mode": _DEFAULT_MODE}
    payload.setdefault("mode", _DEFAULT_MODE)
    return payload


def save_league_settings(settings: Dict[str, Any], path: Path | str | None = None) -> None:
    target = _settings_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(settings)
    payload.setdefault("created_at", _now_iso())
    payload["updated_at"] = _now_iso()
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def configure_league_settings(
    *,
    mode: str,
    commissioner_password: str | None = None,
    path: Path | str | None = None,
) -> Dict[str, Any]:
    settings = load_league_settings(path)
    settings["mode"] = mode
    if commissioner_password is not None:
        settings["commissioner_password"] = _hash_password(commissioner_password)
        settings["commissioner_password_scheme"] = "bcrypt"
    elif mode != _OWNER_MODE:
        settings.pop("commissioner_password", None)
        settings.pop("commissioner_password_scheme", None)
    save_league_settings(settings, path)
    return settings


def is_owner_league(settings: Optional[Dict[str, Any]] = None) -> bool:
    payload = settings or load_league_settings()
    return str(payload.get("mode") or _DEFAULT_MODE) == _OWNER_MODE


def verify_commissioner_password(
    password: str,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    payload = settings or load_league_settings()
    stored = str(payload.get("commissioner_password") or "")
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return stored == password


def _hash_password(password: str) -> str:
    password = password.strip()
    if not password:
        raise ValueError("Commissioner password is required.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


__all__ = [
    "configure_league_settings",
    "is_owner_league",
    "load_league_settings",
    "save_league_settings",
    "verify_commissioner_password",
]
