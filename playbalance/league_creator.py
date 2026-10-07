import colorsys
import csv
import json
import os
import random
import shutil
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set, Tuple

from utils.path_utils import ensure_writable
from models.player import Player
from models.pitcher import Pitcher
from models.roster import Roster
from services.players_repository import save_players
from playbalance.player_generator import generate_player, reset_name_cache
from utils.user_manager import clear_users
import utils.lineup_loader as lineup_loader
from utils.lineup_loader import build_default_game_state
from utils import roster_loader
from utils.roster_rules import (
    AAA_CAP,
    ACT_HITTER_TARGET,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
)
from playbalance.season_context import SeasonContext, slugify_league_id
from services.standings_repository import save_standings

MAX_LEAGUE_TEAMS = 40

# Generated organisations (owner decision 8, utils.roster_rules): a full
# 26-man ACT of 13 pitchers and 13 hitters, then AAA and LOW at their caps --
# 51 players, the organisation limit.
ACT_PITCHERS = MAX_ACTIVE_PITCHERS
ACT_HITTERS = ACT_HITTER_TARGET
AAA_PITCHERS = 7
AAA_HITTERS = AAA_CAP - AAA_PITCHERS
LOW_PITCHERS = 5
LOW_HITTERS = LOW_CAP - LOW_PITCHERS


def _abbr(city: str, name: str, existing: set) -> str:
    """Generate a unique team abbreviation based solely on the city name.

    The abbreviation uses the first three letters of the *city* and appends
    a number if necessary to ensure uniqueness. The *name* parameter is
    ignored but kept for backward compatibility with callers.
    """
    base = "".join(city.split())[:3].upper() or city[:3].upper().strip()
    candidate = base
    i = 1
    while candidate in existing:
        candidate = f"{base}{i}"
        i += 1
    existing.add(candidate)
    return candidate


def _unique_color_pair(used: set) -> tuple[str, str]:
    """Generate a pair of contrasting hex colors not already in *used*.

    Colors are generated deterministically using evenly distributed hues. The
    secondary color is the complement of the primary. Both colors are added to
    *used* before returning.
    """
    idx = len(used) // 2
    while True:
        hue = (idx * 0.618033988749895) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.6, 0.95)
        primary = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"

        comp_hue = (hue + 0.5) % 1.0
        r2, g2, b2 = colorsys.hsv_to_rgb(comp_hue, 0.6, 0.95)
        secondary = f"#{int(r2 * 255):02X}{int(g2 * 255):02X}{int(b2 * 255):02X}"

        if primary not in used and secondary not in used:
            used.update({primary, secondary})
            return primary, secondary
        idx += 1


def _dict_to_model(data: dict):
    potentials = {k[4:]: v for k, v in data.items() if k.startswith("pot_")}
    other_pos = data.get("other_positions")
    common = dict(
        player_id=data.get("player_id"),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        birthdate=str(data.get("birthdate")),
        height=data.get("height", 0),
        weight=data.get("weight", 0),
        ethnicity=data.get("ethnicity", ""),
        skin_tone=data.get("skin_tone", ""),
        hair_color=data.get("hair_color", ""),
        facial_hair=data.get("facial_hair", ""),
        bats=data.get("bats", "R"),
        throws=str(
            data.get("throws") or data.get("bats") or "R"
        ),
        primary_position=data.get("primary_position", ""),
        other_positions=other_pos if isinstance(other_pos, list) else (other_pos.split("|") if other_pos else []),
        gf=data.get("gf", 0),
        injured=bool(data.get("injured", 0)),
        injury_description=data.get("injury_description"),
        return_date=data.get("return_date"),
    )
    if data.get("is_pitcher"):
        arm = data.get("arm") or data.get("fb", 0)
        potentials.setdefault("arm", arm)
        return Pitcher(
            **common,
            endurance=data.get("endurance", 0),
            control=data.get("control", 0),
            movement=data.get("movement", 0),
            hold_runner=data.get("hold_runner", 0),
            role=data.get("role", ""),
            preferred_pitching_role=data.get("preferred_pitching_role", ""),
            fb=data.get("fb", 0),
            cu=data.get("cu", 0),
            cb=data.get("cb", 0),
            sl=data.get("sl", 0),
            si=data.get("si", 0),
            scb=data.get("scb", 0),
            kn=data.get("kn", 0),
            arm=arm,
            fa=data.get("fa", 0),
            pitcher_archetype=data.get("pitcher_archetype", ""),
            potential=potentials,
        )
    else:
        return Player(
            **common,
            ch=data.get("ch", 0),
            ph=data.get("ph", 0),
            sp=data.get("sp", 0),
            eye=data.get("eye", data.get("ch", 0)),
            hitter_archetype=data.get("hitter_archetype", ""),
            pl=data.get("pl", 0),
            vl=data.get("vl", 0),
            sc=data.get("sc", 0),
            fa=data.get("fa", 0),
            arm=data.get("arm", 0),
            potential=potentials,
        )


