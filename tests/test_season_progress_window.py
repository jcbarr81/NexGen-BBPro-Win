import sys, types
from concurrent.futures import Future

# ---- Stub PyQt6 modules ----
class DummySignal:
    def __init__(self, parent=None):
        self._slot = None
        self._parent = parent

    def connect(self, slot):
        self._slot = slot

    def emit(self):
        if self._slot and (
            self._parent is None or self._parent.isEnabled()
        ):
            self._slot()


class Dummy:
    def __init__(self, *args, **kwargs):
        self.clicked = DummySignal(self)
        self._enabled = True

    def __getattr__(self, name):
        return Dummy()

    def setVisible(self, *a, **k):
        pass

    def setWordWrap(self, *a, **k):
        pass

    def setText(self, *a, **k):
        pass

    def setValue(self, *a, **k):
        pass

    def text(self):
        return ""

    def addWidget(self, *a, **k):
        pass

    def connect(self, *a, **k):
        pass

    def setEnabled(self, value):
        self._enabled = value

    def isEnabled(self):
        return self._enabled

    def setWindowTitle(self, *a, **k):
        pass

    def show(self, *a, **k):
        pass

    def close(self, *a, **k):
        pass

    def wasCanceled(self):
        return False


class QLabel(Dummy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._text = ""
        self._style = ""

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text

    def setStyleSheet(self, style):
        self._style = style

    def clear(self):
        self._text = ""


class QPushButton(Dummy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._text = args[0] if args else ""

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class QListWidget(Dummy):
    class SelectionMode:
        NoSelection = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mouse_tracking = False
        self._selection_mode = self.SelectionMode.NoSelection

    def setMouseTracking(self, enabled):
        self._mouse_tracking = bool(enabled)

    def setSelectionMode(self, mode):
        self._selection_mode = mode


class QListWidgetItem(Dummy):
    pass


class QDialog(Dummy):
    pass


class QVBoxLayout(Dummy):
    pass


class QMessageBox:
    last = None

    @staticmethod
    def warning(parent, title, message):
        QMessageBox.last = (title, message)

    class StandardButton:
        Yes = 1
        No = 2

    @staticmethod
    def question(parent, title, message, buttons=None, default=None):
        # Default to "Yes" in headless tests
        return QMessageBox.StandardButton.Yes

    @staticmethod
    def information(parent, title, message):
        # Record the last info message in the same way as warning if needed
        QMessageBox.last = (title, message)


qtwidgets = types.ModuleType("PyQt6.QtWidgets")
qtwidgets.QDialog = QDialog
qtwidgets.QLabel = QLabel
qtwidgets.QPushButton = QPushButton
qtwidgets.QListWidget = QListWidget
qtwidgets.QListWidgetItem = QListWidgetItem
qtwidgets.QVBoxLayout = QVBoxLayout
qtwidgets.QMessageBox = QMessageBox
qtwidgets.QProgressBar = Dummy
qtwidgets.QProgressDialog = Dummy
sys.modules["PyQt6"] = types.ModuleType("PyQt6")
sys.modules["PyQt6.QtWidgets"] = qtwidgets
qtgui = types.ModuleType("PyQt6.QtGui")
qtgui.QColor = Dummy
sys.modules["PyQt6.QtGui"] = qtgui

# ---- Import window after stubs ----
from playbalance.season_manager import SeasonPhase
import services.season_progress_flags as spf
import ui.season_progress_window as spw


def _wait_for_future(win):
    fut = getattr(win, "_active_future", None)
    if isinstance(fut, Future):
        try:
            fut.result(timeout=1)
        except Exception:
            pass


class DummyManager:
    def __init__(self):
        self.phase = SeasonPhase.REGULAR_SEASON

    def handle_phase(self):
        return "Regular Season"

    def advance_phase(self):
        pass


spw.SeasonManager = DummyManager
spw.QMessageBox = QMessageBox
class DummyDraftConsole:
    def __init__(self, date_str, parent=None):
        self.assignment_summary = {"committed": True}

    def exec(self):
        pass

spw.DraftConsole = DummyDraftConsole

def _stub_load_teams(*args, **kwargs):
    teams = []
    ids = ["A", "B", "C", "D", "E", "F", "G", "H"]
    for idx, team_id in enumerate(ids):
        teams.append(
            types.SimpleNamespace(
                team_id=team_id,
                name=team_id,
                city=team_id,
                abbreviation=team_id,
                division=f"Div{idx % 2}",
                stadium="",
                primary_color="#000000",
                secondary_color="#FFFFFF",
                owner_id="",
                act_roster=[],
                aaa_roster=[],
                low_roster=[],
                season_stats={},
            )
        )
    return teams

spw.load_teams = _stub_load_teams
spw.SeasonProgressWindow._validate_all_team_lineups = lambda self: []


def test_simulate_day_until_midseason(tmp_path, monkeypatch):
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B"},
        {"date": "2024-04-02", "home": "A", "away": "B"},
        {"date": "2024-04-03", "home": "A", "away": "B"},
        {"date": "2024-04-04", "home": "A", "away": "B"},
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)
    assert win.remaining_label.text() == "Days until Midseason: 2"

    win.simulate_day_button.clicked.emit()
    _wait_for_future(win)
    assert games == [("A", "B")]
    assert win.remaining_label.text() == "Days until Midseason: 1"
    assert win.simulate_day_button.isEnabled()

    win.simulate_day_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 2
    assert win.remaining_label.text() == "Days until Draft: 2"
    assert win.simulate_day_button.isEnabled()

    win.simulate_day_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 3
    assert win.remaining_label.text() == "Days until Season End: 1"

    win.simulate_day_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 4
    assert win.remaining_label.text() == "Regular season complete."
    assert not win.simulate_day_button.isEnabled()
    assert win.next_button.isEnabled()

    # Further clicks should not simulate more games
    win.simulate_day_button.clicked.emit()
    assert len(games) == 4


def test_simulation_status_tracks_progress(tmp_path, monkeypatch):
    schedule = [
        {"date": f"2024-04-{day:02d}", "home": "A", "away": "B"}
        for day in range(1, 21)
    ]

    games: list[tuple[str, str]] = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)

    win.simulate_week_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 7
    status = win.simulation_status_label.text()
    assert "Simulation complete" in status
    assert "7/7 days" in status
    assert "100% complete" in status


