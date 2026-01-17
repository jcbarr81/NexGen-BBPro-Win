from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .components import Card, section_title
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams


class DraftResultsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Draft Results")
        self.setMinimumSize(900, 600)

        self._base_dir = get_base_dir()
        self._results_paths = self._discover_results()
        self._team_map = self._load_team_map()
        self._player_lookup_cache: Dict[str, object] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        card = Card()
        header_row = QHBoxLayout()
        header_row.addWidget(section_title("Draft Results"))
        header_row.addStretch()
        header_row.addWidget(QLabel("Year:"))
        self.year_selector = QComboBox()
        self.year_selector.currentIndexChanged.connect(self._on_year_changed)
        header_row.addWidget(self.year_selector)
        card.layout().addLayout(header_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Pick", "Round", "Team", "Player", "Pos"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.itemDoubleClicked.connect(self._open_profile_from_item)
        card.layout().addWidget(self.table)

        layout.addWidget(card)

        self._populate_years()

    def _discover_results(self) -> dict[int, Path]:
        results: dict[int, Path] = {}
        data_dir = self._base_dir / "data"
        for path in data_dir.glob("draft_results_*.csv"):
            year = self._parse_year(path)
            if year is not None:
                results[year] = path

        careers_dir = data_dir / "careers"
        if careers_dir.exists():
            for path in careers_dir.glob("*/draft/draft_results_*.csv"):
                year = self._parse_year(path)
                if year is None or year in results:
                    continue
                results[year] = path
        return results

    @staticmethod
    def _parse_year(path: Path) -> int | None:
        stem = path.stem
        parts = stem.split("_")
        if not parts:
            return None
        try:
            return int(parts[-1])
        except ValueError:
            return None

    @staticmethod
    def _load_team_map() -> dict[str, object]:
        try:
            teams = load_teams()
        except Exception:
            return {}
        return {t.team_id: t for t in teams}

    def _player_lookup(self) -> dict[str, object]:
        if self._player_lookup_cache is None:
            try:
                self._player_lookup_cache = {
                    p.player_id: p for p in load_players_from_csv("data/players.csv")
                }
            except Exception:
                self._player_lookup_cache = {}
        return self._player_lookup_cache

    def _populate_years(self) -> None:
        self.year_selector.clear()
        years = sorted(self._results_paths.keys(), reverse=True)
        if not years:
            self.year_selector.setEnabled(False)
            self._set_empty_message("No draft results found.")
            return
        for year in years:
            self.year_selector.addItem(str(year), year)
        self.year_selector.setCurrentIndex(0)
        self._load_year(years[0])

    def _on_year_changed(self) -> None:
        year = self.year_selector.currentData()
        if year is None:
            return
        try:
            year_val = int(year)
        except (TypeError, ValueError):
            return
        self._load_year(year_val)

    def _pool_map_for_year(self, year: int, results_path: Path) -> dict[str, dict[str, Any]]:
        candidates = [
            results_path.parent / f"draft_pool_{year}.csv",
            results_path.parent / f"draft_pool_{year}.json",
        ]
        data_dir = self._base_dir / "data"
        candidates.extend(
            [
                data_dir / f"draft_pool_{year}.csv",
                data_dir / f"draft_pool_{year}.json",
            ]
        )
        pool_map: dict[str, dict[str, Any]] = {}
        for path in candidates:
            if not path.exists():
                continue
            try:
                if path.suffix == ".csv":
                    with path.open("r", encoding="utf-8", newline="") as fh:
                        for row in csv.DictReader(fh):
                            pid = str(row.get("player_id", "")).strip()
                            if pid:
                                pool_map[pid] = row
                    return pool_map
                if path.suffix == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(payload, list):
                        for row in payload:
                            if not isinstance(row, dict):
                                continue
                            pid = str(row.get("player_id", "")).strip()
                            if pid:
                                pool_map[pid] = row
                        return pool_map
            except Exception:
                continue
        return pool_map

    def _team_display(self, team_id: str) -> tuple[str, str | None]:
        team = self._team_map.get(team_id)
        if team is None:
            return team_id, None
        label = getattr(team, "abbreviation", None) or team.team_id
        name = f"{team.city} {team.name}".strip()
        return label, name if name else None

    def _load_year(self, year: int) -> None:
        results_path = self._results_paths.get(year)
        if results_path is None or not results_path.exists():
            self._set_empty_message(f"No draft results found for {year}.")
            return

        self._ensure_table_columns()
        pool_map = self._pool_map_for_year(year, results_path)
        players_map = self._player_lookup()
        rows: list[dict[str, Any]] = []

        try:
            with results_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    pid = str(row.get("player_id", "")).strip()
                    team_id = str(row.get("team_id", "")).strip()
                    pool_row = pool_map.get(pid, {})
                    player_obj = players_map.get(pid)

                    first = str(pool_row.get("first_name", "")).strip()
                    last = str(pool_row.get("last_name", "")).strip()
                    name = f"{first} {last}".strip()
                    if not name and player_obj is not None:
                        first = str(getattr(player_obj, "first_name", "")).strip()
                        last = str(getattr(player_obj, "last_name", "")).strip()
                        name = f"{first} {last}".strip()
                    if not name:
                        name = pid or "--"

                    pos = str(pool_row.get("primary_position", "")).strip()
                    if not pos and player_obj is not None:
                        pos = str(getattr(player_obj, "primary_position", "")).strip()

                    rows.append(
                        {
                            "overall": row.get("overall_pick", ""),
                            "round": row.get("round", ""),
                            "team_id": team_id,
                            "player": name,
                            "pos": pos or "--",
                            "player_id": pid,
                        }
                    )
        except Exception:
            self._set_empty_message(f"Unable to read draft results for {year}.")
            return

        if not rows:
            self._set_empty_message(f"No draft results found for {year}.")
            return

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_idx, entry in enumerate(rows):
            pick_item = QTableWidgetItem(str(entry["overall"]))
            round_item = QTableWidgetItem(str(entry["round"]))
            team_label, team_tip = self._team_display(entry["team_id"])
            team_item = QTableWidgetItem(team_label)
            if team_tip:
                team_item.setToolTip(team_tip)
            player_item = QTableWidgetItem(entry["player"])
            if entry.get("player_id"):
                player_item.setData(
                    Qt.ItemDataRole.UserRole, entry.get("player_id")
                )
            pos_item = QTableWidgetItem(entry["pos"])

            self.table.setItem(row_idx, 0, pick_item)
            self.table.setItem(row_idx, 1, round_item)
            self.table.setItem(row_idx, 2, team_item)
            self.table.setItem(row_idx, 3, player_item)
            self.table.setItem(row_idx, 4, pos_item)

        try:
            self.table.resizeColumnsToContents()
        except Exception:
            pass

    def _set_empty_message(self, message: str) -> None:
        self.table.setRowCount(1)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["Draft Results"])
        item = QTableWidgetItem(message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(0, 0, item)
        try:
            self.table.setSpan(0, 0, 1, 1)
        except Exception:
            pass

    def _ensure_table_columns(self) -> None:
        if self.table.columnCount() == 5:
            return
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Pick", "Round", "Team", "Player", "Pos"]
        )

    def _open_profile_from_item(self, item) -> None:
        row = item.row()
        player_item = self.table.item(row, 3)
        if player_item is None:
            return
        player_id = player_item.data(Qt.ItemDataRole.UserRole)
        if not player_id:
            return
        player = self._player_lookup().get(player_id)
        if player is None:
            return
        try:
            from ui.player_profile_dialog import PlayerProfileDialog

            PlayerProfileDialog(player, self).exec()
        except Exception:
            pass


__all__ = ["DraftResultsDialog"]
