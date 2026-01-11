"""Retro-style dialog showing a team's position players roster.

This refactors the previous tabbed dialog into a single table that mimics the
retro roster mock-up found in ``samples/Roster-Sample.py``. Sample data is
replaced with the real data for the team being viewed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from PyQt6 import QtCore, QtGui, QtWidgets

from ui.player_profile_dialog import PlayerProfileDialog

from models.base_player import BasePlayer
from models.roster import Roster
from utils.pitcher_role import get_role
from utils.rating_display import (
    rating_display_details,
    rating_display_text,
    rating_display_value,
)


# ---------------------------------------------------------------------------
# Retro colour palette
RETRO_GREEN = "#0f3b19"
RETRO_GREEN_DARK = "#0b2a12"
RETRO_GREEN_TABLE = "#164a22"
RETRO_BEIGE = "#d2ba8f"
RETRO_YELLOW = "#ffd34d"
RETRO_TEXT = "#ffffff"
RETRO_CYAN = "#6ce5ff"
RETRO_BORDER = "#3a5f3a"

COLUMNS = [
    "NO.",
    "Player Name",
    "AGE",
    "SLOT",
    "POSN",
    "B",
    "CH",
    "PH",
    "SP",
    "FA",
    "AS",
]

RATING_COLUMNS = {"CH", "PH", "SP", "FA", "AS"}


class NumberDelegate(QtWidgets.QStyledItemDelegate):
    """Right align numeric cells and tint them retro cyan."""

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        header = index.model().headerData(
            index.column(), QtCore.Qt.Orientation.Horizontal
        )
        is_numeric_col = header in {"NO.", "AGE", "CH", "PH", "SP", "FA", "AS"}
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if is_numeric_col:
            opt.displayAlignment = (
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            opt.palette.setColor(
                QtGui.QPalette.ColorRole.Text, QtGui.QColor(RETRO_CYAN)
            )
        else:
            opt.displayAlignment = (
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            opt.palette.setColor(
                QtGui.QPalette.ColorRole.Text, QtGui.QColor(RETRO_TEXT)
            )
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(
            QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget
        )


class SlotItem(QtWidgets.QTableWidgetItem):
    """Table item that sorts roster slots in a custom order."""

    slot_order = {"LOW": 0, "AAA": 1, "ACT": 2}

    def __lt__(self, other: QtWidgets.QTableWidgetItem) -> bool:  # type: ignore[override]
        left = self.slot_order.get(self.text(), 99)
        right = self.slot_order.get(other.text(), 99)
        return left < right


class NumericItem(QtWidgets.QTableWidgetItem):
    """Item that stores numeric sort keys when possible."""

    def __lt__(self, other: QtWidgets.QTableWidgetItem) -> bool:  # type: ignore[override]
        left = self.data(QtCore.Qt.ItemDataRole.EditRole)
        right = other.data(QtCore.Qt.ItemDataRole.EditRole)
        if left is None or right is None:
            return super().__lt__(other)
        try:
            return float(left) < float(right)
        except (TypeError, ValueError):
            return super().__lt__(other)

    def __init__(
        self,
        value: object,
        *,
        align_left: bool = False,
        display_value: object | None = None,
        sort_value: object | None = None,
    ) -> None:
        super().__init__()
        flags = self.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
        self.setFlags(flags)
        alignment = (
            QtCore.Qt.AlignmentFlag.AlignLeft
            if align_left
            else QtCore.Qt.AlignmentFlag.AlignRight
        )
        self.setTextAlignment(alignment | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._set_value(value, display_value=display_value, sort_value=sort_value)

    def _set_value(
        self,
        value: object,
        *,
        display_value: object | None = None,
        sort_value: object | None = None,
    ) -> None:
        numeric_source = value if sort_value is None else sort_value
        try:
            numeric = float(numeric_source)
        except (TypeError, ValueError):
            display = value if display_value is None else display_value
            self.setData(QtCore.Qt.ItemDataRole.DisplayRole, str(display))
        else:
            if display_value is None:
                display = int(numeric) if numeric.is_integer() else numeric
            else:
                display = display_value
            self.setData(QtCore.Qt.ItemDataRole.DisplayRole, display)
            self.setData(QtCore.Qt.ItemDataRole.EditRole, numeric)


class RetroHeader(QtWidgets.QWidget):
    """Header area displaying team name and subheader strip."""

    def __init__(self, team_id: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"background:{RETRO_GREEN}; border-bottom: 1px solid {RETRO_BORDER};"
        )

        title = QtWidgets.QLabel(f"Team Roster — {team_id}")
        title_font = QtGui.QFont("Segoe UI", 16, QtGui.QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #ff6b6b; letter-spacing: 0.5px;")

        strip = QtWidgets.QFrame()
        strip.setStyleSheet(
            f"background:{RETRO_GREEN_DARK}; border: 1px solid {RETRO_BORDER};"
        )
        strip_layout = QtWidgets.QHBoxLayout(strip)
        strip_layout.setContentsMargins(10, 6, 10, 6)
        strip_layout.setSpacing(8)

        team_line = QtWidgets.QLabel(team_id)
        team_line.setStyleSheet(f"color:{RETRO_YELLOW}; font-weight:600;")
        season = QtWidgets.QLabel("Season data")
        season.setStyleSheet(f"color:{RETRO_YELLOW};")

        arrow = QtWidgets.QLabel("▲")
        arrow.setStyleSheet(f"color:{RETRO_YELLOW}; font-weight:700;")
        arrow.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        strip_layout.addWidget(team_line, 1)
        strip_layout.addWidget(season)
        strip_layout.addStretch(1)
        strip_layout.addWidget(arrow)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        lay.addWidget(title)
        lay.addWidget(strip)


class RosterTable(QtWidgets.QTableWidget):
    """Table displaying the team's position players."""
    hidden_columns: set[int] = set()

    def __init__(
        self,
        rows: List[List],
        parent: QtWidgets.QWidget | None = None,
        *,
        use_position_context: bool = False,
    ):
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.setRowCount(len(rows))
        pos_index = COLUMNS.index("POSN")
        for r, row in enumerate(rows):
            *data, pid = row
            for c, val in enumerate(data):
                column = COLUMNS[c]
                if column == "SLOT":
                    item = SlotItem(str(val))
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignCenter
                        | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
                else:
                    align_left = column in {"Player Name", "POSN", "B"}
                    display_value = None
                    sort_value = val if column in RATING_COLUMNS else None
                    if column in RATING_COLUMNS:
                        if use_position_context:
                            position = row[pos_index]
                            (
                                display_rating,
                                top_pct,
                                avg_rating,
                                bucket,
                            ) = rating_display_details(
                                val,
                                key=column,
                                position=position,
                                is_pitcher=False,
                                curve="logistic",
                                curve_k=6.0,
                                display_min=35,
                                display_max=99,
                            )
                            display_value = str(display_rating)
                            if top_pct is not None:
                                display_value = f"{display_value} ({top_pct}%)"
                                avg_text = (
                                    "--"
                                    if avg_rating is None
                                    else str(int(round(avg_rating)))
                                )
                                bucket_label = bucket or position or "ALL"
                                tooltip = (
                                    f"Top {top_pct}% {bucket_label} "
                                    f"(avg {avg_text})"
                                )
                            else:
                                tooltip = None
                            sort_value = (
                                display_rating
                                if isinstance(display_rating, (int, float))
                                else None
                            )
                        else:
                            display_value = rating_display_value(
                                val,
                                key=column,
                                is_pitcher=False,
                            )
                            tooltip = None
                    item = NumericItem(
                        val,
                        align_left=align_left,
                        display_value=display_value,
                        sort_value=sort_value,
                    )
                    if column in RATING_COLUMNS and use_position_context:
                        if tooltip:
                            item.setToolTip(tooltip)
                if c == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, pid)
                self.setItem(r, c, item)

        widths = [50, 220, 50, 60, 60, 40, 60, 60, 60, 60, 60]
        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)

        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        self.setAlternatingRowColors(False)

        self.setStyleSheet(
            f"QTableWidget {{ background:{RETRO_GREEN_TABLE}; color:{RETRO_TEXT};"
            f" gridline-color:{RETRO_BORDER}; selection-background-color:#245b2b;"
            f" selection-color:{RETRO_TEXT}; font: 12px 'Segoe UI'; }}"
            f"QHeaderView::section {{ background:{RETRO_GREEN}; color:{RETRO_TEXT};"
            f" border: 1px solid {RETRO_BORDER}; font-weight:600; }}"
            f"QScrollBar:vertical {{ background:{RETRO_GREEN_DARK}; width: 12px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background:{RETRO_BEIGE}; min-height: 24px; }}"
        )

        delegate = NumberDelegate(self)
        self.setItemDelegate(delegate)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setDefaultAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.horizontalHeader().setSectionsClickable(True)
        self.setSortingEnabled(True)
        self._init_column_menu()

    def _init_column_menu(self) -> None:
        header = self.horizontalHeader()
        header.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        header.customContextMenuRequested.connect(self._show_column_menu)
        for col in type(self).hidden_columns:
            if 0 <= col < self.columnCount():
                self.setColumnHidden(col, True)

    def _show_column_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        header = self.horizontalHeader()
        for i, label in enumerate(COLUMNS):
            action = QtGui.QAction(label, self, checkable=True)
            action.setChecked(not self.isColumnHidden(i))
            action.toggled.connect(
                lambda checked, col=i: self._toggle_column(col, checked)
            )
            menu.addAction(action)
        menu.exec(header.mapToGlobal(pos))

    def _toggle_column(self, col: int, visible: bool) -> None:
        self.setColumnHidden(col, not visible)
        if visible:
            type(self).hidden_columns.discard(col)
        else:
            type(self).hidden_columns.add(col)