def test_simulate_day_warns_when_missing_data(tmp_path, monkeypatch):
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B"},
        {"date": "2024-04-02", "home": "A", "away": "B"},
    ]

    def bad_sim(home, away):  # pragma: no cover - simple stub
        raise FileNotFoundError("Team A lineup missing")

    QMessageBox.last = None
    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=bad_sim)
    win.simulate_day_button.clicked.emit()
    _wait_for_future(win)
    assert QMessageBox.last == (
        "Missing Lineup or Pitching", "Team A lineup missing"
    )


def test_simulate_week_until_midseason(tmp_path, monkeypatch):
    schedule = [
        {"date": f"2024-04-{i:02d}", "home": "A", "away": "B"}
        for i in range(1, 11)
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)
    assert win.remaining_label.text() == "Days until Midseason: 5"

    win.simulate_week_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 7
    assert win.remaining_label.text() == "Days until Season End: 3"
    assert win.simulate_week_button.isEnabled()
    assert not win.next_button.isEnabled()

    win.simulate_week_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 10
    assert win.remaining_label.text() == "Regular season complete."
    assert not win.simulate_week_button.isEnabled()
    assert win.next_button.isEnabled()


def test_simulate_month_until_midseason(tmp_path, monkeypatch):
    schedule = [
        {"date": f"2024-04-{i:02d}", "home": "A", "away": "B"}
        for i in range(1, 41)
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)
    assert win.remaining_label.text() == "Days until Midseason: 20"

    win.simulate_month_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 30
    assert win.remaining_label.text() == "Days until Season End: 10"
    assert win.simulate_month_button.isEnabled()
    assert not win.next_button.isEnabled()
    assert win.done_button.isEnabled()

    win.simulate_month_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 40
    assert win.remaining_label.text() == "Regular season complete."
    assert not win.simulate_month_button.isEnabled()
    assert win.next_button.isEnabled()
    assert win.done_button.isEnabled()



