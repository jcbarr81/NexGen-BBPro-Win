from __future__ import annotations

"""Helpers to persist flags in ``season_progress.json`` safely."""

import json
import os
import time
from pathlib import Path
from typing import Any

from utils.path_utils import get_data_dir


def _progress_path() -> Path:
    return get_data_dir() / "season_progress.json"


# Backward-compatible default path handle for callers that import this symbol.
PROGRESS_PATH = _progress_path()


class ProgressUpdateError(RuntimeError):
    """Raised when ``season_progress.json`` could not be updated reliably."""


def mark_draft_completed(
    year: int,
    *,
    progress_path: Path | None = None,
    retries: int = 6,
    delay: float = 0.05,
) -> None:
    """Ensure ``year`` is present in ``draft_completed_years``."""

    path = Path(progress_path) if progress_path is not None else _progress_path()
    year_int = int(year)
    try:
        progress = _load_progress(path, retries=retries, delay=delay)
    except Exception as exc:
        raise ProgressUpdateError(f"Unable to read {path.name}: {exc}") from exc

    completed = _normalized_years(progress.get("draft_completed_years", []))
    if year_int not in completed:
        completed.add(year_int)
        progress["draft_completed_years"] = sorted(completed)
        try:
            _write_progress(path, progress, retries=retries, delay=delay)
        except Exception as exc:
            raise ProgressUpdateError(f"Unable to write {path.name}: {exc}") from exc
    else:
        # Still write the merged payload so we persist any other changes (e.g., keys added elsewhere).
        try:
            _write_progress(path, progress, retries=retries, delay=delay)
        except Exception as exc:
            raise ProgressUpdateError(f"Unable to write {path.name}: {exc}") from exc


def mark_playoffs_completed(
    *,
    progress_path: Path | None = None,
    retries: int = 6,
    delay: float = 0.05,
) -> None:
    """Ensure the ``playoffs_done`` flag in ``season_progress.json`` is set."""

    path = Path(progress_path) if progress_path is not None else _progress_path()
    try:
        progress = _load_progress(path, retries=retries, delay=delay)
    except Exception as exc:
        raise ProgressUpdateError(f"Unable to read {path.name}: {exc}") from exc

    if not progress.get("playoffs_done"):
        progress["playoffs_done"] = True
    try:
        _write_progress(path, progress, retries=retries, delay=delay)
    except Exception as exc:
        raise ProgressUpdateError(f"Unable to write {path.name}: {exc}") from exc


def _load_progress(path: Path, *, retries: int, delay: float) -> dict[str, Any]:
    last_exc: Exception | None = None
    attempts = max(int(retries), 1)
    for attempt in range(attempts):
        try:
            if not path.exists():
                return {}
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return {}
            return json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            last_exc = exc
            if attempt == attempts - 1:
                break
            time.sleep(max(delay, 0.0))
    if last_exc is not None:
        raise last_exc
    return {}


def _write_progress(path: Path, payload: dict[str, Any], *, retries: int, delay: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(int(retries), 1)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        suffix = f".tmp.{os.getpid()}.{int(time.time() * 1_000_000)}.{attempt}"
        tmp_path = path.with_suffix(path.suffix + suffix)
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # Omit fsync failures on platforms that do not support it for text files.
                    pass
            os.replace(tmp_path, path)
            return
        except Exception as exc:
            last_exc = exc
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            if attempt == attempts - 1:
                break
            time.sleep(max(delay, 0.0))
    if last_exc is not None:
        raise last_exc


def _normalized_years(values: list[Any]) -> set[int]:
    years: set[int] = set()
    for value in values:
        try:
            years.add(int(value))
        except Exception:
            continue
    return years


__all__ = [
    "mark_draft_completed",
    "mark_playoffs_completed",
    "ProgressUpdateError",
    "PROGRESS_PATH",
]
