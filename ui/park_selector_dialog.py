from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from data.ballparks import BALLPARKS
from utils.path_utils import get_base_dir


@dataclass
class Park:
    park_id: str
    name: str
    year: int


def _project_root() -> Path:
    return get_base_dir()


def _park_config_path() -> Path:
    root = _project_root()
    primary = root / "data" / "parks" / "ParkConfig.csv"
    if primary.exists():
        return primary
    return root / "data" / "ballparks" / "ParkConfig.csv"


def _fallback_parks() -> List[Park]:
    return [Park(park_id="", name=name, year=0) for name in sorted(BALLPARKS)]


def _park_label(park: Park) -> str:
    if park.year and park.year > 0:
        return f"{park.name} ({park.year})"
    return park.name


def _load_latest_parks(csv_path: Optional[Path] = None) -> List[Park]:
    """Return latest-year parks that have at least one dimension recorded.

    A park is included only if at least one ``*_Dim`` field can be parsed as
    a float for that park in any year. Among the qualifying rows for each
    park, the most recent year is selected.
    """

    path = csv_path or _park_config_path()
    if not path.exists():
        return _fallback_parks()
    latest: Dict[str, Park] = {}
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                park_id = (row.get("parkID") or row.get("ParkID") or "").strip()
                name = (row.get("NAME") or row.get("Name") or "").strip()
                try:
                    year = int(row.get("Year") or 0)
                except Exception:
                    continue
                if not park_id or not name:
                    continue

                # Count any numeric dimension fields in this row (e.g., LF_Dim, CF_Dim, etc.)
                has_dim = False
                for k, v in row.items():
                    if not k or not k.endswith("_Dim"):
                        continue
                    try:
                        if v is not None and str(v).strip() != "" and float(str(v)):
                            has_dim = True
                            break
                    except Exception:
                        continue
                if not has_dim:
                    # Skip rows without any dimension data
                    continue

                p = Park(park_id=park_id, name=name, year=year)
                # Keep the most recent qualifying row per park
                if park_id not in latest or year > latest[park_id].year:
                    latest[park_id] = p
    except Exception:
        return _fallback_parks()
    if not latest:
        return _fallback_parks()
    return sorted(latest.values(), key=lambda p: p.name)


class ParkSelectorDialog(QDialog):
    """Allows choosing a ballpark from ParkConfig with a simple preview."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Stadium")
        self._parks = _load_latest_parks()
        self.selected_name: Optional[str] = None
        self.selected_park_id: Optional[str] = None

        root = QVBoxLayout(self)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter by name")
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_edit)
        root.addLayout(filter_row)

        # List + Preview
        main_row = QHBoxLayout()

        self.list = QListWidget()
        for p in self._parks:
            item = QListWidgetItem(_park_label(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._update_preview)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 320)
        self.preview.setStyleSheet("background:#222; color:#ddd;")
        self.preview.setText("Select a park to preview")

        main_row.addWidget(self.list, 2)
        main_row.addWidget(self.preview, 3)
        root.addLayout(main_row)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_use = QPushButton("Use Stadium")
        self.btn_use.clicked.connect(self._accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_use)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

        # Default select first item
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _apply_filter(self, text: str) -> None:
        text = (text or "").lower()
        self.list.clear()
        for p in self._parks:
            label = _park_label(p)
            if text in p.name.lower():
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.list.addItem(item)

    def _update_preview(self, item: Optional[QListWidgetItem]) -> None:
        if not item:
            return
        p: Park = item.data(Qt.ItemDataRole.UserRole)
        self.selected_name = p.name
        self.selected_park_id = p.park_id or None

        if not p.park_id or p.year <= 0:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"{p.name}\n(No preview available)")
            return

        # Try to show a generated image if present
        img_path = _project_root() / "images" / "parks" / f"{p.park_id}_{p.year}.png"
        if not img_path.exists():
            # Generate on-demand using the generator module
            try:
                from scripts import generate_park_diagrams as gen
                # Load all parks, filter to this one, and render
                parks = gen.load_parks(_park_config_path())
                parks = [r for r in parks if r.park_id == p.park_id and r.year == p.year]
                if parks:
                    img_path.parent.mkdir(parents=True, exist_ok=True)
                    gen.draw_diagram(parks[0], img_path)
            except Exception:
                pass

        if img_path.exists():
            pix = QPixmap(str(img_path))
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return
        # Fallback text
        self.preview.setText(f"{p.name}\n(No preview available)")

    def resizeEvent(self, event):  # noqa: N802 - Qt signature
        # Keep image scaled to label
        super().resizeEvent(event)
        pix = self.preview.pixmap()
        if pix:
            self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _accept(self) -> None:
        if self.selected_name:
            self.accept()