def test_regular_season_simulation_controls(tmp_path, monkeypatch):
    spw.SeasonManager = DummyManager
    schedule = [
        {"date": f"2024-04-{i:02d}", "home": "A", "away": "B"}
        for i in range(1, 11)
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    monkeypatch.setattr(spf, "PROGRESS_PATH", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)
    assert "simulate_phase_button" not in win.__dict__
    assert win.remaining_label.text() == "Days until Midseason: 5"
    assert win.simulate_to_draft_button.text() == "Simulate to Draft Day"
    assert win.simulate_to_playoffs_button.text() == "Simulate to Playoffs"
    assert win.simulate_to_draft_button.isEnabled()
    assert not win.simulate_to_playoffs_button.isEnabled()
    assert not win.cancel_sim_button.isEnabled()

    win.simulate_to_draft_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 10
    assert win.remaining_label.text() in {
        "Regular season complete.",
        "Days until Season End: 0",
    }
    assert not win.simulate_to_draft_button.isEnabled()
    assert not win.simulate_to_playoffs_button.isEnabled()
    assert not win.simulate_day_button.isEnabled()
    assert win.next_button.isEnabled()


def test_season_progress_window_omits_timeline_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow()

    assert "timeline_label" in win.__dict__
    assert "timeline" in win.__dict__
    assert "feed_label" not in win.__dict__
    assert "feed_list" not in win.__dict__


def test_simulate_to_playoffs_requires_draft_completion(tmp_path, monkeypatch):
    spw.SeasonManager = DummyManager
    schedule = [
        {"date": f"2024-04-{i:02d}", "home": "A", "away": "B"}
        for i in range(1, 11)
    ] + [
        {"date": f"2024-08-{i:02d}", "home": "A", "away": "B"}
        for i in range(1, 4)
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)

    assert win.simulate_to_draft_button.isEnabled()
    assert not win.simulate_to_playoffs_button.isEnabled()

    win.simulate_to_draft_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == 10
    assert win.simulate_to_playoffs_button.isEnabled()

    win.simulate_to_playoffs_button.clicked.emit()
    _wait_for_future(win)
    assert len(games) == len(schedule)
    assert not win.simulate_to_playoffs_button.isEnabled()
    assert win.done_button.isEnabled()


def test_simulate_to_draft_stops_before_draft_day(tmp_path, monkeypatch):
    spw.SeasonManager = DummyManager
    schedule = [
        {"date": "2024-07-14", "home": "A", "away": "B"},
        {"date": "2024-07-15", "home": "A", "away": "B"},
        {"date": "2024-07-17", "home": "A", "away": "B"},
    ]

    games = []

    def fake_sim(home, away):
        games.append((home, away))

    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=schedule, simulate_game=fake_sim)
    draft_idx = win.simulator.dates.index(win.simulator.draft_date)

    win.simulate_to_draft_button.clicked.emit()
    _wait_for_future(win)

    assert win.simulator._index == draft_idx
    assert not getattr(win.simulator, "_draft_triggered", False)
    assert win.done_button.isEnabled()


def test_done_button_enabled_once_progress_complete(tmp_path, monkeypatch):
    spw.SeasonManager = DummyManager
    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow()
    win._active_future = object()
    win._allow_done_early = True
    win._update_ui()
    assert win.done_button.isEnabled()


def test_playoffs_require_simulation(tmp_path, monkeypatch):
    class PlayoffManager:
        def __init__(self):
            self.phase = SeasonPhase.PLAYOFFS

        def handle_phase(self):
            return "Playoffs"

        def advance_phase(self):
            self.phase = self.phase.next()

        def save(self):
            pass

    spw.SeasonManager = PlayoffManager
    monkeypatch.setattr(spw, "PROGRESS_FILE", tmp_path / "progress.json")
    win = spw.SeasonProgressWindow(schedule=[])
    assert win.remaining_label.text() == "Playoffs underway; simulate to continue."
    assert win.simulate_day_button.text() == "Simulate Game"
    assert win.simulate_round_button.text() == "Simulate Round"
    assert win.simulate_to_playoffs_button.text() == "Simulate Playoffs"
    assert win.simulate_day_button.isEnabled()
    assert win.simulate_round_button.isEnabled()
    assert win.simulate_to_playoffs_button.isEnabled()
    assert not win.next_button.isEnabled()

    win.simulate_to_playoffs_button.clicked.emit()
    _wait_for_future(win)
    assert not win.simulate_to_playoffs_button.isEnabled()
    assert win.next_button.isEnabled()
    assert win.remaining_label.text() == "Playoffs complete."
    note = win.notes_label.text()
    assert any(
        substring in note
        for substring in (
            "Simulated playoffs; championship decided.",
            "Playoffs already completed; champion:",
        )
    )
    spw.SeasonManager = DummyManager


def test_playoffs_flag_inferred_from_completed_bracket(tmp_path, monkeypatch):
    import json

    class PlayoffManager:
        def __init__(self):
            self.phase = SeasonPhase.PLAYOFFS

        def handle_phase(self):
            return "Playoffs"

        def advance_phase(self):
            self.phase = self.phase.next()

        def save(self):
            pass

    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps({"playoffs_done": False}))
    monkeypatch.setattr(spw, "PROGRESS_FILE", progress_path)

    bracket = types.SimpleNamespace(
        year=2025,
        champion="AAA",
        runner_up="BBB",
        rounds=[],
    )

    monkeypatch.setattr(spw, "SeasonManager", PlayoffManager)
    monkeypatch.setattr("playbalance.playoffs.load_bracket", lambda: bracket)
    monkeypatch.setattr("playbalance.playoffs.save_bracket", lambda br: None)

    schedule = [{"date": "2025-09-30", "home": "A", "away": "B"}]
    win = spw.SeasonProgressWindow(schedule=schedule)

    assert win._playoffs_done is True
    assert win.next_button.isEnabled()

    spw.SeasonManager = DummyManager


