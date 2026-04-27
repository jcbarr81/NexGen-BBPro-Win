"""Reusable OpenAI client configured via environment or ``config.ini``.

Reads the API key from the ``OPENAI_API_KEY`` environment variable, falling
back to the ``[OpenAIkey]`` section of ``config.ini``. A singleton ``OpenAI``
client is created that can be imported anywhere in the project. If the
:mod:`openai` package is not installed or a key is missing, the ``client``
variable will be ``None``.
"""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Optional


try:  # pragma: no cover - gracefully handle missing dependency
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


CLIENT_STATUS_OK = "ok"
CLIENT_STATUS_MISSING_DEPENDENCY = "missing_dependency"
CLIENT_STATUS_MISSING_KEY = "missing_key"
CLIENT_STATUS_INIT_FAILED = "init_failed"


_CLIENT_STATUS_MESSAGES = {
    CLIENT_STATUS_MISSING_DEPENDENCY: (
        "Python package 'openai' is not installed. Install it with "
        "'pip install openai' to enable AI-generated logos."
    ),
    CLIENT_STATUS_MISSING_KEY: (
        "OpenAI API key was not found. Add it to the "
        "OPENAI_API_KEY environment variable or the [OpenAIkey] "
        "section in config.ini."
    ),
    CLIENT_STATUS_INIT_FAILED: (
        "OpenAI client initialization failed. Check the API key and network "
        "configuration."
    ),
}


def _candidate_config_paths() -> list[Path]:
    """Where ``config.ini`` might live.

    Priority: writable user data dir (where the AI Settings page now
    saves keys), then the bundle / dev base dir (legacy / dev only).
    First existing file wins.
    """

    candidates: list[Path] = []
    try:
        # Inline import to avoid bootstrapping path_utils before it's ready.
        from utils.path_utils import get_data_dir as _get_data_dir

        candidates.append(_get_data_dir() / "config.ini")
    except Exception:
        pass
    base_root = Path(__file__).resolve().parent.parent
    base_dir = Path(getattr(sys, "_MEIPASS", base_root))
    candidates.append(base_dir / "config.ini")
    return candidates


def _read_api_key() -> Optional[str]:
    """Return the OpenAI API key from environment or ``config.ini``."""

    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    config_path: Optional[Path] = None
    for cand in _candidate_config_paths():
        if cand.exists():
            config_path = cand
            break
    if config_path is None:
        # Fall through with a non-existent path — parser.read() handles
        # the missing file silently and we drop back to the no-key path.
        candidates = _candidate_config_paths()
        config_path = candidates[-1] if candidates else Path("config.ini")
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path)
    except configparser.Error:
        parser = None

    if parser:
        # Typical ``key=value`` entries
        for opt in ("key", "api_key", "OPENAI_API_KEY"):
            if parser.has_option("OpenAIkey", opt):
                return parser.get("OpenAIkey", opt)

        # Handle a section containing only the raw key on following lines
        if "OpenAIkey" in parser and not parser["OpenAIkey"]:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError:
                return None
            inside = False
            key_lines: list[str] = []
            for line in lines:
                if line.strip() == "[OpenAIkey]":
                    inside = True
                    continue
                if inside:
                    if line.startswith("["):
                        break
                    key_lines.append(line.strip())
            if key_lines:
                return "".join(key_lines).strip()

    # Fallback manual parsing when ``ConfigParser`` fails entirely
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    inside = False
    key_lines: list[str] = []
    for line in lines:
        if line.strip() == "[OpenAIkey]":
            inside = True
            continue
        if inside:
            if line.startswith("["):
                break
            key_lines.append(line.strip())
    if key_lines:
        return "".join(key_lines).strip()
    return None


_api_key = _read_api_key()

# Exposed, reusable OpenAI client instance. ``None`` if not configured.
client: Optional[OpenAI]
CLIENT_STATUS: str
CLIENT_ERROR: Optional[str]

if OpenAI is None:  # pragma: no cover - executed when dependency missing
    client = None
    CLIENT_STATUS = CLIENT_STATUS_MISSING_DEPENDENCY
    CLIENT_ERROR = _CLIENT_STATUS_MESSAGES[CLIENT_STATUS_MISSING_DEPENDENCY]
elif not _api_key:
    client = None
    CLIENT_STATUS = CLIENT_STATUS_MISSING_KEY
    CLIENT_ERROR = _CLIENT_STATUS_MESSAGES[CLIENT_STATUS_MISSING_KEY]
else:
    try:
        client = OpenAI(api_key=_api_key)
    except Exception as exc:  # pragma: no cover - protect against init errors
        client = None
        CLIENT_STATUS = CLIENT_STATUS_INIT_FAILED
        CLIENT_ERROR = f"OpenAI client initialization failed: {exc}"
    else:
        CLIENT_STATUS = CLIENT_STATUS_OK
        CLIENT_ERROR = None


def get_client_status_message() -> Optional[str]:
    """Return a human friendly explanation for the current client status."""

    if CLIENT_STATUS == CLIENT_STATUS_OK:
        return None
    if CLIENT_ERROR:
        return CLIENT_ERROR
    return _CLIENT_STATUS_MESSAGES.get(CLIENT_STATUS)


def get_client_status() -> str:
    """Return the symbolic status string for the configured client."""

    return CLIENT_STATUS


__all__ = [
    "client",
    "CLIENT_STATUS",
    "CLIENT_STATUS_OK",
    "CLIENT_STATUS_MISSING_DEPENDENCY",
    "CLIENT_STATUS_MISSING_KEY",
    "CLIENT_STATUS_INIT_FAILED",
    "get_client_status",
    "get_client_status_message",
]
