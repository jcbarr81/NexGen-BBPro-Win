from __future__ import annotations

from typing import Callable, Dict, Iterable, List
import inspect
import random

from playbalance.game_runner import simulate_game_scores
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.path_utils import get_data_dir
from types import SimpleNamespace
from utils.exceptions import DraftRosterError
from utils.stats_persistence import (
    batched_stats_writes,
    load_stats as _load_season_stats,
)

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

        # Midpoint of the actual game schedule — the All-Star break anchor.
        # Compute it BEFORE inserting the draft date so a mid-July draft day
        # (an off-day with no games) can't nudge the break off the true
        # midseason point.
        self._mid = len(self.dates) // 2

        # Ensure Draft Day exists in the date sequence even if no games are scheduled
        # that day (e.g., an off day). This guarantees the simulator pauses to run the
        # draft rather than skipping past it when advancing to the next scheduled date.
        if self.draft_date and self.draft_date not in self.dates:
            self.dates.append(self.draft_date)
            self.dates.sort()

        # Per-day seed generator (S1-10 D6). Created lazily on the first
        # simulate_next_day() call so callers' random.seed(...) still seeds the
        # first draw, then decoupled from the global stream — the physics
        # engine reseeds global random per game (engine.py), which in serial
        # would feed the next day's seeds; a private generator makes serial and
        # parallel day-simulation produce byte-identical seeds by construction.
        self._seed_rng: random.Random | None = None

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
                    # Don't mark the draft "triggered" on an unexpected crash —
                    # doing so would skip the draft entirely on the retry,
                    # leaving the league with no picks. Re-raise so the failure
                    # surfaces and the next attempt re-runs the draft.
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
        # S1-10 D6: draw per-day seeds from a private generator decoupled from
        # the global random stream. The first-ever draw is seeded from the
        # global stream (honoring any caller random.seed(...)); thereafter the
        # engine's per-game global reseeding cannot perturb our seed sequence,
        # so serial and parallel day-simulation stay bit-identical.
        if self._seed_rng is None:
            self._seed_rng = random.Random(random.randrange(1 << 62))
        seeds = [self._seed_rng.randrange(1 << 30) for _ in games]

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

        # Batch the per-game season-stats writes into one flush per day
        # (S1-01): stats are cumulative-to-date, so the final file is
        # identical while the O(file-size) parse+rewrite happens once
        # instead of once per game. Same idea for the recovery tracker
        # (S1-02): its ~4 whole-file rewrites per game become one per day.
        # S1-10: opt-in parallel day simulation. Workers simulate games with all
        # persistence intercepted into journals; the parent replays them below in
        # serial game order, so the on-disk state is byte-identical to serial.
        # Default (PB_PARALLEL_GAMES unset) resolves to 0 workers -> serial path.
        from playbalance import parallel_day

        workers = parallel_day.resolve_worker_count(len(games))
        parallel = workers >= 2 and self._parallel_eligible()

        with batched_stats_writes(), self._tracker.deferred_saves():
            if parallel:
                self._simulate_day_parallel(
                    games,
                    seeds,
                    current_date,
                    workers,
                    use_default_save,
                    game_meta,
                    _apply_result_to_game,
                )
            else:
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
    def _parallel_eligible(self) -> bool:
        """D2 gate: parallel only for the two audited simulate callables +
        physics engine. Custom callables (tests/scripts) and the legacy engine
        have unaudited write paths and always run serial."""

        from playbalance.game_runner import _resolve_game_engine, simulate_game_scores

        if (
            self.simulate_game is not self._default_simulate_game
            and self.simulate_game is not simulate_game_scores
        ):
            return False
        try:
            return _resolve_game_engine(None) == "physics"
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _simulate_day_parallel(
        self,
        games: List[Dict[str, str]],
        seeds: List[int],
        current_date: str,
        workers: int,
        use_default_save: bool,
        game_meta: list,
        apply_result: Callable[[Dict[str, str], object], None],
    ) -> None:
        """Simulate one day's games in worker processes, then replay their
        side-effect journals in the parent in serial game order (S1-10).

        Runs inside the caller's ``batched_stats_writes()`` +
        ``deferred_saves()`` contexts so tracker/stats writes flush once per day
        exactly as serial does.
        """

        import logging
        from concurrent.futures.process import BrokenProcessPool

        from playbalance import game_runner, parallel_day
        from utils.path_utils import (
            get_active_league_id,
            get_data_dir,
            get_data_root,
        )
        from utils.player_loader import load_players_from_csv

        logger = logging.getLogger(__name__)
        data_dir = get_data_dir()
        players_file = str(data_dir / "players.csv")
        roster_dir = str(data_dir / "rosters")

        # 1. Pre-assign starters in games order (home then away), advancing each
        #    team's next_index exactly once, in the same per-team order as serial.
        assignments: list[tuple[str | None, str | None]] = []
        for game in games:
            home_starter = (
                self._tracker.assign_starter(game["home"], current_date, players_file, roster_dir)
                or None
            )
            away_starter = (
                self._tracker.assign_starter(game["away"], current_date, players_file, roster_dir)
                or None
            )
            assignments.append((home_starter, away_starter))

        # 2. Build payloads. One usage context for the day. Every game gets the
        #    FULL fatigue state (so no participant is ever seeded at zero); the
        #    worker returns only the players it changed, so the merge is exact.
        usage_state, game_day = game_runner._physics_usage_context(current_date)
        data_root = str(get_data_root())
        league_id = get_active_league_id()
        usage_in = parallel_day.usage_state_to_payload(usage_state, game_day)

        payloads = []
        for game, seed, (home_starter, away_starter) in zip(games, seeds, assignments):
            payloads.append(
                parallel_day.build_payload(
                    home=game["home"],
                    away=game["away"],
                    seed=seed,
                    date=current_date,
                    home_starter=home_starter,
                    away_starter=away_starter,
                    data_root=data_root,
                    league_id=league_id,
                    usage_in=usage_in,
                )
            )

        # 3. Dispatch.
        pool = parallel_day.get_pool(workers)
        futures = [pool.submit(parallel_day.simulate_game_job, payload) for payload in payloads]

        # 4. Replay in games order. day_lookup is rebuilt after any game that
        #    applied injuries (players.csv changed).
        day_lookup = {p.player_id: p for p in load_players_from_csv(players_file)}
        day_broken = False
        for idx, (game, seed, (home_starter, away_starter)) in enumerate(
            zip(games, seeds, assignments)
        ):
            journal = None
            if not day_broken:
                try:
                    journal = futures[idx].result()
                except Exception as exc:  # includes BrokenProcessPool + journal errors (D12)
                    logger.warning(
                        "parallel game %s@%s on %s failed (%s); falling back to serial",
                        game.get("away"),
                        game.get("home"),
                        current_date,
                        exc,
                    )
                    if isinstance(exc, BrokenProcessPool):
                        parallel_day.shutdown_pool()
                        day_broken = True  # remaining games this day run serial in-parent
                    journal = None

            if journal is None:
                # D12: serial fallback executed in-parent (side effects direct,
                # batch contexts active), with the pre-assigned starters.
                result = game_runner.simulate_game_scores(
                    game["home"],
                    game["away"],
                    seed=seed,
                    game_date=current_date,
                    home_starter=home_starter,
                    away_starter=away_starter,
                    players_file=players_file,
                    roster_dir=roster_dir,
                )
            else:
                result = game_runner.replay_game_journal(
                    journal,
                    tracker=self._tracker,
                    players_file=players_file,
                    roster_dir=roster_dir,
                    game_date=current_date,
                    day_lookup=day_lookup,
                )
                parallel_day.merge_usage_into_state(usage_state, journal.get("usage"))
                if journal.get("injury_events"):
                    day_lookup = {
                        p.player_id: p for p in load_players_from_csv(players_file)
                    }

            apply_result(game, result)
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

    # ------------------------------------------------------------------
    @staticmethod
    def _default_simulate_game(
        home_id: str,
        away_id: str,
        seed: int | None = None,
        game_date: str | None = None,
        *,
        home_starter: str | None = None,
        away_starter: str | None = None,
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
            home_starter=home_starter,
            away_starter=away_starter,
        )


__all__ = ["SeasonSimulator"]
from utils.team_loader import load_teams as _load_teams_cached
from utils.player_loader import load_players_from_csv as _load_players_cached
