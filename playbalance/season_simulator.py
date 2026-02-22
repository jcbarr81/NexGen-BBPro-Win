from __future__ import annotations

from typing import Callable, Dict, Iterable, List
import inspect
import random

from playbalance.game_runner import simulate_game_scores
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.path_utils import get_data_dir
from types import SimpleNamespace
from utils.exceptions import DraftRosterError
from utils.stats_persistence import load_stats as _load_season_stats

_BASIC_TEAM_KEYS = {"g", "w", "l", "r", "ra"}


def _coerce_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _persist_daily_totals(teams_accum: dict[str, dict[str, float]]) -> None:
    """Persist fallback team totals without overriding detailed season stats."""

    if not teams_accum:
        return
    try:
        existing = _load_season_stats()
    except Exception:
        existing = {"players": {}, "teams": {}}
    existing_teams: dict[str, dict[str, object]] = existing.get("teams", {}) or {}

    teams_to_save: list[SimpleNamespace] = []
    players_to_save: list[SimpleNamespace] = []

    for team_id, stats in teams_accum.items():
        current = existing_teams.get(team_id) or {}
        # Skip when detailed stats from the full simulator already exist.
        if any(key not in _BASIC_TEAM_KEYS for key in current.keys()):
            continue

        merged = {
            key: _coerce_int(current.get(key)) + _coerce_int(stats.get(key))
            for key in _BASIC_TEAM_KEYS
        }
        teams_to_save.append(SimpleNamespace(team_id=team_id, season_stats=merged))

        player_id = f"{team_id}_sim_player"
        players_to_save.append(
            SimpleNamespace(
                player_id=player_id,
                team_id=team_id,
                season_stats={
                    "g": merged["g"],
                    "r": merged["r"],
                    "ra": merged["ra"],
                },
            )
        )

    if teams_to_save:
        from playbalance.simulation import save_stats as _save_stats

        _save_stats(players_to_save, teams_to_save)


