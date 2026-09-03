from __future__ import annotations

from datetime import datetime
import base64
import binascii
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import bcrypt

from utils.path_utils import get_data_dir

_DEFAULT_MODE = "single_player"
_OWNER_MODE = "owner_league"
_COMMISSIONER_ROLES = {"admin", "commissioner"}


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
        hashed, scheme = _hash_password(commissioner_password)
        settings["commissioner_password"] = hashed
        settings["commissioner_password_scheme"] = scheme
    elif mode != _OWNER_MODE:
        settings.pop("commissioner_password", None)
        settings.pop("commissioner_password_scheme", None)
    save_league_settings(settings, path)
    return settings


def is_owner_league(settings: Optional[Dict[str, Any]] = None) -> bool:
    payload = settings or load_league_settings()
    return str(payload.get("mode") or _DEFAULT_MODE) == _OWNER_MODE


# Whether the sim activates players off the injured list on its own the moment
# their minimum lapses. Default ON, which is what the league did before owners
# could touch the list at all — turning it off is an explicit choice to manage
# activations by hand. CPU-owned teams ignore this and always auto-activate, so
# an unowned club can never strand a healthy player.
AUTO_ACTIVATE_IL_KEY = "auto_activate_il"


def auto_activate_il(settings: Optional[Dict[str, Any]] = None) -> bool:
    """Should eligible players be activated automatically? Defaults to True."""

    payload = settings if settings is not None else load_league_settings()
    return bool(payload.get(AUTO_ACTIVATE_IL_KEY, True))


def set_auto_activate_il(
    enabled: bool, *, path: Path | str | None = None
) -> Dict[str, Any]:
    settings = load_league_settings(path)
    settings[AUTO_ACTIVATE_IL_KEY] = bool(enabled)
    save_league_settings(settings, path)
    return settings


def can_run_season_progression(
    actor_role: Optional[str],
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether the given actor can run season progression actions.

    In single-player leagues, all roles are allowed. In multi-owner leagues,
    season progression is restricted to commissioner/admin roles.
    """

    if not is_owner_league(settings):
        return True
    role = str(actor_role or "").strip().lower()
    return role in _COMMISSIONER_ROLES


def verify_commissioner_password(
    password: str,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    payload = settings or load_league_settings()
    stored = str(payload.get("commissioner_password") or "")
    if not stored:
        return False
    password = password.strip()
    scheme = str(payload.get("commissioner_password_scheme") or "").strip().lower()
    try:
        if _looks_like_bcrypt_hash(stored) or scheme in {"bcrypt", ""}:
            if bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8")):
                return True
    except Exception:
        pass

    if _verify_legacy_hash(password, stored):
        return True

    return stored == password


def _hash_password(password: str) -> Tuple[str, str]:
    password = password.strip()
    if not password:
        raise ValueError("Commissioner password is required.")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()
    scheme = "bcrypt" if _looks_like_bcrypt_hash(hashed) else "legacy_sha256"
    return hashed, scheme


def _looks_like_bcrypt_hash(value: str) -> bool:
    return value.startswith(("$2a$", "$2b$", "$2y$", "$2x$"))


def _verify_legacy_hash(password: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored, validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(raw) != 48:
        return False
    salt, digest = raw[:16], raw[16:]
    expected = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return hmac.compare_digest(digest, expected)


__all__ = [
    "can_run_season_progression",
    "configure_league_settings",
    "is_owner_league",
    "load_league_settings",
    "save_league_settings",
    "verify_commissioner_password",
]