class StatusFooter(QtWidgets.QStatusBar):
    """Simple status bar matching the retro palette."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{RETRO_GREEN}; color:{RETRO_TEXT};"
            f" border-top: 1px solid {RETRO_BORDER};"
        )
        self.setSizeGripEnabled(False)

        left = QtWidgets.QLabel("NexGen-BBpro")
        right = QtWidgets.QLabel("JBARR 2025")
        right.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )

        container = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(container)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(left)
        lay.addWidget(spacer)
        lay.addWidget(right)

        self.addPermanentWidget(container, 1)


class PositionPlayersDialog(QtWidgets.QDialog):
    """Display all position players in a retro roster table."""

    def __init__(
        self,
        players: Dict[str, BasePlayer],
        roster: Roster,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.players = players
        self.roster = roster

        self.setWindowTitle("Position Players")
        self.resize(1100, 650)
        self._apply_global_palette()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.header = RetroHeader(roster.team_id)
        layout.addWidget(self.header)

        rows = self._build_rows()
        self.table = RosterTable(rows)
        self.table.itemDoubleClicked.connect(self._open_player_profile)

        header = self.table.horizontalHeader()
        header.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        header.customContextMenuRequested.connect(self._show_columns_menu)

        self.columns_menu = QtWidgets.QMenu("Columns", self)
        for index, label in enumerate(COLUMNS):
            action = self.columns_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(
                lambda checked, i=index: self.table.setColumnHidden(i, not checked)
            )

        layout.addWidget(self.table, 1)

        self.statusbar = StatusFooter()
        layout.addWidget(self.statusbar)

    # ------------------------------------------------------------------
    # Column visibility menu
    def _show_columns_menu(self, pos: QtCore.QPoint) -> None:
        """Display the column toggle menu."""

        header = self.table.horizontalHeader()
        self.columns_menu.exec(header.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Data helpers
    def _build_rows(self) -> List[List]:
        """Create table rows for all non-pitchers across roster levels."""

        rows: List[List] = []
        seq = 1
        for slot, ids in (
            ("ACT", self.roster.act),
            ("AAA", self.roster.aaa),
            ("LOW", self.roster.low),
        ):
            for pid in ids:
                p = self.players.get(pid)
                if not p or get_role(p):
                    continue
                age = self._calculate_age(p.birthdate)
                rows.append(
                    [
                        seq,
                        f"{p.last_name}, {p.first_name}",
                        age,
                        slot,
                        p.primary_position,
                        p.bats,
                        getattr(p, "ch", 0),
                        getattr(p, "ph", 0),
                        getattr(p, "sp", 0),
                        getattr(p, "fa", 0),
                        getattr(p, "arm", 0),
                        pid,
                    ]
                )
                seq += 1
        return rows

    # ------------------------------------------------------------------
    # Helpers for tests and compatibility
    def _make_player_item(self, p: BasePlayer) -> QtWidgets.QListWidgetItem:
        """Format a player entry similar to OwnerDashboard._make_player_item."""

        age = self._calculate_age(p.birthdate)
        role = get_role(p)
        if role:
            arm_display = rating_display_text(
                getattr(p, "arm", 0), key="AS", is_pitcher=True
            )
            endurance_display = rating_display_text(
                getattr(p, "endurance", 0), key="EN", is_pitcher=True
            )
            control_display = rating_display_text(
                getattr(p, "control", 0), key="CO", is_pitcher=True
            )
            core = (
                f"AS:{arm_display} EN:{endurance_display} "
                f"CO:{control_display}"
            )
        else:
            ch_display = rating_display_text(
                getattr(p, "ch", 0), key="CH", is_pitcher=False
            )
            ph_display = rating_display_text(
                getattr(p, "ph", 0), key="PH", is_pitcher=False
            )
            sp_display = rating_display_text(
                getattr(p, "sp", 0), key="SP", is_pitcher=False
            )
            core = f"CH:{ch_display} PH:{ph_display} SP:{sp_display}"
        label = (
            f"{p.first_name} {p.last_name} ({age}) - {role or p.primary_position} | {core}"
        )
        item = QtWidgets.QListWidgetItem(label)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, p.player_id)
        return item

    def _calculate_age(self, birthdate_str: str):
        try:
            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            return today.year - birthdate.year - (
                (today.month, today.day) < (birthdate.month, birthdate.day)
            )
        except Exception:
            return "?"

    # ------------------------------------------------------------------
    # Player profile dialog
    def _open_player_profile(self, item: QtWidgets.QTableWidgetItem):
        """Open the player profile dialog for the selected table row."""

        row = item.row()
        pid_item = self.table.item(row, 0)
        if not pid_item:
            return
        pid = pid_item.data(QtCore.Qt.ItemDataRole.UserRole)
        player = self.players.get(pid)
        if not player:
            return
        PlayerProfileDialog(player, self).exec()

    # ------------------------------------------------------------------
    # Palette helpers
    def _apply_global_palette(self) -> None:
        pal = self.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(RETRO_GREEN))
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(RETRO_GREEN_TABLE))
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(RETRO_TEXT))
        pal.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(RETRO_BEIGE))
        pal.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#222"))
        self.setPalette(pal)
        self.setStyleSheet(
            f"QDialog {{ background:{RETRO_GREEN}; }}"
            f"QPushButton {{ background:{RETRO_BEIGE}; color:#222; }}"
        )

