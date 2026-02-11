from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import stat


_DATA_DIR: Path | None = None
_MINIMAL_DATA_FILES = (
    "names.csv",
    "ballparks.py",
    "draft_config.json",
    "injury_catalog.json",
)
_MINIMAL_DATA_DIRS = (
    "MLB_avg",
    "parks",
)


def get_base_dir() -> Path:
    """Return project root or PyInstaller's temporary directory."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


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


def get_data_dir() -> Path:
    """Return writable data directory, seeding from bundled data when needed."""
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR

    base_dir = get_base_dir()
    base_data = base_dir / "data"
    running_frozen = bool(getattr(sys, "frozen", False))

    override = os.environ.get("NEXGEN_DATA_DIR")
    if override:
        candidate = Path(override)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _seed_data_dir(base_data, candidate)
            _DATA_DIR = candidate
            return _DATA_DIR
        except OSError:
            pass

    if not running_frozen and _can_write_dir(base_data):
        _DATA_DIR = base_data
        return _DATA_DIR

    local_app = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local_app:
        user_data = Path(local_app) / "NexGen-BBPro" / "data"
    else:
        user_data = Path.home() / ".nexgen-bbpro" / "data"

    try:
        user_data.mkdir(parents=True, exist_ok=True)
    except OSError:
        _DATA_DIR = base_data
        return _DATA_DIR

    _seed_data_dir(base_data, user_data)
    _clear_readonly_tree(user_data)
    _DATA_DIR = user_data
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
