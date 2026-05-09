from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import shutil
import sys
import stat
import json


_DATA_DIR: Path | None = None
_DATA_DIR_KEY: tuple[str, bool, str] | None = None
_DATA_ROOT: Path | None = None
_DATA_ROOT_KEY: tuple[str, bool, str] | None = None
_LEAGUE_REGISTRY_FILENAME = "league_registry.json"
_ACTIVE_LEAGUE_FILENAME = "active_league.txt"
_MINIMAL_DATA_FILES = (
    "names.csv",
    # Reference player pool seeded into the user data dir on first run
    # so the player generator has real per-stat distributions to sample
    # from (otherwise eye/fa/arm/gf/pl/vl/sc fall back to 50 ± 2.5 jitter
    # and no one in a newly-created league ever shows a real spread).
    "players.csv",
    "ballparks.py",
    "draft_config.json",
    "injury_catalog.json",
)
_MINIMAL_DATA_DIRS = (
    "MLB_avg",
    "parks",
)
_SEED_EXCLUDE_FILES = frozenset({_LEAGUE_REGISTRY_FILENAME, _ACTIVE_LEAGUE_FILENAME})


class ActivePath:
    """Path-like proxy that resolves against current runtime context."""

    def __init__(self, resolver):
        self._resolver = resolver

    def _path(self) -> Path:
        return self._resolver()

    def __fspath__(self) -> str:
        return os.fspath(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return repr(self._path())

    def __truediv__(self, key):
        return self._path() / key

    def __getattr__(self, name):
        return getattr(self._path(), name)

    def __eq__(self, other: object) -> bool:
        return self._path() == other


def get_base_dir() -> Path:
    """Return project root or PyInstaller's temporary directory."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _normalize_league_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip().lower()
    if not candidate:
        return None
    normalized = []
    for char in candidate:
        if char.isalnum() or char in {"-", "_"}:
            normalized.append(char)
    result = "".join(normalized).strip("-_")
    return result or None


def _can_write_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    test_path = path / ".write_test"
    try:
        with test_path.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        try:
            test_path.unlink()
        except OSError:
            pass
        return True
    except OSError:
        try:
            if test_path.exists():
                test_path.unlink()
        except OSError:
            pass
        return False


def _clear_readonly(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _clear_readonly_tree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        _clear_readonly(path)
        return
    for root, dirs, files in os.walk(path):
        for name in dirs:
            _clear_readonly(Path(root) / name)
        for name in files:
            _clear_readonly(Path(root) / name)
    _clear_readonly(path)


def _seed_data_dir(source: Path, target: Path) -> None:
    if not source.exists():
        return
    try:
        needs_full_seed = any(
            not (target / name).exists()
            for name in ("teams.csv", "players.csv", "users.txt")
        )
    except OSError:
        needs_full_seed = True
    if needs_full_seed:
        for item in source.iterdir():
            if item.name in _SEED_EXCLUDE_FILES:
                continue
            dest = target / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
                _clear_readonly_tree(dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                _clear_readonly(dest)
        return
    for name in _MINIMAL_DATA_FILES:
        src = source / name
        dest = target / name
        if src.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    for name in _MINIMAL_DATA_DIRS:
        src = source / name
        dest = target / name
        if src.exists() and not dest.exists():
            shutil.copytree(src, dest)
            _clear_readonly_tree(dest)


def _resolve_data_root() -> Path:
    base_dir = get_base_dir()
    base_data = base_dir / "data"
    running_frozen = bool(getattr(sys, "frozen", False))

    def _should_seed_root(target: Path) -> bool:
        registry = target / _LEAGUE_REGISTRY_FILENAME
        leagues_root = target / "leagues"
        return not registry.exists() and not leagues_root.exists()

    override = os.environ.get("NEXGEN_DATA_ROOT") or os.environ.get("NEXGEN_DATA_DIR")
    if override:
        candidate = Path(override)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            if _should_seed_root(candidate):
                _seed_data_dir(base_data, candidate)
            _clear_readonly_tree(candidate)
            return candidate
        except OSError:
            pass

    if not running_frozen and _can_write_dir(base_data):
        return base_data

    local_app = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local_app:
        user_data = Path(local_app) / "NexGen-BBPro" / "data"
    else:
        user_data = Path.home() / ".nexgen-bbpro" / "data"

    try:
        user_data.mkdir(parents=True, exist_ok=True)
    except OSError:
        return base_data

    if _should_seed_root(user_data):
        _seed_data_dir(base_data, user_data)
    _clear_readonly_tree(user_data)
    return user_data


def _data_root_cache_key() -> tuple[str, bool, str]:
    override = (
        os.environ.get("NEXGEN_DATA_ROOT")
        or os.environ.get("NEXGEN_DATA_DIR")
        or ""
    ).strip()
    active_league_override = _normalize_league_id(
        os.environ.get("NEXGEN_ACTIVE_LEAGUE")
    ) or ""
    return (
        f"{override}|{active_league_override}",
        bool(getattr(sys, "frozen", False)),
        str(get_base_dir()),
    )


def get_data_root() -> Path:
    """Return writable root for NexGen league data."""

    global _DATA_ROOT, _DATA_ROOT_KEY
    cache_key = _data_root_cache_key()
    if _DATA_ROOT is not None and _DATA_ROOT_KEY == cache_key:
        return _DATA_ROOT
    _DATA_ROOT = _resolve_data_root()
    _DATA_ROOT_KEY = cache_key
    return _DATA_ROOT


def get_league_registry_path(*, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else get_data_root()
    return root / _LEAGUE_REGISTRY_FILENAME


def get_active_league_pointer_path(*, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else get_data_root()
    return root / _ACTIVE_LEAGUE_FILENAME


def get_leagues_root(*, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else get_data_root()
    return root / "leagues"


def _default_league_id_from_registry(registry_path: Path) -> str | None:
    if not registry_path.exists():
        return None
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        return None
    fallback: str | None = None
    for entry in leagues:
        if not isinstance(entry, dict):
            continue
        league_id = _normalize_league_id(str(entry.get("id") or ""))
        if not league_id:
            continue
        status = str(entry.get("status", "active")).strip().lower()
        if status != "archived":
            return league_id
        if fallback is None:
            fallback = league_id
    return fallback


def get_active_league_id(*, default: str | None = None) -> str | None:
    """Return current active league id when available."""

    env_value = _normalize_league_id(os.environ.get("NEXGEN_ACTIVE_LEAGUE"))
    if env_value:
        return env_value

    pointer = get_active_league_pointer_path()
    if pointer.exists():
        try:
            value = _normalize_league_id(pointer.read_text(encoding="utf-8"))
            if value:
                return value
        except OSError:
            pass

    fallback = _default_league_id_from_registry(get_league_registry_path())
    if fallback:
        return fallback
    return _normalize_league_id(default)


def set_active_league_id(league_id: str, *, data_root: Path | None = None) -> str:
    """Persist active league id and reset cached data-dir resolution."""

    normalized = _normalize_league_id(league_id)
    if not normalized:
        raise ValueError("league_id is required")
    pointer = get_active_league_pointer_path(data_root=data_root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(normalized, encoding="utf-8")
    global _DATA_DIR, _DATA_DIR_KEY
    _DATA_DIR = None
    _DATA_DIR_KEY = None
    return normalized


def clear_active_league_id(*, data_root: Path | None = None) -> None:
    pointer = get_active_league_pointer_path(data_root=data_root)
    try:
        if pointer.exists():
            pointer.unlink()
    except OSError:
        pass
    global _DATA_DIR, _DATA_DIR_KEY
    _DATA_DIR = None
    _DATA_DIR_KEY = None


def get_active_league_dir(
    *,
    data_root: Path | None = None,
    league_id: str | None = None,
    create: bool = False,
) -> Path | None:
    root = data_root if data_root is not None else get_data_root()
    resolved_id = _normalize_league_id(league_id) or get_active_league_id()
    if not resolved_id:
        return None
    league_dir = get_leagues_root(data_root=root) / resolved_id
    if create:
        league_dir.mkdir(parents=True, exist_ok=True)
    if create or league_dir.exists():
        return league_dir
    return None


def get_active_league_data_dir(
    *,
    data_root: Path | None = None,
    league_id: str | None = None,
    create: bool = False,
) -> Path | None:
    league_dir = get_active_league_dir(
        data_root=data_root,
        league_id=league_id,
        create=create,
    )
    if league_dir is None:
        return None
    data_dir = league_dir / "data"
    if create:
        data_dir.mkdir(parents=True, exist_ok=True)
    if create or data_dir.exists():
        return data_dir
    return None


def get_data_dir() -> Path:
    """Return active league data dir when configured, otherwise legacy root."""

    global _DATA_DIR, _DATA_DIR_KEY
    cache_key = _data_root_cache_key()
    if _DATA_DIR is not None and _DATA_DIR_KEY == cache_key:
        return _DATA_DIR
    _DATA_DIR = None
    _DATA_DIR_KEY = None

    data_root = get_data_root()
    active_data = get_active_league_data_dir(data_root=data_root, create=True)
    if active_data is not None:
        try:
            base_data = get_base_dir() / "data"
            _seed_data_dir(base_data, active_data)
            _clear_readonly_tree(active_data)
            _DATA_DIR = active_data
            _DATA_DIR_KEY = cache_key
            return _DATA_DIR
        except OSError:
            pass

    _DATA_DIR = data_root
    _DATA_DIR_KEY = cache_key
    return _DATA_DIR


def resolve_app_path(path: str | Path) -> Path:
    """Resolve *path* against data dir when rooted under data/, else base dir."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0].lower() == "data":
        return get_data_dir() / Path(*parts[1:])
    return get_base_dir() / candidate