def _purge_old_league(base_dir: Path) -> None:
    """Remove remnants of a previous league from ``base_dir``.

    Static resources required for league generation are preserved. Player
    avatars reside outside ``base_dir`` and are therefore untouched.
    """
    keep = {"names.csv", "ballparks.py", "MLB_avg"}

    def _on_rm_error(func, path, _exc_info):
        try:
            ensure_writable(path)
            func(path)
        except Exception:
            pass

    for item in base_dir.iterdir():
        if item.name in keep:
            continue
        if item.is_dir():
            shutil.rmtree(item, onerror=_on_rm_error)
        else:
            try:
                item.unlink()
            except OSError:
                try:
                    ensure_writable(item)
                    item.unlink()
                except OSError:
                    if item.exists():
                        raise
    # Remove lingering lock files that may live alongside stats.
    lock_file = base_dir / "season_stats.json.lock"
    if lock_file.exists():
        try:
            ensure_writable(lock_file)
            lock_file.unlink()
        except OSError:
            pass


def _ensure_act_positions(players: List[dict]) -> None:
    """Ensure the active roster has coverage for all positions.

    Parameters
    ----------
    players:
        List of player dictionaries representing the ACT roster.

    Raises
    ------
    ValueError
        If any required position is missing from the roster.
    """
    required = {"P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"}
    positions = {p.get("primary_position") for p in players}
    missing = required - positions
    if missing:
        raise ValueError(
            "ACT roster missing positions: " + ", ".join(sorted(missing))
        )


def _build_pitching_staff(players: List[dict]) -> List[tuple[str, str]]:
    """Return ordered (player_id, role) entries for a pitching staff.

    Uses the Pitching auto-fill (``utils.pitching_autofill``), the same rows
    the editor's Auto-Fill and ``/pitching/autofill`` write: SP1-5, LR, CL,
    SU, MR1-MR3, then the optional MR4/MR5 for the 12th and 13th active arms.
    A new league therefore starts with a staff the editor's own validation
    accepts and every active pitcher slotted. The creator used to write plain
    "MR" rows and two "SU" rows, which the editor rejects.
    """

    from utils.pitching_autofill import autofill_pitching_staff

    candidates = [
        (str(p["player_id"]), p) for p in players if counts_as_pitcher(p)
    ]
    if not candidates:
        return []
    assignments = autofill_pitching_staff(candidates)
    return [(pid, role) for role, pid in assignments.items() if pid]