class SeasonSimulator:
    """Simulate a season schedule with an All-Star break."""

    def __init__(
        self,
        schedule: Iterable[Dict[str, str]],
        simulate_game: Callable[[str, str], None] | None = None,
        on_all_star_break: Callable[[], None] | None = None,
        after_game: Callable[[Dict[str, str]], None] | None = None,
        *,
        draft_date: str | None = None,
        on_draft_day: Callable[[str], None] | None = None,
    ) -> None:
        self.schedule = list(schedule)
        self.dates: List[str] = sorted({g["date"] for g in self.schedule})
        self._index = 0
        self.simulate_game = simulate_game or self._default_simulate_game
        self.on_all_star_break = on_all_star_break
        self._all_star_played = False
        self.after_game = after_game
        self._tracker = PitcherRecoveryTracker.instance()
        # Amateur draft hook
        self.draft_date: str | None = str(draft_date) if draft_date else None
        self._draft_triggered: bool = False
        self.on_draft_day = on_draft_day

        # Ensure Draft Day exists in the date sequence even if no games are scheduled
        # that day (e.g., an off day). This guarantees the simulator pauses to run the
        # draft rather than skipping past it when advancing to the next scheduled date.
        if self.draft_date and self.draft_date not in self.dates:
            self.dates.append(self.draft_date)
            self.dates.sort()

        # Compute midpoint after potential draft insertion
        self._mid = len(self.dates) // 2

        self._seed_positional = False
        self._seed_keyword = False
        self._seed_required = False
        self._date_param_name: str | None = None
        self._has_var_kwargs = False
        self._analyse_sim_signature()

    # ------------------------------------------------------------------
    def _analyse_sim_signature(self) -> None:
        sig = inspect.signature(self.simulate_game)
        params = sig.parameters
        self._has_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        seed_param = params.get("seed")
        if seed_param is not None:
            if seed_param.kind == inspect.Parameter.POSITIONAL_ONLY:
                self._seed_positional = True
            else:
                self._seed_keyword = True
            self._seed_required = seed_param.default is inspect._empty
        elif self._has_var_kwargs:
            self._seed_keyword = True

        if "game_date" in params:
            self._date_param_name = "game_date"
        elif "date" in params:
            self._date_param_name = "date"
        elif self._has_var_kwargs:
            self._date_param_name = "game_date"

    # ------------------------------------------------------------------
    def remaining_days(self) -> int:
        """Return the number of days left until the All-Star break."""

        return max(self._mid - self._index, 0)

    def remaining_schedule_days(self) -> int:
        """Return the number of scheduled days left in the regular season."""

        return max(len(self.dates) - self._index, 0)

    def _call_simulate_game(self, home: str, away: str, seed: int, date_str: str) -> object:
        args: List[object] = [home, away]
        kwargs: Dict[str, object] = {}
        if self._seed_positional:
            args.append(seed)
        elif self._seed_keyword:
            kwargs["seed"] = seed
        elif seed is not None:
            random.seed(seed)
        if self._date_param_name and date_str:
            kwargs[self._date_param_name] = date_str
        return self.simulate_game(*args, **kwargs)

    def simulate_next_day(self) -> None:
        """Simulate games for the next scheduled day."""

        if self._index == self._mid and not self._all_star_played:
            if self.on_all_star_break is not None:
                self.on_all_star_break()
            self._all_star_played = True

        if self._index >= len(self.dates):
            return
        current_date = self.dates[self._index]
        # Draft Day pause (before any games on that date)
        if (
            self.draft_date
            and not self._draft_triggered
            and str(current_date) == str(self.draft_date)
        ):
            if self.on_draft_day is not None:
                try:
                    self.on_draft_day(current_date)
                except DraftRosterError:
                    raise
                except Exception:
                    self._draft_triggered = True
                    raise
                else:
                    self._draft_triggered = True
            else:
                self._draft_triggered = True
        games = [g for g in self.schedule if g["date"] == current_date]
        if not games:
            self._index += 1
            return

        self._tracker.start_day(current_date)
        seeds = [random.randrange(1 << 30) for _ in games]

        def _apply_result_to_game(game: Dict[str, str], result) -> None:
            if not isinstance(result, tuple):
                return
            if len(result) >= 2:
                game["result"] = f"{result[0]}-{result[1]}"
            meta_index = 2
            if len(result) > 2:
                third = result[2]
                if isinstance(third, str):
                    game["boxscore_html"] = third
                else:
                    game["extra"] = third
                meta_index = 3
            if len(result) > meta_index:
                game["extra"] = result[meta_index]

        default_game = self._default_simulate_game
        use_default_save = self.simulate_game is default_game
        game_meta: list[tuple[str, str, dict[str, object]]] = []

        for game, seed in zip(games, seeds):
            result = self._call_simulate_game(game["home"], game["away"], seed, current_date)
            _apply_result_to_game(game, result)
            if self.after_game is not None:
                try:
                    self.after_game(game)
                except Exception:  # pragma: no cover - persistence is best effort
                    pass
            if use_default_save:
                meta = {}
                if len(result) >= 4 and isinstance(result[3], dict):
                    meta = result[3]
                game_meta.append((game["home"], game["away"], meta))

        if use_default_save:
            try:
                teams_accum: dict[str, dict[str, float]] = {}

                for home_id, away_id, details in game_meta:
                    result = details.get("score_line") or details.get("result") or None
                    home_runs = away_runs = None
                    if isinstance(result, dict):
                        home_runs = result.get("home")
                        away_runs = result.get("away")
                    elif isinstance(result, str) and "-" in result:
                        parts = result.split("-")
                        if len(parts) == 2:
                            try:
                                home_runs = int(parts[0])
                                away_runs = int(parts[1])
                            except ValueError:
                                home_runs = away_runs = None

                    if home_runs is None or away_runs is None:
                        score_str = next((g.get("result") for g in games if g["home"] == home_id and g["away"] == away_id), None)
                        if score_str and "-" in score_str:
                            try:
                                home_runs, away_runs = map(int, score_str.split("-"))
                            except ValueError:
                                home_runs = away_runs = 0
                        else:
                            home_runs = away_runs = 0

                    teams_accum.setdefault(home_id, {"g": 0, "r": 0, "ra": 0, "w": 0, "l": 0})
                    teams_accum.setdefault(away_id, {"g": 0, "r": 0, "ra": 0, "w": 0, "l": 0})

                    home_entry = teams_accum[home_id]
                    away_entry = teams_accum[away_id]

                    home_entry["g"] += 1
                    home_entry["r"] += home_runs
                    home_entry["ra"] += away_runs
                    home_entry["w"] += int(home_runs > away_runs)
                    home_entry["l"] += int(home_runs < away_runs)

                    away_entry["g"] += 1
                    away_entry["r"] += away_runs
                    away_entry["ra"] += home_runs
                    away_entry["w"] += int(away_runs > home_runs)
                    away_entry["l"] += int(away_runs < home_runs)

                _persist_daily_totals(teams_accum)
            except Exception:
                pass
        self._index += 1

    # ------------------------------------------------------------------
    @staticmethod
    def _default_simulate_game(
        home_id: str,
        away_id: str,
        seed: int | None = None,
        game_date: str | None = None,
    ) -> tuple[int, int, str, dict[str, object]]:
        """Run a full play-balance simulation and return score, HTML and metadata."""

        data_dir = get_data_dir()
        return simulate_game_scores(
            home_id,
            away_id,
            seed=seed,
            players_file=str(data_dir / "players.csv"),
            roster_dir=str(data_dir / "rosters"),
            lineup_dir=str(data_dir / "lineups"),
            game_date=game_date,
        )


__all__ = ["SeasonSimulator"]
from utils.team_loader import load_teams as _load_teams_cached
from utils.player_loader import load_players_from_csv as _load_players_cached
