import colorsys
import csv
import json
import os
import stat
import random
import shutil
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple, Iterable, Set

from models.player import Player
from models.pitcher import Pitcher
from models.roster import Roster
from utils.player_writer import save_players_to_csv
from playbalance.player_generator import generate_player, reset_name_cache
from utils.user_manager import clear_users
from utils.player_loader import load_players_from_csv
import utils.lineup_loader as lineup_loader
from utils.lineup_loader import build_default_game_state
from utils import roster_loader
from playbalance.season_context import SeasonContext
from services.standings_repository import save_standings

MAX_LEAGUE_TEAMS = 40


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
            os.chmod(path, stat.S_IWRITE)
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
                    os.chmod(item, stat.S_IWRITE)
                    item.unlink()
                except OSError:
                    if item.exists():
                        raise
    # Remove lingering lock files that may live alongside stats.
    lock_file = base_dir / "season_stats.json.lock"
    if lock_file.exists():
        try:
            os.chmod(lock_file, stat.S_IWRITE)
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
    """Return ordered (player_id, role) entries for a pitching staff."""

    pitchers = [p for p in players if p.get("is_pitcher")]  # type: ignore[truthy-bool]
    if not pitchers:
        return []

    def rating(p: dict) -> float:
        return (
            float(p.get("arm", 0)) * 0.5
            + float(p.get("movement", 0)) * 0.3
            + float(p.get("control", 0)) * 0.2
        )

    starters = sorted(
        pitchers, key=lambda p: float(p.get("endurance", 0)), reverse=True
    )[:5]
    starter_ids = {p["player_id"] for p in starters}
    bullpen = [p for p in pitchers if p["player_id"] not in starter_ids]

    closer_candidates = [
        p
        for p in bullpen
        if str(p.get("preferred_pitching_role", "")).upper() == "CL"
        or str(p.get("pitcher_archetype", "")).lower() == "closer"
    ]
    if not closer_candidates:
        closer_candidates = bullpen[:]
    closer = max(closer_candidates, key=rating) if closer_candidates else None

    bullpen = [
        p
        for p in bullpen
        if closer is None or p["player_id"] != closer["player_id"]
    ]
    long_relief = (
        max(bullpen, key=lambda p: float(p.get("endurance", 0))) if bullpen else None
    )
    bullpen = [
        p
        for p in bullpen
        if long_relief is None or p["player_id"] != long_relief["player_id"]
    ]
    setup = sorted(bullpen, key=rating, reverse=True)[:2]
    setup_ids = {p["player_id"] for p in setup}
    bullpen_rest = [p for p in bullpen if p["player_id"] not in setup_ids]

    staff: List[tuple[str, str]] = []
    for idx, pitcher in enumerate(starters, start=1):
        staff.append((pitcher["player_id"], f"SP{idx}"))
    if closer is not None:
        staff.append((closer["player_id"], "CL"))
    for pitcher in setup:
        staff.append((pitcher["player_id"], "SU"))
    if long_relief is not None:
        staff.append((long_relief["player_id"], "LR"))
    for pitcher in bullpen_rest:
        staff.append((pitcher["player_id"], "MR"))
    return staff




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
):
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
                }
            )

            act_players = generate_roster(11, 14, (21, 38), ensure_positions=True, closers=1)
            _ensure_act_positions(act_players)
            aaa_players = generate_roster(7, 8, (21, 38), closers=1)
            low_players = generate_roster(5, 5, (18, 21), closers=1)

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

    player_models = [_dict_to_model(p) for p in all_players]
    save_players_to_csv(player_models, players_path)

    load_players_from_csv.cache_clear()
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

    with open(teams_path, "w", newline="") as f:
        fieldnames = [
            "team_id","name","city","abbreviation","division","stadium","primary_color","secondary_color","owner_id"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(team_rows)
    with open(league_path, "w", newline="") as f:
        f.write(league_name)

    # Initialize season context for the new league.
    ctx = SeasonContext.load()
    ctx.ensure_league(name=league_name)
    ctx.ensure_current_season(league_year=date.today().year)
    ctx.save()