def _write_default_lineups(base_dir: Path, team_ids: Iterable[str]) -> None:
    """Create simple left/right lineups for each team using roster data."""

    lineup_dir = base_dir / "lineups"
    if lineup_dir.exists():
        shutil.rmtree(lineup_dir, ignore_errors=True)
    lineup_dir.mkdir(parents=True, exist_ok=True)

    players_file = base_dir / "players.csv"
    roster_dir = base_dir / "rosters"

    def _write_lineup(path: Path, lineup: List[Player]) -> None:
        with path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["order", "player_id", "position"])
            for order, player in enumerate(lineup, start=1):
                position = getattr(player, "position", "") or getattr(player, "primary_position", "")
                writer.writerow([order, player.player_id, position])

    for team_id in team_ids:
        state = build_default_game_state(
            team_id,
            players_file=str(players_file),
            roster_dir=str(roster_dir),
        )
        _write_lineup(lineup_dir / f"{team_id}_vs_rhp.csv", list(state.lineup))
        _write_lineup(lineup_dir / f"{team_id}_vs_lhp.csv", list(state.lineup))


def _assert_rosters_compliant(
    generated_rosters: Dict[str, Roster],
    all_players: List[dict],
) -> None:
    """Guarantee every freshly generated roster passes the same rule check the
    season-sim gate enforces (``services.roster_validation.validate_roster_state``).

    This is a belt-and-suspenders guard: ACT is built with full positional
    coverage and LOW is generated young (18–21, well under the LOW age limit),
    so this should never trip in practice. But it means a regression in the
    generator — or a future change to the age/cap rules — fails league creation
    loudly instead of silently shipping a league whose teams can't advance the
    calendar (the exact symptom that blocked the sim). Age is computed against
    the real calendar date to match how the validator reads players.csv.
    """

    from datetime import date as _date

    from services.roster_validation import (
        DEFAULT_LEVEL_CAPS,
        validate_roster_state,
    )

    today = _date.today()

    def _age(birthdate: object) -> int | None:
        try:
            born = _date.fromisoformat(str(birthdate)[:10])
        except (TypeError, ValueError):
            return None
        return today.year - born.year - (
            (today.month, today.day) < (born.month, born.day)
        )

    players_map: Dict[str, dict] = {}
    for p in all_players:
        pid = p.get("player_id")
        if not pid:
            continue
        players_map[pid] = {
            "player_id": pid,
            "primary_position": p.get("primary_position", ""),
            "other_positions": p.get("other_positions", ""),
            "is_pitcher": bool(p.get("is_pitcher")),
            "age": _age(p.get("birthdate")),
        }

    problems: List[str] = []
    for team_id, roster in generated_rosters.items():
        result = validate_roster_state(
            current_levels={
                "act": list(roster.act),
                "aaa": list(roster.aaa),
                "low": list(roster.low),
            },
            players=players_map,
            level_caps=DEFAULT_LEVEL_CAPS,
        )
        errors = list(result.errors) if not result.ok else []
        # The 13-pitcher maximum (decision 8), checked here directly so the
        # guard does not depend on which rules the validator has learned.
        act_pitchers = sum(
            1 for pid in roster.act if counts_as_pitcher(players_map.get(pid))
        )
        if act_pitchers > MAX_ACTIVE_PITCHERS:
            errors.append(
                f"Active roster carries {act_pitchers} pitchers "
                f"(maximum {MAX_ACTIVE_PITCHERS})."
            )
        if errors:
            problems.append(f"{team_id}: " + "; ".join(errors))

    if problems:
        raise ValueError(
            "Generated rosters are not rule-compliant: " + " | ".join(problems)
        )


def _initialize_league_state(base_dir: Path) -> None:
    """Reset season persistence files to empty defaults."""

    stats_path = base_dir / "season_stats.json"
    with stats_path.open("w", encoding="utf-8") as fh:
        json.dump({"players": {}, "teams": {}, "history": []}, fh, indent=2)

    progress_path = base_dir / "season_progress.json"
    with progress_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "preseason_done": {
                    "free_agency": False,
                    "training_camp": False,
                    "schedule": False,
                },
                "sim_index": 0,
            },
            fh,
            indent=2,
        )

    news_path = base_dir / "news_feed.txt"
    news_path.write_text("", encoding="utf-8")

    standings_path = base_dir / "standings.json"
    save_standings({}, base_path=standings_path)

    schedule_path = base_dir / "schedule.csv"
    if schedule_path.exists():
        schedule_path.unlink()

    # Remove any existing playoffs brackets from a prior league to avoid
    # showing stale postseason results in the new league.
    try:
        for p in base_dir.glob("playoffs*.json"):
            try:
                p.unlink()
            except Exception:
                pass
    except Exception:
        pass