from datetime import date
from models.player import Player


def _player(age: int) -> Player:
    today = date.today()
    birthdate = date(today.year - age, today.month, today.day).isoformat()
    return Player(
        player_id=str(age),
        first_name="A",
        last_name="B",
        birthdate=birthdate,
        height=72,
        weight=180,
        bats="R",
        primary_position="1b",
        other_positions=[],
        gf=0,
        ch=50,
        ph=50,
        sp=50,
        fa=50,
        arm=50,
    )


def test_offseason_resets_to_preseason():
    class OffseasonManager:
        def __init__(self):
            self.phase = SeasonPhase.OFFSEASON
            self.players = {"old": _player(41), "young": _player(30)}

        def handle_phase(self):
            return "Offseason"

        def save(self):
            pass

        def advance_phase(self):
            self.phase = self.phase.next()

    spw.SeasonManager = OffseasonManager
    win = spw.SeasonProgressWindow()
    win._next_phase()
    assert win.manager.phase == SeasonPhase.PRESEASON
    assert "old" not in win.manager.players
    import playbalance.season_manager as sm
    assert sm.TRADE_DEADLINE.year == date.today().year + 1


def test_preseason_actions_require_sequence():
    class PreseasonManager:
        def __init__(self):
            self.phase = SeasonPhase.PRESEASON
            self.players = {}
            team_a = types.SimpleNamespace(
                abbreviation="A", act_roster=[], aaa_roster=[], low_roster=[]
            )
            team_b = types.SimpleNamespace(
                abbreviation="B", act_roster=[], aaa_roster=[], low_roster=[]
            )
            self.teams = [team_a, team_b]

        def handle_phase(self):
            return "Preseason"

        def save(self):
            pass

        def advance_phase(self):
            self.phase = self.phase.next()

    spw.SeasonManager = PreseasonManager
    win = spw.SeasonProgressWindow()

    assert not win.training_camp_button.isEnabled()
    assert not win.generate_schedule_button.isEnabled()
    assert not win.next_button.isEnabled()

    win.free_agency_button.clicked.emit()
    assert win.training_camp_button.isEnabled()
    assert "No unsigned players available" in win.notes_label.text()

    win.training_camp_button.clicked.emit()
    assert win.generate_schedule_button.isEnabled()
    assert "Training camp completed" in win.notes_label.text()

    win.generate_schedule_button.clicked.emit()
    assert len(win.simulator.schedule) == 162
    assert win.next_button.isEnabled()
    assert "Schedule generated with" in win.notes_label.text()


def test_generate_schedule_loads_teams_from_csv(monkeypatch, tmp_path):
    import csv

    class PreseasonManager:
        def __init__(self):
            self.phase = SeasonPhase.PRESEASON
            self.players = {}
            self.teams = []

        def handle_phase(self):
            return "Preseason"

        def save(self):
            pass

        def advance_phase(self):
            pass

    spw.SeasonManager = PreseasonManager
    teams_file = tmp_path / "teams.csv"
    with teams_file.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["abbreviation"])
        writer.writeheader()
        writer.writerow({"abbreviation": "A"})
        writer.writerow({"abbreviation": "B"})
    schedule_file = tmp_path / "schedule.csv"
    monkeypatch.setattr(spw, "TEAMS_FILE", teams_file)
    monkeypatch.setattr(spw, "SCHEDULE_FILE", schedule_file)

    win = spw.SeasonProgressWindow()
    win._generate_schedule()
    assert len(win.simulator.schedule) > 0
    assert schedule_file.exists()


def test_progress_persists_between_sessions(monkeypatch, tmp_path):
    class PreseasonManager:
        def __init__(self):
            self.phase = SeasonPhase.PRESEASON
            self.players = {}
            team_a = types.SimpleNamespace(
                abbreviation="A", act_roster=[], aaa_roster=[], low_roster=[]
            )
            team_b = types.SimpleNamespace(
                abbreviation="B", act_roster=[], aaa_roster=[], low_roster=[]
            )
            self.teams = [team_a, team_b]

        def handle_phase(self):
            return "Preseason"

        def save(self):
            pass

        def advance_phase(self):
            pass

    spw.SeasonManager = PreseasonManager
    progress_file = tmp_path / "progress.json"
    monkeypatch.setattr(spw, "PROGRESS_FILE", progress_file)

    win1 = spw.SeasonProgressWindow()
    assert win1.free_agency_button.isEnabled()
    win1.free_agency_button.clicked.emit()

    win2 = spw.SeasonProgressWindow()
    assert not win2.free_agency_button.isEnabled()
    assert win2.training_camp_button.isEnabled()
