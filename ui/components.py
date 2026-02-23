"""Reusable UI components for consistent styling."""

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QToolButton,
    QFrame,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QWidget,
    QGridLayout,
)


def _call_if_exists(obj: Any, method: str, *args: Any, **kwargs: Any) -> None:
    """Invoke ``method`` on ``obj`` when available."""

    func = getattr(obj, method, None)
    if callable(func):
        try:
            func(*args, **kwargs)
        except Exception:
            pass


class NavButton(QToolButton):
    """Navigation button used in sidebars."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        _call_if_exists(self, "setObjectName", "NavButton")
        # Emoji icons keep dependencies light; swap for SVGs if you prefer
        _call_if_exists(self, "setText", text)  # e.g., "⚾  Dashboard"
        _call_if_exists(self, "setCheckable", True)
        style = getattr(Qt.ToolButtonStyle, "ToolButtonTextOnly", None)
        if style is not None:
            _call_if_exists(self, "setToolButtonStyle", style)
        policy_enum = getattr(QSizePolicy, "Policy", None)
        h_policy = getattr(policy_enum, "Expanding", None) if policy_enum else None
        v_policy = getattr(policy_enum, "Fixed", None) if policy_enum else None
        if h_policy is not None and v_policy is not None:
            _call_if_exists(self, "setSizePolicy", h_policy, v_policy)


class Card(QFrame):
    """Framed container with standard padding and layout."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _call_if_exists(self, "setObjectName", "Card")
        policy_enum = getattr(QSizePolicy, "Policy", None)
        h_policy = getattr(policy_enum, "Expanding", None) if policy_enum else None
        v_policy = getattr(policy_enum, "Minimum", None) if policy_enum else None
        if h_policy is not None and v_policy is not None:
            _call_if_exists(self, "setSizePolicy", h_policy, v_policy)
        shape_enum = getattr(QFrame, "Shape", None)
        frame_shape = getattr(shape_enum, "StyledPanel", None)
        if frame_shape is not None:
            _call_if_exists(self, "setFrameShape", frame_shape)
        layout = QVBoxLayout()
        self._fallback_layout = layout
        _call_if_exists(self, "setLayout", layout)
        _call_if_exists(layout, "setContentsMargins", 18, 18, 18, 18)
        _call_if_exists(layout, "setSpacing", 10)

    def layout(self):  # type: ignore[override]
        """Return the active layout, falling back to the stored layout for stubs."""

        base_layout = None
        try:
            base_method = getattr(super(), "layout", None)
            if callable(base_method):
                candidate = base_method()
                if candidate is not None and candidate is not self:
                    base_layout = candidate
        except Exception:
            base_layout = None
        return base_layout or getattr(self, "_fallback_layout", None)


def ensure_layout(widget: Any) -> Any:
    """Return a layout object for ``widget`` that supports layout operations."""

    layout_attr = getattr(widget, "layout", None)
    if callable(layout_attr):
        try:
            candidate = layout_attr()
            if candidate is not None and candidate is not widget:
                return candidate
        except TypeError:
            pass
    fallback = getattr(widget, "_fallback_layout", None)
    return fallback or layout_attr or widget


def section_title(text: str) -> QLabel:
    """Create a standardized section header label."""

    label = QLabel(text)
    _call_if_exists(label, "setObjectName", "SectionTitle")
    return label


def spacer(h: int = 1, v: int = 1) -> QSpacerItem:
    """Return a flexible spacer item for layouts."""

    return QSpacerItem(
        h,
        v,
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )


def metric_widget(
    title: str,
    value: str,
    *,
    highlight: bool = False,
    variant: str = "stat",
    tooltip: Optional[str] = None,
    on_click: Optional[Callable[[], None]] = None,
) -> QWidget:
    """Return a metric widget with styling variants for different content types."""

    container = QWidget()
    layout = QVBoxLayout(container)
    _call_if_exists(layout, "setContentsMargins", 0, 0, 0, 0)
    _call_if_exists(layout, "setSpacing", 4)

    policy_enum = getattr(QSizePolicy, "Policy", None)
    h_policy = getattr(policy_enum, "Expanding", None) if policy_enum else None
    v_policy = getattr(policy_enum, "Preferred", None) if policy_enum else None
    if h_policy is not None and v_policy is not None:
        _call_if_exists(container, "setSizePolicy", h_policy, v_policy)

    title_label = QLabel(title.upper())
    _call_if_exists(title_label, "setObjectName", "MetricLabel")
    _call_if_exists(title_label, "setProperty", "variant", variant)

    alignment_flag = getattr(Qt, "AlignmentFlag", None)
    align_left = getattr(alignment_flag, "AlignLeft", None)
    align_v_center = getattr(alignment_flag, "AlignVCenter", None)

    if variant == "leader" and align_left is not None:
        _call_if_exists(
            title_label,
            "setAlignment",
            align_left | (align_v_center or 0),
        )

    value_label = QLabel(value)
    _call_if_exists(value_label, "setObjectName", "MetricValue")
    _call_if_exists(value_label, "setProperty", "variant", variant)
    if highlight:
        _call_if_exists(value_label, "setProperty", "highlight", True)
    _call_if_exists(value_label, "setWordWrap", True)
    if h_policy is not None and v_policy is not None:
        _call_if_exists(value_label, "setSizePolicy", h_policy, v_policy)

    if variant == "leader" and align_left is not None:
        _call_if_exists(
            value_label,
            "setAlignment",
            align_left | (align_v_center or 0),
        )

    interactive = bool(on_click)
    _call_if_exists(value_label, "setProperty", "interactive", interactive)
    if tooltip:
        _call_if_exists(value_label, "setToolTip", tooltip)
    if interactive and on_click is not None:
        _attach_click_handler(value_label, on_click)

    _call_if_exists(layout, "addWidget", title_label)
    _call_if_exists(layout, "addWidget", value_label)
    _call_if_exists(layout, "addStretch")
    return container


def build_metric_row(
    pairs: list[tuple[str, str]],
    *,
    columns: int = 4,
    variant: str = "stat",
) -> QWidget:
    wrapper = QWidget()
    grid = QGridLayout(wrapper)
    _call_if_exists(grid, "setContentsMargins", 0, 0, 0, 0)
    _call_if_exists(grid, "setSpacing", 18)
    for idx, (title, value) in enumerate(pairs):
        row = idx // columns
        col = idx % columns
        text, options = _normalize_metric_value(value)
        _call_if_exists(
            grid,
            "addWidget",
            metric_widget(
                title,
                text,
                variant=variant,
                highlight=options.get("highlight", False),
                tooltip=options.get("tooltip"),
                on_click=options.get("on_click"),
            ),
            row,
            col,
        )

    for col in range(columns):
        _call_if_exists(grid, "setColumnStretch", col, 1)
    return wrapper


def _normalize_metric_value(
    value: Any,
) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        text = str(value.get("text", "--"))
        return text, {
            "highlight": bool(value.get("highlight", False)),
            "tooltip": value.get("tooltip"),
            "on_click": value.get("on_click"),
        }
    if value is None:
        return "--", {"highlight": False, "tooltip": None, "on_click": None}
    return str(value), {"highlight": False, "tooltip": None, "on_click": None}


def _attach_click_handler(label: Any, callback: Callable[[], None]) -> None:
    """Attach a simple left-click handler to the provided label widget."""

    if not callable(callback):
        return

    original = getattr(label, "mousePressEvent", None)

    def _handler(event) -> None:
        try:
            button = getattr(event, "button", None)
            btn_val = button() if callable(button) else None
            left_button = getattr(Qt.MouseButton, "LeftButton", None)
            if left_button is not None and btn_val not in (left_button, None):
                if callable(original):
                    original(event)
                return
        except Exception:
            pass
        try:
            callback()
        except Exception:
            pass
        if callable(original):
            try:
                original(event)
            except Exception:
                pass

    try:
        cursor = getattr(Qt.CursorShape, "PointingHandCursor", None)
        if cursor is not None:
            _call_if_exists(label, "setCursor", cursor)
    except Exception:
        pass

    setattr(label, "mousePressEvent", _handler)
