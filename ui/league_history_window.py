from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from types import SimpleNamespace

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignLeft=None,
            AlignVCenter=None,
        ),
        ItemDataRole=SimpleNamespace(DisplayRole=None, EditRole=None, UserRole=None),
        ItemFlag=SimpleNamespace(ItemIsEditable=None),
        SortOrder=SimpleNamespace(AscendingOrder=None, DescendingOrder=None),
    )
try:
    from PyQt6.QtWidgets import (
        QDialog,
        QHeaderView,
        QLabel,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QTabWidget,
    )
except ImportError:  # pragma: no cover - test stubs
    class _QtDummy:
        EditTrigger = SimpleNamespace(NoEditTriggers=None)
        SelectionBehavior = SimpleNamespace(SelectRows=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _dummy(*_args, **_kwargs):
                return self

            return _dummy

    QDialog = QHeaderView = QLabel = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QTabWidget = _QtDummy

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None
            ResizeToContents = None

from playbalance.season_context import SeasonContext
from services.record_book import league_record_book
from services.special_events import load_special_events
from utils.path_utils import get_base_dir
from utils.team_loader import load_teams
from .components import Card, ensure_layout, section_title


@dataclass
class SeasonHistoryEntry:
    season_id: str
    league_year: str
    ended_on: str
    archived_on: str
    champion: str
    runner_up: str
    series_result: str
    mvp: str
    cy_young: str
    artifacts: Dict[str, str]


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _resolve_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = get_base_dir() / candidate
    return candidate


def _display(value: object, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _team_labels() -> Dict[str, str]:
    labels: Dict[str, str] = {}
    try:
        teams = load_teams()
    except Exception:
        return labels
    for team in teams:
        tid = str(getattr(team, "team_id", "") or "").strip()
        name = f"{getattr(team, 'city', '')} {getattr(team, 'name', '')}".strip()
        if tid:
            labels[tid] = name or tid
    return labels


def _holder_label(holder: Dict[str, Any]) -> str:
    name = str(holder.get("name") or holder.get("team_name") or holder.get("team_id") or holder.get("player_id") or "")
    season_label = str(holder.get("season_label") or "").strip()
    if season_label:
        return f"{name} ({season_label})"
    return name


def _record_book_text(book: Dict[str, List[Dict[str, Any]]]) -> str:
    sections = (
        ("Batting Records", book.get("batting", [])),
        ("Pitching Records", book.get("pitching", [])),
        ("Team Records", book.get("team", [])),
    )
    lines: List[str] = []
    for title, records in sections:
        lines.append(f"{title}:")
        if not records:
            lines.append("  (none)")
            lines.append("")
            continue
        for entry in records:
            holders = entry.get("holders", []) if isinstance(entry, dict) else []
            holder_text = ", ".join(
                [_holder_label(holder) for holder in holders if isinstance(holder, dict)]
            )
            if not holder_text:
                holder_text = "-"
            value_text = str(entry.get("value_text") or entry.get("value") or "-")
            lines.append(f"  {entry.get('label', '-')}: {holder_text} - {value_text}")
        lines.append("")
    return "\n".join(lines).strip()


def _load_awards(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = _read_json(path, {})
    awards = payload.get("awards", {})
    if isinstance(awards, dict):
        return awards
    return {}


def _award_name(awards: Dict[str, Any], key: str) -> str:
    entry = awards.get(key, {})
    if not isinstance(entry, dict):
        return "-"
    name = str(entry.get("player_name") or "").strip()
    if not name:
        name = str(entry.get("player_id") or "").strip()
    return name or "-"


def _load_champion(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year:
        return "", "", ""
    if path is None or not path.exists():
        return "", "", ""
    target = league_year.strip()
    selected = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                if target and str(row.get("year", "")).strip() != target:
                    continue
                selected = row
    except OSError:
        return "", "", ""
    if not selected:
        return "", "", ""
    return (
        str(selected.get("champion", "") or "").strip(),
        str(selected.get("runner_up", "") or "").strip(),
        str(selected.get("series_result", "") or "").strip(),
    )


def _season_artifacts(season: Dict[str, Any], season_id: str) -> Dict[str, str]:
    artifacts = season.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        return {
            str(key): str(value)
            for key, value in artifacts.items()
            if value
        }
    meta_path = get_base_dir() / "data" / "careers" / season_id / "metadata.json"
    payload = _read_json(meta_path, {})
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {
            str(key): str(value)
            for key, value in meta_artifacts.items()
            if value
        }
    return {}


def _load_history_entries() -> list[SeasonHistoryEntry]:
    context = SeasonContext.load()
    entries: list[SeasonHistoryEntry] = []
    seasons = list(context.seasons)
    for season in reversed(seasons):
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id", "") or "").strip()
        if not season_id:
            continue
        league_year = _display(season.get("league_year"), "")
        ended_on = _display(season.get("ended_on"), "")
        archived_on = _display(season.get("archived_on"), "")
        artifacts = _season_artifacts(season, season_id)
        awards = _load_awards(_resolve_path(artifacts.get("awards")))
        champions_path = _resolve_path(artifacts.get("champions"))
        champion, runner_up, series_result = _load_champion(champions_path, league_year)
        entries.append(
            SeasonHistoryEntry(
                season_id=season_id,
                league_year=league_year,
                ended_on=ended_on,
                archived_on=archived_on,
                champion=champion,
                runner_up=runner_up,
                series_result=series_result,
                mvp=_award_name(awards, "MVP"),
                cy_young=_award_name(awards, "CY_YOUNG"),
                artifacts=artifacts,
            )
        )
    return entries


class LeagueHistoryWindow(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        if callable(getattr(self, "setWindowTitle", None)):
            self.setWindowTitle("League History")
        if callable(getattr(self, "resize", None)):
            self.resize(980, 700)

        layout = QVBoxLayout(self)
        if callable(getattr(layout, "setContentsMargins", None)):
            layout.setContentsMargins(24, 24, 24, 24)
        if callable(getattr(layout, "setSpacing", None)):
            layout.setSpacing(18)

        self._entries = _load_history_entries()
        self._entry_map = {entry.season_id: entry for entry in self._entries}

        table_card = Card()
        table_layout = ensure_layout(table_card)
        table_layout.addWidget(section_title("Archived Seasons"))
        if not self._entries:
            message = QLabel(
                "No archived seasons yet. Finish a season to populate league history."
            )
            if callable(getattr(message, "setWordWrap", None)):
                message.setWordWrap(True)
            table_layout.addWidget(message)

        self.table = QTableWidget(len(self._entries), 6)
        self.table.setHorizontalHeaderLabels(
            ["Season", "Year", "Ended", "Champion", "MVP", "CY Young"]
        )
        try:
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            header = self.table.horizontalHeader()
            header.setStretchLastSection(True)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            self.table.verticalHeader().setVisible(False)
        except Exception:
            pass

        self._populate_table()
        try:
            self.table.setSortingEnabled(True)
            self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        except Exception:
            pass
        try:
            self.table.itemSelectionChanged.connect(self._refresh_details)
        except Exception:
            pass
        table_layout.addWidget(self.table)
        layout.addWidget(table_card)

        details_card = Card()
        details_layout = ensure_layout(details_card)
        details_layout.addWidget(section_title("Season Details"))
        self.details_tabs = QTabWidget()
        self.details_summary = QTextEdit()
        self.details_record_book = QTextEdit()
        try:
            self.details_summary.setReadOnly(True)
            self.details_record_book.setReadOnly(True)
        except Exception:
            pass
        self.details_events = QTableWidget(0, 4)
        self.details_events.setHorizontalHeaderLabels(
            ["Date", "Player", "Event", "Team"]
        )
        try:
            self.details_events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.details_events.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.details_events.verticalHeader().setVisible(False)
            header = self.details_events.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            pass
        self.details_tabs.addTab(self.details_summary, "Summary")
        self.details_tabs.addTab(self.details_record_book, "Record Book")
        self.details_tabs.addTab(self.details_events, "Special Events")
        details_layout.addWidget(self.details_tabs)
        layout.addWidget(details_card)
        layout.addStretch()

        if self._entries:
            try:
                self.table.selectRow(0)
            except Exception:
                pass
        self._record_book_cache: Dict[str, List[Dict[str, Any]]] | None = None
        self._team_labels = _team_labels()
        self._refresh_details()

    def _populate_table(self) -> None:
        for row, entry in enumerate(self._entries):
            season_item = QTableWidgetItem(entry.season_id)
            try:
                season_item.setData(Qt.ItemDataRole.UserRole, entry.season_id)
            except Exception:
                pass
            self.table.setItem(row, 0, season_item)
            self.table.setItem(row, 1, QTableWidgetItem(_display(entry.league_year)))
            self.table.setItem(row, 2, QTableWidgetItem(_display(entry.ended_on)))
            self.table.setItem(row, 3, QTableWidgetItem(_display(entry.champion)))
            self.table.setItem(row, 4, QTableWidgetItem(_display(entry.mvp)))
            self.table.setItem(row, 5, QTableWidgetItem(_display(entry.cy_young)))

    def _current_entry(self) -> SeasonHistoryEntry | None:
        try:
            row = self.table.currentRow()
        except Exception:
            row = -1
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        season_id = None
        try:
            season_id = item.data(Qt.ItemDataRole.UserRole)
        except Exception:
            season_id = None
        if season_id is None:
            try:
                season_id = item.text()
            except Exception:
                season_id = None
        if season_id is None:
            return None
        return self._entry_map.get(str(season_id))

    def _refresh_details(self) -> None:
        entry = self._current_entry()
        if self._record_book_cache is None:
            try:
                self._record_book_cache = league_record_book()
            except Exception:
                self._record_book_cache = {}
        record_text = _record_book_text(self._record_book_cache or {})
        try:
            self.details_record_book.setPlainText(
                record_text or "Record book unavailable."
            )
        except Exception:
            pass

        if entry is None:
            try:
                self.details_summary.setPlainText("Select a season to view details.")
            except Exception:
                pass
            self._populate_events([])
            return

        lines = [
            f"Season ID: {_display(entry.season_id)}",
            f"League Year: {_display(entry.league_year)}",
            f"Ended On: {_display(entry.ended_on)}",
            f"Archived On: {_display(entry.archived_on)}",
            f"Champion: {_display(entry.champion)}",
            f"Runner-up: {_display(entry.runner_up)}",
            f"Series Result: {_display(entry.series_result)}",
            "",
            "Awards:",
            f"  MVP: {_display(entry.mvp)}",
            f"  CY Young: {_display(entry.cy_young)}",
            "",
            "Artifacts:",
        ]
        if entry.artifacts:
            for key in sorted(entry.artifacts):
                lines.append(f"  {key}: {entry.artifacts[key]}")
        else:
            lines.append("  (none)")
        text = "\n".join(lines)
        try:
            self.details_summary.setPlainText(text)
        except Exception:
            pass
        self._populate_events(self._load_events_for_entry(entry))

    def _load_events_for_entry(self, entry: SeasonHistoryEntry) -> list[Dict[str, Any]]:
        path = _resolve_path(entry.artifacts.get("special_events"))
        if path is None:
            candidate = get_base_dir() / "data" / "careers" / entry.season_id / "special_events.json"
            if candidate.exists():
                path = candidate
        if path is None or not path.exists():
            return []
        try:
            return load_special_events(path=path, limit=200)
        except Exception:
            return []

    def _populate_events(self, events: list[Dict[str, Any]]) -> None:
        try:
            self.details_events.setRowCount(len(events))
        except Exception:
            return
        for row, event in enumerate(events):
            date_val = str(event.get("date") or "").strip() or "--"
            player = str(event.get("player_name") or event.get("player_id") or "--")
            label = str(event.get("label") or event.get("type") or "--")
            detail = str(event.get("detail") or "").strip()
            event_text = label if not detail else f"{label} - {detail}"
            team_id = str(event.get("team_id") or "").strip()
            opp_id = str(event.get("opponent_id") or "").strip()
            team_label = self._team_labels.get(team_id, team_id or "--")
            opp_label = self._team_labels.get(opp_id, opp_id)
            if opp_label:
                team_label = f"{team_label} vs {opp_label}"
            self.details_events.setItem(row, 0, QTableWidgetItem(date_val))
            self.details_events.setItem(row, 1, QTableWidgetItem(player))
            self.details_events.setItem(row, 2, QTableWidgetItem(event_text))
            self.details_events.setItem(row, 3, QTableWidgetItem(team_label))


__all__ = ["LeagueHistoryWindow"]