def create_league(
    base_dir: str | Path,
    divisions: Dict[str, List[Tuple[str, str]]],
    league_name: str,
    rating_profile: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
):
    def _report_progress(phase: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(str(phase))
        except Exception:
            pass

    _report_progress("Loading")
    total_teams = sum(len(teams) for teams in divisions.values())
    if total_teams > MAX_LEAGUE_TEAMS:
        raise ValueError(
            f"League size {total_teams} exceeds the maximum of {MAX_LEAGUE_TEAMS} teams."
        )
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    _purge_old_league(base_dir)
    reset_name_cache()
    rosters_dir = base_dir / "rosters"
    rosters_dir.mkdir(parents=True, exist_ok=True)

    clear_users(base_dir / "users.txt")

    teams_path = base_dir / "teams.csv"
    players_path = base_dir / "players.csv"
    league_path = base_dir / "league.txt"

    team_rows = []
    all_players = []
    existing_abbr = set()
    used_colors: set[str] = set()

    used_ids: set[str] = set()

    def _ensure_unique_id(player: dict) -> dict:
        pid = str(player.get("player_id", ""))
        while not pid or pid in used_ids:
            pid = f"P{random.randint(1000, 9999)}"
        player["player_id"] = pid
        used_ids.add(pid)
        return player

    profile = (
        rating_profile or os.getenv("PB_RATING_PROFILE", "normalized")
    ).strip().lower()
    if profile not in {"arr", "normalized"}:
        profile = "normalized"

    def generate_roster(
        num_pitchers: int,
        num_hitters: int,
        age_range: Tuple[int, int],
        ensure_positions: bool = False,
        closers: int = 0,
    ):
        players = []
        closer_quota = max(0, min(closers, num_pitchers))
        for _ in range(closer_quota):
            data = generate_player(
                is_pitcher=True,
                age_range=age_range,
                pitcher_archetype="closer",
                rating_profile=profile,
            )
            data["is_pitcher"] = True
            players.append(_ensure_unique_id(data))
        for _ in range(num_pitchers - closer_quota):
            data = generate_player(
                is_pitcher=True,
                age_range=age_range,
                rating_profile=profile,
            )
            data["is_pitcher"] = True
            players.append(_ensure_unique_id(data))
        if ensure_positions:
            positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
            for pos in positions:
                data = generate_player(
                    is_pitcher=False,
                    age_range=age_range,
                    primary_position=pos,
                    rating_profile=profile,
                )
                data["is_pitcher"] = False
                players.append(_ensure_unique_id(data))
            remaining = num_hitters - len(positions)
        else:
            remaining = num_hitters
        for _ in range(remaining):
            data = generate_player(
                is_pitcher=False,
                age_range=age_range,
                rating_profile=profile,
            )
            data["is_pitcher"] = False
            players.append(_ensure_unique_id(data))
        return players

    generated_rosters: dict[str, Roster] = {}
    _report_progress("Processing")

    for division, teams in divisions.items():
        for city, name in teams:
            abbr = _abbr(city, name, existing_abbr)
            primary, secondary = _unique_color_pair(used_colors)
            team_rows.append(
                {
                    "team_id": abbr,
                    "name": name,
                    "city": city,
                    "abbreviation": abbr,
                    "division": division,
                    "stadium": f"{name} Stadium",
                    "primary_color": primary,
                    "secondary_color": secondary,
                    "owner_id": "",
                    # Audit L13: no park chosen yet, so the generic park. A
                    # generated "{mascot} Stadium" can collide with a real
                    # park ("Royals Stadium" is Kauffman 1973-93); only an
                    # explicit pick in Team Settings sets a park_id.
                    "park_id": "",
                }
            )

            act_players = generate_roster(
                ACT_PITCHERS, ACT_HITTERS, (21, 38), ensure_positions=True, closers=1
            )
            _ensure_act_positions(act_players)
            aaa_players = generate_roster(AAA_PITCHERS, AAA_HITTERS, (21, 38), closers=1)
            # LOW is for young prospects only — keep the age range comfortably
            # under services.roster_validation.LOW_LEVEL_MAX_AGE (currently 27,
            # i.e. a 26 limit) so generated LOW rosters are always compliant.
            low_players = generate_roster(LOW_PITCHERS, LOW_HITTERS, (18, 21), closers=1)

            roster_levels = {"ACT": act_players, "AAA": aaa_players, "LOW": low_players}

            for level_players in roster_levels.values():
                all_players.extend(level_players)

            roster_file = rosters_dir / f"{abbr}.csv"
            with roster_file.open("w", newline="") as f:
                writer = csv.writer(f)
                for level, players in roster_levels.items():
                    for p in players:
                        writer.writerow([p["player_id"], level])

            pitching_staff = _build_pitching_staff(act_players)
            if pitching_staff:
                staff_file = rosters_dir / f"{abbr}_pitching.csv"
                with staff_file.open("w", newline="") as f:
                    writer = csv.writer(f)
                    for player_id, role in pitching_staff:
                        writer.writerow([player_id, role])

            generated_rosters[abbr] = Roster(
                team_id=abbr,
                act=[p["player_id"] for p in act_players],
                aaa=[p["player_id"] for p in aaa_players],
                low=[p["player_id"] for p in low_players],
            )

    _report_progress("Saving")
    player_models = [_dict_to_model(p) for p in all_players]
    save_players(player_models, players_path)
    # New league rosters replace previously cached entries; drop them so lineup
    # generation reads the freshly-written CSVs instead of stale in-memory data.
    roster_loader.load_roster.cache_clear()
    original_pitcher_guard = roster_loader._ensure_pitcher_depth
    def _skip_pitcher_depth(roster, *, min_pitchers=roster_loader.MIN_ACTIVE_PITCHERS):
        return False
    roster_loader._ensure_pitcher_depth = _skip_pitcher_depth
    roster_root = (base_dir / "rosters").resolve()
    original_lineup_load_roster = lineup_loader.load_roster

    def _load_roster_override(team_id, roster_dir: str | Path = "data/rosters"):
        try:
            resolved = Path(roster_dir)
            if not resolved.is_absolute():
                resolved = (base_dir / resolved).resolve()
            else:
                resolved = resolved.resolve()
        except Exception:
            resolved = None
        if resolved == roster_root:
            cached = generated_rosters.get(team_id)
            if cached is not None:
                return cached
        return original_lineup_load_roster(team_id, roster_dir)

    lineup_loader.load_roster = _load_roster_override
    try:
        _write_default_lineups(base_dir, [row["team_id"] for row in team_rows])
    finally:
        roster_loader._ensure_pitcher_depth = original_pitcher_guard
        lineup_loader.load_roster = original_lineup_load_roster
        roster_loader.load_roster.cache_clear()
    _initialize_league_state(base_dir)

    _report_progress("Validating")
    # Fail loudly if any team was generated out of compliance, rather than
    # shipping a league whose teams can't advance the calendar.
    _assert_rosters_compliant(generated_rosters, all_players)
    with open(teams_path, "w", newline="") as f:
        fieldnames = [
            "team_id","name","city","abbreviation","division","stadium","primary_color","secondary_color","owner_id",
            "park_id",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(team_rows)
    with open(league_path, "w", newline="") as f:
        f.write(league_name)
    _report_progress("Complete")

    # Initialize season context scoped to this league data directory.
    ctx = SeasonContext.load(path=base_dir / "career_index.json")
    ctx.ensure_league(name=league_name, league_id=slugify_league_id(league_name))
    ctx.ensure_current_season(league_year=date.today().year)
    ctx.save()
