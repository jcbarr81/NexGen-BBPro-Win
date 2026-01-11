from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover - test stubs
    QtCore = SimpleNamespace(
        Qt=SimpleNamespace(
            AspectRatioMode=SimpleNamespace(KeepAspectRatio=None),
            TransformationMode=SimpleNamespace(SmoothTransformation=None),
            GlobalColor=SimpleNamespace(transparent=None),
            AlignmentFlag=SimpleNamespace(AlignCenter=None),
        )
    )

    class _PixmapStub:
        def __init__(self, *args, **kwargs) -> None:
            self._is_null = True

        def isNull(self) -> bool:
            return self._is_null

        def scaled(self, *args, **kwargs):
            return self

        def fill(self, *args, **kwargs) -> None:
            self._is_null = False

        def size(self):
            return SimpleNamespace()

    class _PainterStub:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def drawPixmap(self, *args, **kwargs) -> None:
            return None

        def end(self) -> None:
            return None

    class _LabelStub:
        def __init__(self, *args, **kwargs) -> None:
            self._text = ""

        def setAlignment(self, *args, **kwargs) -> None:
            return None

        def setPixmap(self, *args, **kwargs) -> None:
            return None

        def setFixedSize(self, *args, **kwargs) -> None:
            return None

        def setStyleSheet(self, *args, **kwargs) -> None:
            return None

        def setText(self, text: str) -> None:
            self._text = text

    QtGui = SimpleNamespace(QPixmap=_PixmapStub, QPainter=_PainterStub)
    QtWidgets = SimpleNamespace(QLabel=_LabelStub)

from utils.path_utils import get_base_dir

STAR_COUNT = 5


def _asset_path(name: str) -> Path:
    return Path(get_base_dir()) / "assets" / name


def _quantize_stars(value: float) -> float:
    return math.floor(value * 2 + 0.5) / 2.0


def star_rating_value(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if max_rating <= min_rating:
        return 1.0
    clamped = max(min_rating, min(max_rating, numeric))
    normalized = (clamped - min_rating) / (max_rating - min_rating)
    stars = 1.0 + normalized * 4.0
    stars = _quantize_stars(stars)
    return max(1.0, min(5.0, stars))


def star_text(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
) -> Optional[str]:
    stars = star_rating_value(value, min_rating=min_rating, max_rating=max_rating)
    if stars is None:
        return None
    if stars.is_integer():
        return str(int(stars))
    return f"{stars:.1f}"


def _star_steps(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
) -> Optional[int]:
    stars = star_rating_value(value, min_rating=min_rating, max_rating=max_rating)
    if stars is None:
        return None
    return int(round(stars * 2))


@lru_cache(maxsize=12)
def _load_star_pixmap(kind: str, size: int) -> QtGui.QPixmap:
    path = _asset_path(f"{kind}_star.png")
    pix = QtGui.QPixmap(str(path))
    if pix.isNull():
        return pix
    return pix.scaled(
        size,
        size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=32)
def _star_bar_pixmap(steps: int, size: int) -> QtGui.QPixmap:
    width = size * STAR_COUNT
    bar = QtGui.QPixmap(width, size)
    bar.fill(QtCore.Qt.GlobalColor.transparent)

    full_star = _load_star_pixmap("full", size)
    half_star = _load_star_pixmap("half", size)
    if full_star.isNull() or half_star.isNull():
        return QtGui.QPixmap()

    full_count = min(steps // 2, STAR_COUNT)
    half_count = 1 if steps % 2 else 0
    painter = QtGui.QPainter(bar)
    for idx in range(STAR_COUNT):
        x = idx * size
        if idx < full_count:
            painter.drawPixmap(x, 0, full_star)
        elif idx == full_count and half_count:
            painter.drawPixmap(x, 0, half_star)
    painter.end()
    return bar


def star_pixmap(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
    size: int = 12,
) -> Optional[QtGui.QPixmap]:
    steps = _star_steps(value, min_rating=min_rating, max_rating=max_rating)
    if steps is None:
        return None
    pix = _star_bar_pixmap(steps, size)
    if pix.isNull():
        return None
    return pix


def star_label(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
    size: int = 12,
    fixed_size: bool = True,
) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel()
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    pix = star_pixmap(
        value,
        min_rating=min_rating,
        max_rating=max_rating,
        size=size,
    )
    if pix is None:
        fallback = star_text(value, min_rating=min_rating, max_rating=max_rating)
        label.setText(fallback if fallback is not None else str(value))
        return label
    label.setPixmap(pix)
    if fixed_size:
        label.setFixedSize(pix.size())
    label.setStyleSheet("background: transparent;")
    return label
