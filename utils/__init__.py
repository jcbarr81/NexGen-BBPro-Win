"""Utility package for UBL."""

from __future__ import annotations

import copy as _copy

from utils.safe_copy import deepcopy as _safe_deepcopy


if not callable(getattr(_copy, "deepcopy", None)):
    _copy.deepcopy = _safe_deepcopy  # type: ignore[attr-defined]

__all__: list[str] = []
