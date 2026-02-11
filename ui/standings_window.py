from __future__ import annotations

from collections import defaultdict
from datetime import datetime

try:
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit
    from PyQt6.QtCore import QTimer
except ImportError:  # pragma: no cover - fallback for stubbed tests
    class _QtDummy:
        def __init__(self, *_, **__):
            pass

        def __getattr__(self, _name):
            return self

        def setHtml(self, *_):
            pass

        def toHtml(self):
            return ""

    class QDialog(_QtDummy):
        pass

    class QVBoxLayout(_QtDummy):
        def addWidget(self, *_):
            pass

    class QTextEdit(_QtDummy):
        def __init__(self, *_, **__):
            super().__init__()
            self._html = ""

        def setHtml(self, html):
            self._html = html

        def setPlainText(self, text):
            self._html = text

        def setReadOnly(self, *_):
            pass

        def setMinimumHeight(self, *_):
            pass

        def toHtml(self):
            return self._html

    class QTimer:
        @staticmethod
        def singleShot(_msec, callback):
            if callback is not None:
                callback()

from utils.team_loader import load_teams
from utils.standings_utils import default_record
from utils.path_utils import get_data_dir
from utils.sim_date import get_current_sim_date
from services.standings_repository import load_standings
from services.unified_data_service import get_unified_data_service


