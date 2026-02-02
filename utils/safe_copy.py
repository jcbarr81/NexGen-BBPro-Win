"""Fallback deep copy helpers used when stdlib ``copy`` is unavailable."""

from __future__ import annotations

from typing import Any, TypeVar
import types

try:  # pragma: no cover - exercised when stdlib copy is healthy
    import copy as _copy
except Exception:  # pragma: no cover - defensive fallback
    _copy = None

T = TypeVar("T")

_IMMUTABLE_TYPES = (
    int,
    float,
    bool,
    str,
    bytes,
    type(None),
    complex,
    range,
    type,
)


def deepcopy(value: T) -> T:
    """Return a deep copy of ``value`` with a resilient fallback."""

    copier = getattr(_copy, "deepcopy", None) if _copy is not None else None
    if callable(copier) and copier is not deepcopy:
        return copier(value)
    return _deepcopy_fallback(value, {})


def _deepcopy_fallback(value: T, memo: dict[int, Any]) -> T:
    obj_id = id(value)
    if obj_id in memo:
        return memo[obj_id]

    if isinstance(value, _IMMUTABLE_TYPES):
        return value

    if isinstance(
        value,
        (
            types.FunctionType,
            types.BuiltinFunctionType,
            types.MethodType,
            types.ModuleType,
        ),
    ):
        return value

    if isinstance(value, dict):
        dup = value.__class__()
        memo[obj_id] = dup
        for key, item in value.items():
            dup[_deepcopy_fallback(key, memo)] = _deepcopy_fallback(item, memo)
        return dup

    if isinstance(value, list):
        dup: list[Any] = []
        memo[obj_id] = dup
        dup.extend(_deepcopy_fallback(item, memo) for item in value)
        return dup

    if isinstance(value, tuple):
        dup = tuple(_deepcopy_fallback(item, memo) for item in value)
        memo[obj_id] = dup
        return dup

    if isinstance(value, set):
        dup: set[Any] = set()
        memo[obj_id] = dup
        for item in value:
            dup.add(_deepcopy_fallback(item, memo))
        return dup

    if isinstance(value, frozenset):
        dup = frozenset(_deepcopy_fallback(item, memo) for item in value)
        memo[obj_id] = dup
        return dup

    if isinstance(value, bytearray):
        dup = bytearray(value)
        memo[obj_id] = dup
        return dup

    if isinstance(value, memoryview):
        dup = memoryview(value.tobytes())
        memo[obj_id] = dup
        return dup

    getstate = getattr(value, "__getstate__", None)
    setstate = getattr(value, "__setstate__", None)
    if callable(getstate) and callable(setstate):
        try:
            state = getstate()
        except Exception:
            state = None
        try:
            dup = value.__class__.__new__(value.__class__)
        except Exception:
            return value
        memo[obj_id] = dup
        if state is not None:
            try:
                dup.__setstate__(_deepcopy_fallback(state, memo))
                return dup
            except Exception:
                pass
        return dup

    try:
        dup = value.__class__.__new__(value.__class__)
    except Exception:
        return value

    memo[obj_id] = dup

    if hasattr(value, "__dict__"):
        try:
            dup.__dict__.update(_deepcopy_fallback(value.__dict__, memo))
        except Exception:
            pass

    slots = getattr(value.__class__, "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    for slot in slots:
        if slot.startswith("__") and slot.endswith("__"):
            continue
        if hasattr(value, slot):
            try:
                setattr(dup, slot, _deepcopy_fallback(getattr(value, slot), memo))
            except Exception:
                pass
    return dup


__all__ = ["deepcopy"]
