from __future__ import annotations

"""Free Agency Hub (read-only + simulated AI bids).

Lists unsigned players and lets the user simulate an AI bidding outcome
without committing roster changes. This provides planning insight without
affecting league data. Persistence can be added later.
"""

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QAbstractItemView,
    )
    from PyQt6.QtCore import Qt
except Exception:  # pragma: no cover - headless stubs for tests
    class _Signal:
        def __init__(self): self._slot=None
        def connect(self, s): self._slot=s
        def emit(self, *a, **k):
            if self._slot: self._slot(*a, **k)
    class QDialog:  # type: ignore
        def __init__(self, *a, **k): pass
        def show(self): pass
    class QLabel:
        def __init__(self, text="", *a, **k): self._t=text
        def setText(self, t): self._t=t
    class QPushButton:
        def __init__(self, *a, **k): self.clicked=_Signal()
    class QTableWidget:
        def __init__(self, *a, **k): pass
        def setHorizontalHeaderLabels(self, *a, **k): pass
        def setRowCount(self, *a, **k): pass
        def setItem(self, *a, **k): pass
        def setEditTriggers(self, *a, **k): pass
        def setSelectionBehavior(self, *a, **k): pass
        def setSelectionMode(self, *a, **k): pass
        def currentRow(self): return -1
        def item(self, *a, **k): return None
    class QTableWidgetItem:
        def __init__(self, text=""): self._t=str(text)
        def text(self): return self._t
    class QVBoxLayout:
        def __init__(self, *a, **k): pass
        def addWidget(self, *a, **k): pass
        def addLayout(self, *a, **k): pass
        def setContentsMargins(self, *a, **k): pass
        def setSpacing(self, *a, **k): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QAbstractItemView:
        class EditTrigger: NoEditTriggers=0
        class SelectionBehavior: SelectRows=0
        class SelectionMode: SingleSelection=0
    class Qt:
        class AlignmentFlag: AlignLeft = 0; AlignHCenter = 0

from typing import Dict, List
import random

from services.free_agency import list_unsigned_players
from utils.team_loader import load_teams
from services.contract_negotiator import evaluate_free_agent_bids
from utils.news_logger import log_news_event
from utils.rating_display import rating_display_text


class FreeAgencyWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Free Agency Hub")
            self.resize(900, 600)
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("Unsigned Players")
        header.addWidget(self.title)
        header.addStretch()
        self.sim_bids_btn = QPushButton("Simulate AI Bids")
        self.sim_bids_btn.clicked.connect(self._simulate_bids)
        header.addWidget(self.sim_bids_btn)
        root.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Player", "Pos", "Age", "Hands", "Rating", "Expected $ (sim)"])
        try:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except Exception:
            pass
        root.addWidget(self.table)

        self.status = QLabel("Ready")
        root.addWidget(self.status)

        self._players: List[object] = []
        self._load_players()

    # ------------------------------------------------------------------
    def _load_players(self) -> None:
        try:
            teams = load_teams()
        except Exception:
            teams = []
        players = list_unsigned_players({}, teams)  # manager supplies maps, function tolerates {}
        self._players = list(players)
        self.table.setRowCount(len(self._players))
        for r, p in enumerate(self._players):
            name = f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
            pos = getattr(p, 'primary_position', '')
            age = getattr(p, 'birthdate', '')
            hands = getattr(p, 'bats', 'R')
            # rough overall score proxy
            rating = int(getattr(p, 'ch', 50))
            is_pitcher = bool(getattr(p, "is_pitcher", False)) or str(pos).upper() == "P"
            rating_display = rating_display_text(
                rating,
                key="CH",
                position=pos,
                is_pitcher=is_pitcher,
            )
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(str(pos)))
            self.table.setItem(r, 2, QTableWidgetItem(str(age)))
            self.table.setItem(r, 3, QTableWidgetItem(str(hands)))
            self.table.setItem(r, 4, QTableWidgetItem(str(rating_display)))
            self.table.setItem(r, 5, QTableWidgetItem(""))
        self.status.setText(f"Loaded {len(self._players)} unsigned players")

    def _simulate_bids(self) -> None:
        # Pick current row
        row = getattr(self.table, 'currentRow', lambda: -1)()
        if row is None or row < 0 or row >= len(self._players):
            self.status.setText("Select a player to simulate bids.")
            return
        player = self._players[row]
        # Build simple bids from all teams in league using random budgets
        try:
            teams = load_teams()
        except Exception:
            teams = []
        # Salary offers: base on rating ± random
        rating = max(1, int(getattr(player, 'ch', 50)))
        base_offer = 1000000 + rating * 25000
        bids = {t: base_offer + random.randint(0, 250000) for t in teams}
        try:
            winner = evaluate_free_agent_bids(player, bids)
            self.table.setItem(row, 5, QTableWidgetItem(f"${bids[winner]:,}"))
            msg = f"Simulated bids for {getattr(player,'first_name','')} {getattr(player,'last_name','')}: winner {winner.team_id} at ${bids[winner]:,}."
            self.status.setText(msg)
            log_news_event(msg)
        except Exception:
            self.status.setText("Failed to simulate bids.")


__all__ = ["FreeAgencyWindow"]