class StandingsWindow(QDialog):
    """Dialog displaying league standings from league data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Standings")
        # Expand the dialog so the standings HTML can be viewed without scrolling
        self.setGeometry(100, 100, 1000, 800)

        layout = QVBoxLayout(self)

        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        # Ensure the text area grows with the dialog
        self.viewer.setMinimumHeight(760)

        layout.addWidget(self.viewer)

        self._service = get_unified_data_service()
        self._event_unsubscribes: list[callable] = []
        self._register_event_listeners()

        self._render_standings()

    def _register_event_listeners(self) -> None:
        """Subscribe to standings events to keep the view updated."""

        bus = self._service.events

        def _schedule_refresh(_payload=None) -> None:
            QTimer.singleShot(0, self._render_standings)

        for topic in ("standings.updated", "standings.invalidated"):
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, _schedule_refresh))
            except Exception:  # pragma: no cover - defensive
                pass

    def _render_standings(self) -> None:
        """Load league, division and team names into the text viewer."""

        if not hasattr(self, "viewer"):
            return

        base_dir = get_data_dir()
        league_name, umbrella_name = self._load_league_names(base_dir)

        teams = load_teams()
        divisions: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for team in teams:
            divisions[team.division].append((f"{team.city} {team.name}", team.abbreviation))

        standings = load_standings()

        # Build HTML using the same format as the sample standings page.
        sim_date = get_current_sim_date()
        if sim_date:
            try:
                date_obj = datetime.strptime(sim_date, "%Y-%m-%d")
                today = date_obj.strftime("%A, %B %d, %Y")
            except ValueError:
                today = sim_date
        else:
            today = datetime.now().strftime("%A, %B %d, %Y")
        parts = [
            "<html><head>",
            f"<title>{league_name} Standings</title>",
            "</head><body>",
            "<b><font size=\"+2\"><center>",
            f"{league_name} Standings",
            "</center></font>",
            "<font size=\"+1\"><center>",
            today,
            "</center></font></b>",
            "<hr><b><font size=\"+1\"><center>",
            league_name,
            "</center></font></b>",
        ]
        if umbrella_name and umbrella_name.lower() != league_name.lower():
            parts.extend([
                "<font size=\"+1\"><center>",
                umbrella_name,
                "</center></font>",
            ])
        parts.append("<pre>")

        def win_pct(record: dict[str, object]) -> float:
            wins = int(record.get("wins", 0))
            losses = int(record.get("losses", 0))
            games = wins + losses
            return wins / games if games else 0.0

        def fmt_pair(wins: int, losses: int) -> str:
            return f"{wins}-{losses}"

        def fmt_last10(entries: list[str]) -> str:
            wins = sum(1 for r in entries if r == "W")
            losses = sum(1 for r in entries if r == "L")
            return f"{wins}-{losses}"

        def fmt_streak(streak: dict[str, object]) -> str:
            result = streak.get("result")
            length = streak.get("length", 0)
            try:
                length = int(length)
            except (TypeError, ValueError):
                length = 0
            if result in {"W", "L"} and length > 0:
                return f"{result}{length}"
            return "--"

        row_fmt = (
            "{:<22}{:>2}  {:>2}  {:>5}  {:>4}  {:>5}  {:>6}  {:>5}  {:>4}  {:>6}  {:>6}  {:>7}  {:>7}  {:>8}  {:>8}"
        )

        for division in sorted(divisions):
            parts.append(
                f"<b>{row_fmt.format(division, 'W', 'L', 'Pct.', 'GB', '1-run', 'X-inn', 'L-10', 'Strk', 'Home', 'Road', 'v.RHP', 'v.LHP', 'in Div', 'nonDiv')}</b>"
            )

            def sort_key(team_info: tuple[str, str]) -> tuple[float, int]:
                record = standings.get(team_info[1], default_record())
                return (win_pct(record), int(record.get('wins', 0)))

            teams_sorted = sorted(divisions[division], key=sort_key, reverse=True)
            if teams_sorted:
                leader_record = standings.get(teams_sorted[0][1], default_record())
                leader_wins = int(leader_record.get('wins', 0))
                leader_losses = int(leader_record.get('losses', 0))
            else:
                leader_wins = leader_losses = 0

            for name, abbr in teams_sorted:
                record = standings.get(abbr, default_record())
                wins = int(record.get('wins', 0))
                losses = int(record.get('losses', 0))
                games = wins + losses
                pct = wins / games if games else 0.0
                gb_value = ((leader_wins - wins) + (losses - leader_losses)) / 2
                gb_str = '---' if not teams_sorted or abs(gb_value) < 1e-6 else f"{gb_value:.1f}".rstrip('0').rstrip('.')
                if gb_str == '':
                    gb_str = '0'
                one_run = fmt_pair(int(record.get('one_run_wins', 0)), int(record.get('one_run_losses', 0)))
                extra = fmt_pair(int(record.get('extra_innings_wins', 0)), int(record.get('extra_innings_losses', 0)))
                last10 = fmt_last10(list(record.get('last10', [])))
                streak = fmt_streak(record.get('streak', {}))
                home_rec = fmt_pair(int(record.get('home_wins', 0)), int(record.get('home_losses', 0)))
                road_rec = fmt_pair(int(record.get('road_wins', 0)), int(record.get('road_losses', 0)))
                vs_rhp = fmt_pair(int(record.get('vs_rhp_wins', 0)), int(record.get('vs_rhp_losses', 0)))
                vs_lhp = fmt_pair(int(record.get('vs_lhp_wins', 0)), int(record.get('vs_lhp_losses', 0)))
                div_rec = fmt_pair(int(record.get('division_wins', 0)), int(record.get('division_losses', 0)))
                non_div = fmt_pair(int(record.get('non_division_wins', 0)), int(record.get('non_division_losses', 0)))
                parts.append(
                    row_fmt.format(
                        name,
                        wins,
                        losses,
                        f"{pct:.3f}",
                        gb_str,
                        one_run,
                        extra,
                        last10,
                        streak,
                        home_rec,
                        road_rec,
                        vs_rhp,
                        vs_lhp,
                        div_rec,
                        non_div,
                    )
                )
            parts.append("")

        parts.extend(["</pre></body></html>"])
        self.viewer.setHtml("\n".join(parts))

    def closeEvent(self, event):  # pragma: no cover - GUI wiring
        for unsubscribe in getattr(self, "_event_unsubscribes", []):
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes = []
        super().closeEvent(event)

    @staticmethod
    def _load_league_names(base_dir) -> tuple[str, str]:
        league_name = "League"
        league_alias = "USABL"
        league_path = base_dir / "league.txt"
        lines: list[str] = []
        try:
            with league_path.open(encoding="utf-8") as fh:
                lines = [line.strip() for line in fh if line.strip()]
        except OSError:
            lines = []
        if lines:
            league_name = lines[0] or league_name
            if len(lines) > 1 and lines[1]:
                league_alias = lines[1]

        alias_path = base_dir / "league_alias.txt"
        if alias_path.exists():
            try:
                with alias_path.open(encoding="utf-8") as fh:
                    alias_line = fh.readline().strip()
                    if alias_line:
                        league_alias = alias_line
            except OSError:
                pass

        return league_name, league_alias
