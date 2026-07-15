"""CPU trade offer evaluator and response scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from services.decision_explanations import DecisionReason, reason
from services.draft_pick_ledger import list_team_tradable_picks, parse_pick_id
from services.standings_repository import load_standings
from services.team_strategy_profiles import resolve_team_strategy_profile
from services.trade_settings import current_league_year
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.team_loader import load_teams

CPU_OWNER_IDS = {"", "cpu", "ai", "none", "computer", "bot"}
_HITTER_KEYS = ("ch", "ph", "sp", "pl", "vl", "sc", "fa", "arm", "gf")
_PITCHER_KEYS = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "arm",
    "fa",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)
_ROUND_PICK_BASE = {
    1: 8.8,
    2: 6.8,
    3: 5.4,
    4: 4.2,
    5: 3.3,
    6: 2.7,
    7: 2.2,
    8: 1.8,
    9: 1.4,
    10: 1.1,
}
_KEY_POSITIONS = {"C", "SS", "CF", "2B", "3B"}


@dataclass(frozen=True)
class CpuTradeEvaluation:
    """Computed CPU response profile for a single offer."""

    team_id: str
    action: str
    total_score: float
    threshold: float
    value_delta: float
    fit_delta: float
    timeline_delta: float
    strategy_profile: str
    competitive_window: str
    reasons: list[DecisionReason]
    details: dict[str, object]
    counter_offer: dict[str, list[str]] | None = None


def is_cpu_owned_team(
    team_id: str | None,
    *,
    teams_by_id: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
) -> bool:
    """Return ``True`` when ``team_id`` is controlled by CPU/AI."""

    token = str(team_id or "").strip().upper()
    if not token:
        return False
    teams = teams_by_id or _load_teams_by_id(data_dir=data_dir)
    team = teams.get(token)
    if team is None:
        return False
    owner = str(getattr(team, "owner_id", "") or "").strip().lower()
    return owner in CPU_OWNER_IDS


def evaluate_cpu_trade_offer(
    trade: object,
    *,
    players_by_id: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
    teams_by_id: Mapping[str, object] | None = None,
    rosters_by_team: Mapping[str, object] | None = None,
    win_pct_by_team: Mapping[str, float] | None = None,
    strategy_profile: str | None = None,
    current_year: int | None = None,
    allow_counter_offers: bool = True,
    timeline_weight_factor: float = 1.0,
) -> CpuTradeEvaluation | None:
    """Evaluate an owner-submitted offer targeting a CPU team.

    Returns ``None`` when the receiving team is not CPU-controlled.
    """

    cpu_team_id = str(getattr(trade, "to_team", "") or "").strip().upper()
    if not cpu_team_id:
        return None

    teams = teams_by_id or _load_teams_by_id(data_dir=data_dir)
    if not is_cpu_owned_team(cpu_team_id, teams_by_id=teams, data_dir=data_dir):
        return None

    players = _coerce_players(players_by_id, data_dir=data_dir)
    roster_map = dict(rosters_by_team or {})
    standings = dict(win_pct_by_team or {})
    if not standings:
        standings = _load_win_pct_by_team(data_dir=data_dir)

    profile = _normalize_profile(strategy_profile)
    if profile is None:
        profile = _resolve_strategy_profile(cpu_team_id, data_dir=data_dir)
    team_win_pct = float(standings.get(cpu_team_id, 0.500) or 0.500)
    window = _resolve_competitive_window(profile, team_win_pct)
    season_year = int(current_year if current_year is not None else current_league_year())

    incoming_ids = [str(pid or "").strip() for pid in getattr(trade, "give_player_ids", []) or []]
    outgoing_ids = [str(pid or "").strip() for pid in getattr(trade, "receive_player_ids", []) or []]
    incoming_pick_ids = [
        str(pid or "").strip() for pid in getattr(trade, "give_pick_ids", []) or []
    ]
    outgoing_pick_ids = [
        str(pid or "").strip() for pid in getattr(trade, "receive_pick_ids", []) or []
    ]

    incoming_players = [players[pid] for pid in incoming_ids if pid in players]
    outgoing_players = [players[pid] for pid in outgoing_ids if pid in players]
    roster_fit = _build_roster_fit_context(
        cpu_team_id,
        players_by_id=players,
        rosters_by_team=roster_map,
        data_dir=data_dir,
    )

    value_in = sum(_player_current_value(player) for player in incoming_players)
    value_out = sum(_player_current_value(player) for player in outgoing_players)
    pick_in = sum(
        _pick_value(pick_id, window=window, current_year=season_year)
        for pick_id in incoming_pick_ids
    )
    pick_out = sum(
        _pick_value(pick_id, window=window, current_year=season_year)
        for pick_id in outgoing_pick_ids
    )
    value_delta = (value_in + pick_in) - (value_out + pick_out)

    fit_in = sum(
        _fit_value(
            player,
            roster_fit=roster_fit,
            strategy_profile=profile,
        )
        for player in incoming_players
    )
    fit_out = sum(
        _fit_value(
            player,
            roster_fit=roster_fit,
            strategy_profile=profile,
        )
        for player in outgoing_players
    )
    fit_delta = fit_in - fit_out

    timeline_in = sum(
        _timeline_value(player, window=window, strategy_profile=profile)
        for player in incoming_players
    )
    timeline_out = sum(
        _timeline_value(player, window=window, strategy_profile=profile)
        for player in outgoing_players
    )
    timeline_pick_in = sum(
        _pick_timeline_bonus(pick_id, window=window, current_year=season_year)
        for pick_id in incoming_pick_ids
    )
    timeline_pick_out = sum(
        _pick_timeline_bonus(pick_id, window=window, current_year=season_year)
        for pick_id in outgoing_pick_ids
    )
    timeline_delta = (timeline_in + timeline_pick_in) - (timeline_out + timeline_pick_out)

    timeline_w = 0.12 * max(0.25, min(3.0, float(timeline_weight_factor)))
    total_score = (0.68 * value_delta) + (0.20 * fit_delta) + (timeline_w * timeline_delta)
    threshold_base = _window_threshold(window)
    required_score = threshold_base + _decision_variation(
        str(getattr(trade, "trade_id", "") or ""),
        cpu_team_id,
    )
    action = "accept" if total_score >= required_score else "reject"
    counter_offer: dict[str, list[str]] | None = None
    score_gap = float(required_score) - float(total_score)
    if action == "reject" and allow_counter_offers and 0.0 < score_gap <= 1.8:
        counter_offer = _build_counter_offer(
            from_team=str(getattr(trade, "from_team", "") or "").strip().upper(),
            to_team=cpu_team_id,
            incoming_ids=incoming_ids,
            outgoing_ids=outgoing_ids,
            incoming_pick_ids=incoming_pick_ids,
            outgoing_pick_ids=outgoing_pick_ids,
            required_gain=score_gap + 0.12,
            players_by_id=players,
            roster_fit=roster_fit,
            strategy_profile=profile,
            window=window,
            current_year=season_year,
            data_dir=data_dir,
        )
        if counter_offer is not None:
            action = "counter"

    reasons = _build_reasons(
        action=action,
        value_delta=value_delta,
        fit_delta=fit_delta,
        timeline_delta=timeline_delta,
        strategy_profile=profile,
        window=window,
        roster_fit=roster_fit,
    )
    if incoming_pick_ids or outgoing_pick_ids:
        reasons.append(
            reason(
                "draft_capital",
                "Draft-pick value and timeline impact were included in trade scoring.",
                details={
                    "incoming_picks": len(incoming_pick_ids),
                    "outgoing_picks": len(outgoing_pick_ids),
                },
            )
        )
    if action == "counter" and counter_offer is not None:
        reasons.append(
            reason(
                "counter_offer",
                "Offer was close enough that CPU generated a counter package.",
                details={
                    "incoming_players": len(counter_offer.get("incoming_player_ids", [])),
                    "outgoing_players": len(counter_offer.get("outgoing_player_ids", [])),
                    "incoming_picks": len(counter_offer.get("incoming_pick_ids", [])),
                    "outgoing_picks": len(counter_offer.get("outgoing_pick_ids", [])),
                },
            )
        )

    return CpuTradeEvaluation(
        team_id=cpu_team_id,
        action=action,
        total_score=float(total_score),
        threshold=float(required_score),
        value_delta=float(value_delta),
        fit_delta=float(fit_delta),
        timeline_delta=float(timeline_delta),
        strategy_profile=profile,
        competitive_window=window,
        reasons=reasons,
        details={
            "incoming_players": len(incoming_players),
            "outgoing_players": len(outgoing_players),
            "incoming_picks": len(incoming_pick_ids),
            "outgoing_picks": len(outgoing_pick_ids),
            "team_win_pct": team_win_pct,
            "roster_needs": sorted(roster_fit.get("needs", set())),
            "score_gap": round(score_gap, 3),
        },
        counter_offer=counter_offer,
    )


def _coerce_players(
    players_by_id: Mapping[str, object] | None,
    *,
    data_dir: Path | str | None = None,
) -> dict[str, object]:
    if isinstance(players_by_id, Mapping):
        return {str(key): value for key, value in players_by_id.items()}
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    players_path = resolved_data_dir / "players.csv"
    loaded = load_players_from_csv(players_path)
    return {str(getattr(player, "player_id", "") or ""): player for player in loaded}


def _load_teams_by_id(*, data_dir: Path | str | None = None) -> dict[str, object]:
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    teams_path = resolved_data_dir / "teams.csv"
    teams: dict[str, object] = {}
    try:
        for team in load_teams(teams_path):
            team_id = str(getattr(team, "team_id", "") or "").strip().upper()
            if team_id:
                teams[team_id] = team
    except Exception:
        return {}
    return teams


def _load_win_pct_by_team(*, data_dir: Path | str | None = None) -> dict[str, float]:
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    standings_path = resolved_data_dir / "standings.json"
    try:
        standings = load_standings(base_path=standings_path, normalize=True)
    except Exception:
        standings = {}
    result: dict[str, float] = {}
    for team_id, row in standings.items():
        token = str(team_id or "").strip().upper()
        if not token:
            continue
        result[token] = _extract_win_pct(row)
    return result


def _resolve_strategy_profile(team_id: str, *, data_dir: Path | str | None = None) -> str:
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    try:
        resolved = resolve_team_strategy_profile(team_id, data_dir=resolved_data_dir)
    except Exception:
        return "balanced"
    profile = str(getattr(resolved, "profile", "balanced") or "balanced").strip().lower()
    return profile if profile else "balanced"


def _normalize_profile(profile: str | None) -> str | None:
    token = str(profile or "").strip().lower()
    if not token:
        return None
    return token


def _resolve_competitive_window(strategy_profile: str, win_pct: float) -> str:
    profile = str(strategy_profile or "balanced").strip().lower()
    if profile in {"win_now", "power_offense"}:
        return "contend"
    if profile == "development_focus":
        return "rebuild"
    if win_pct >= 0.560:
        return "contend"
    if win_pct <= 0.440:
        return "rebuild"
    return "balanced"


def _extract_win_pct(row: object) -> float:
    if not isinstance(row, Mapping):
        return 0.500
    direct = row.get("win_pct")
    if direct is not None:
        try:
            value = float(direct)
            if value > 1.0:
                return max(0.0, min(1.0, value / 100.0))
            return max(0.0, min(1.0, value))
        except Exception:
            pass
    wins = _safe_int(row.get("wins"))
    losses = _safe_int(row.get("losses"))
    total = wins + losses
    if total <= 0:
        return 0.500
    return float(wins) / float(total)


def _build_roster_fit_context(
    team_id: str,
    *,
    players_by_id: Mapping[str, object],
    rosters_by_team: Mapping[str, object],
    data_dir: Path | str | None = None,
) -> dict[str, object]:
    roster = rosters_by_team.get(team_id)
    if roster is None:
        resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
        try:
            roster = load_roster(team_id, resolved_data_dir / "rosters")
        except Exception:
            roster = None
    active_ids = list(getattr(roster, "act", []) or [])
    active_players = [players_by_id[pid] for pid in active_ids if pid in players_by_id]
    pitchers = [player for player in active_players if _is_pitcher(player)]
    hitters = [player for player in active_players if not _is_pitcher(player)]
    pos_counts: dict[str, int] = {}
    for player in hitters:
        primary = str(getattr(player, "primary_position", "") or "").strip().upper()
        if not primary or primary == "P":
            continue
        pos_counts[primary] = int(pos_counts.get(primary, 0)) + 1
    needs: set[str] = set()
    if len(pitchers) < 12:
        needs.add("P")
    for pos in ("C", "SS", "CF", "2B", "3B", "1B", "LF", "RF"):
        if int(pos_counts.get(pos, 0)) <= 0:
            needs.add(pos)
    surplus = {pos for pos, count in pos_counts.items() if int(count) >= 3}
    return {
        "pitchers": len(pitchers),
        "hitters": len(hitters),
        "needs": needs,
        "surplus": surplus,
        "pos_counts": pos_counts,
    }


def _is_pitcher(player: object) -> bool:
    if bool(getattr(player, "is_pitcher", False)):
        return True
    return str(getattr(player, "primary_position", "") or "").strip().upper() == "P"


def _player_current_value(player: object) -> float:
    current = _overall_score(player, potential=False)
    potential = _overall_score(player, potential=True)
    upside = max(0.0, potential - current)
    age = _player_age(player)
    age_penalty = 0.0
    if age is not None and age > 33:
        age_penalty = (age - 33) * 0.28
    injury_penalty = 1.1 if bool(getattr(player, "injured", False)) else 0.0
    return (current * 0.12) + (upside * 0.04) - age_penalty - injury_penalty


def _fit_value(
    player: object,
    *,
    roster_fit: Mapping[str, object],
    strategy_profile: str,
) -> float:
    profile = str(strategy_profile or "balanced").strip().lower()
    needs = set(roster_fit.get("needs", set()) or set())
    surplus = set(roster_fit.get("surplus", set()) or set())
    pos_counts = roster_fit.get("pos_counts", {})
    if not isinstance(pos_counts, Mapping):
        pos_counts = {}

    if _is_pitcher(player):
        fit = 0.4
        if "P" in needs:
            fit += 1.8
        pitcher_count = _safe_int(roster_fit.get("pitchers"), fallback=13)
        if pitcher_count >= 14:
            fit -= 0.5
        if profile in {"win_now", "defense_first"}:
            fit += _norm(getattr(player, "control", 0)) * 0.8
            fit += _norm(getattr(player, "movement", 0)) * 0.7
        if profile == "development_focus":
            age = _player_age(player)
            if age is not None and age <= 24:
                fit += 0.9
        return fit

    primary = str(getattr(player, "primary_position", "") or "").strip().upper()
    fit = 0.3
    if primary in needs:
        fit += 1.6
    if primary in surplus:
        fit -= 0.6
    if int(pos_counts.get(primary, 0) or 0) == 0:
        fit += 0.5
    if profile == "defense_first":
        fit += _norm(getattr(player, "fa", 0)) * 0.9
        fit += _norm(getattr(player, "arm", 0)) * 0.6
        if primary in _KEY_POSITIONS:
            fit += 0.4
    elif profile == "power_offense":
        fit += _norm(getattr(player, "ph", 0)) * 0.9
        fit += _norm(getattr(player, "ch", 0)) * 0.4
    elif profile == "development_focus":
        age = _player_age(player)
        if age is not None and age <= 24:
            fit += 0.8
    return fit


def _timeline_value(player: object, *, window: str, strategy_profile: str) -> float:
    age = _player_age(player)
    current = _overall_score(player, potential=False)
    potential = _overall_score(player, potential=True)
    upside = max(0.0, potential - current)
    profile = str(strategy_profile or "balanced").strip().lower()

    if window == "contend":
        age_bonus = _prime_age_bonus(age, prime_age=29)
        value = (current * 0.10) + age_bonus + (upside * 0.01)
        if profile == "win_now":
            value += 0.5
        return value
    if window == "rebuild":
        youth_bonus = _youth_bonus(age)
        value = (current * 0.05) + (upside * 0.05) + youth_bonus
        if profile == "development_focus":
            value += 0.5
        return value
    # balanced window
    return (current * 0.07) + (upside * 0.025) + (_prime_age_bonus(age, prime_age=28) * 0.4)


def _pick_value(pick_id: str, *, window: str, current_year: int) -> float:
    try:
        year, round_no, _team = parse_pick_id(pick_id)
    except Exception:
        return 0.0
    base = float(_ROUND_PICK_BASE.get(round_no, max(0.7, 1.0 - (round_no - 10) * 0.08)))
    years_out = max(0, int(year) - int(current_year) - 1)
    discount = 1.0 / (1.0 + (0.26 * years_out))
    modifier = 1.0
    if window == "rebuild":
        modifier = 1.15
    elif window == "contend":
        modifier = 0.92
    return base * discount * modifier


def _pick_timeline_bonus(pick_id: str, *, window: str, current_year: int) -> float:
    try:
        year, round_no, _team = parse_pick_id(pick_id)
    except Exception:
        return 0.0
    years_out = max(0, int(year) - int(current_year) - 1)
    round_factor = max(0.3, 1.3 - (0.08 * max(0, round_no - 1)))
    if window == "rebuild":
        return round_factor * (1.0 + (0.25 * min(4, years_out)))
    if window == "contend":
        return round_factor * -0.35
    return round_factor * 0.15


def _window_threshold(window: str) -> float:
    if window == "contend":
        return 0.90
    if window == "rebuild":
        return 0.10
    return 0.45


def _decision_variation(trade_id: str, team_id: str) -> float:
    token = f"{trade_id}|{team_id}"
    digest = sha256(token.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / float(0xFFFFFFFF)
    return (bucket - 0.5) * 0.44


def _build_counter_offer(
    *,
    from_team: str,
    to_team: str,
    incoming_ids: list[str],
    outgoing_ids: list[str],
    incoming_pick_ids: list[str],
    outgoing_pick_ids: list[str],
    required_gain: float,
    players_by_id: Mapping[str, object],
    roster_fit: Mapping[str, object],
    strategy_profile: str,
    window: str,
    current_year: int,
    data_dir: Path | str | None = None,
) -> dict[str, list[str]] | None:
    if not from_team or not to_team:
        return None

    base_incoming_players = [pid for pid in incoming_ids if pid in players_by_id]
    base_outgoing_players = [pid for pid in outgoing_ids if pid in players_by_id]
    base_incoming_picks = [pid for pid in incoming_pick_ids if str(pid).strip()]
    base_outgoing_picks = [pid for pid in outgoing_pick_ids if str(pid).strip()]

    if (not base_incoming_players and not base_incoming_picks) or (
        not base_outgoing_players and not base_outgoing_picks
    ):
        return None

    candidates: list[tuple[float, dict[str, list[str]], str]] = []
    min_gain = max(0.08, float(required_gain))

    # Option 1: CPU gives up less draft capital (remove highest-value outgoing pick).
    if base_outgoing_picks and (
        len(base_outgoing_picks) > 1 or len(base_outgoing_players) > 0
    ):
        ranked = sorted(
            base_outgoing_picks,
            key=lambda pick_id: _asset_score_delta_for_pick(
                pick_id,
                window=window,
                current_year=current_year,
            ),
            reverse=True,
        )
        for pick_id in ranked:
            gain = _asset_score_delta_for_pick(
                pick_id,
                window=window,
                current_year=current_year,
            )
            payload = {
                "incoming_player_ids": list(base_incoming_players),
                "outgoing_player_ids": list(base_outgoing_players),
                "incoming_pick_ids": list(base_incoming_picks),
                "outgoing_pick_ids": [pid for pid in base_outgoing_picks if pid != pick_id],
            }
            if _is_valid_counter_payload(payload):
                candidates.append((gain, payload, f"remove_outgoing_pick:{pick_id}"))

    # Option 2: CPU gives up one fewer player (remove highest-impact outgoing player).
    if base_outgoing_players and (
        len(base_outgoing_players) > 1 or len(base_outgoing_picks) > 0
    ):
        ranked_players = sorted(
            base_outgoing_players,
            key=lambda pid: _asset_score_delta_for_player(
                players_by_id.get(pid),
                roster_fit=roster_fit,
                strategy_profile=strategy_profile,
                window=window,
            ),
            reverse=True,
        )
        for pid in ranked_players:
            player = players_by_id.get(pid)
            gain = _asset_score_delta_for_player(
                player,
                roster_fit=roster_fit,
                strategy_profile=strategy_profile,
                window=window,
            )
            payload = {
                "incoming_player_ids": list(base_incoming_players),
                "outgoing_player_ids": [token for token in base_outgoing_players if token != pid],
                "incoming_pick_ids": list(base_incoming_picks),
                "outgoing_pick_ids": list(base_outgoing_picks),
            }
            if _is_valid_counter_payload(payload):
                candidates.append((gain, payload, f"remove_outgoing_player:{pid}"))

    # Option 3: ask for one extra owner pick.
    try:
        tradable_picks = list_team_tradable_picks(from_team)
    except Exception:
        tradable_picks = []
    pick_candidates = [
        str(getattr(pick, "pick_id", "") or "")
        for pick in tradable_picks
        if str(getattr(pick, "pick_id", "") or "")
        and str(getattr(pick, "pick_id", "") or "") not in base_incoming_picks
    ]
    ranked_extra_picks = sorted(
        pick_candidates,
        key=lambda pick_id: _asset_score_delta_for_pick(
            pick_id,
            window=window,
            current_year=current_year,
        ),
    )
    for pick_id in ranked_extra_picks:
        gain = _asset_score_delta_for_pick(
            pick_id,
            window=window,
            current_year=current_year,
        )
        payload = {
            "incoming_player_ids": list(base_incoming_players),
            "outgoing_player_ids": list(base_outgoing_players),
            "incoming_pick_ids": list(base_incoming_picks) + [pick_id],
            "outgoing_pick_ids": list(base_outgoing_picks),
        }
        if _is_valid_counter_payload(payload):
            candidates.append((gain, payload, f"add_incoming_pick:{pick_id}"))

    # Option 4: ask for one extra owner player.
    extra_owner_players = _extra_owner_players(
        from_team,
        already_incoming=set(base_incoming_players),
        players_by_id=players_by_id,
        data_dir=data_dir,
    )
    ranked_extra_players = sorted(
        extra_owner_players,
        key=lambda pid: _asset_score_delta_for_player(
            players_by_id.get(pid),
            roster_fit=roster_fit,
            strategy_profile=strategy_profile,
            window=window,
        ),
    )
    for pid in ranked_extra_players:
        gain = _asset_score_delta_for_player(
            players_by_id.get(pid),
            roster_fit=roster_fit,
            strategy_profile=strategy_profile,
            window=window,
        )
        payload = {
            "incoming_player_ids": list(base_incoming_players) + [pid],
            "outgoing_player_ids": list(base_outgoing_players),
            "incoming_pick_ids": list(base_incoming_picks),
            "outgoing_pick_ids": list(base_outgoing_picks),
        }
        if _is_valid_counter_payload(payload):
            candidates.append((gain, payload, f"add_incoming_player:{pid}"))

    if not candidates:
        return None
    # Prefer the smallest gain that clears the needed margin; fallback to best available.
    viable = [entry for entry in candidates if entry[0] >= min_gain]
    ranked = viable if viable else candidates
    ranked.sort(key=lambda entry: (abs(entry[0] - min_gain), entry[0]))
    selected_gain, selected_payload, selected_kind = ranked[0]
    if selected_gain <= 0.0:
        return None
    selected_payload["counter_kind"] = [selected_kind]
    return selected_payload


def _is_valid_counter_payload(payload: Mapping[str, list[str]]) -> bool:
    incoming_players = list(payload.get("incoming_player_ids", []) or [])
    outgoing_players = list(payload.get("outgoing_player_ids", []) or [])
    incoming_picks = list(payload.get("incoming_pick_ids", []) or [])
    outgoing_picks = list(payload.get("outgoing_pick_ids", []) or [])
    return bool(incoming_players or incoming_picks) and bool(
        outgoing_players or outgoing_picks
    )


def _asset_score_delta_for_player(
    player: object | None,
    *,
    roster_fit: Mapping[str, object],
    strategy_profile: str,
    window: str,
) -> float:
    if player is None:
        return 0.0
    value = _player_current_value(player)
    fit = _fit_value(player, roster_fit=roster_fit, strategy_profile=strategy_profile)
    timeline = _timeline_value(player, window=window, strategy_profile=strategy_profile)
    return (0.68 * value) + (0.20 * fit) + (0.12 * timeline)


def _asset_score_delta_for_pick(
    pick_id: str,
    *,
    window: str,
    current_year: int,
) -> float:
    value = _pick_value(pick_id, window=window, current_year=current_year)
    timeline = _pick_timeline_bonus(pick_id, window=window, current_year=current_year)
    return (0.68 * value) + (0.12 * timeline)


def _extra_owner_players(
    from_team: str,
    *,
    already_incoming: set[str],
    players_by_id: Mapping[str, object],
    data_dir: Path | str | None = None,
) -> list[str]:
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    try:
        roster = load_roster(from_team, resolved_data_dir / "rosters")
    except Exception:
        return []
    candidates: list[str] = []
    for pid in list(getattr(roster, "act", []) or []):
        token = str(pid or "").strip()
        if not token or token in already_incoming:
            continue
        if token not in players_by_id:
            continue
        candidates.append(token)
    return candidates


def _build_reasons(
    *,
    action: str,
    value_delta: float,
    fit_delta: float,
    timeline_delta: float,
    strategy_profile: str,
    window: str,
    roster_fit: Mapping[str, object],
) -> list[DecisionReason]:
    status_text = "accepted" if action == "accept" else "countered" if action == "counter" else "rejected"
    reasons: list[DecisionReason] = [
        reason(
            "cpu_trade_evaluator",
            (
                f"CPU {status_text} the offer after evaluating current value, "
                "roster fit, and timeline impact."
            ),
        ),
        reason(
            "strategy_window",
            (
                f"Team strategy profile '{strategy_profile}' evaluated as '{window}' "
                "competitive window for this decision."
            ),
        ),
    ]
    reasons.append(
        reason(
            "value_balance",
            (
                "Incoming vs outgoing value delta "
                f"scored {value_delta:+.2f} for the CPU team."
            ),
            details={"value_delta": round(value_delta, 3)},
        )
    )
    needs = sorted(set(roster_fit.get("needs", set()) or set()))
    reasons.append(
        reason(
            "roster_fit",
            (
                "Roster-fit delta scored "
                f"{fit_delta:+.2f}; current needs considered: "
                f"{', '.join(needs) if needs else 'none'}."
            ),
            details={"fit_delta": round(fit_delta, 3), "needs": needs},
        )
    )
    reasons.append(
        reason(
            "timeline_alignment",
            f"Timeline and age/upside alignment delta scored {timeline_delta:+.2f}.",
            details={"timeline_delta": round(timeline_delta, 3)},
        )
    )
    return reasons


def _overall_score(player: object, *, potential: bool) -> float:
    is_pitcher = _is_pitcher(player)
    keys = _PITCHER_KEYS if is_pitcher else _HITTER_KEYS
    values: list[float] = []
    for key in keys:
        rating = _rating_value(player, key, potential=potential)
        if rating is None:
            continue
        values.append(rating)
    if not values:
        return 50.0
    avg = sum(values) / float(len(values))
    return max(0.0, min(99.0, avg))


def _rating_value(player: object, key: str, *, potential: bool) -> float | None:
    if potential:
        pot_key = f"pot_{key}"
        val = _safe_float(getattr(player, pot_key, None), fallback=None)
        if val is not None:
            return max(0.0, min(99.0, val))
        potential_blob = getattr(player, "potential", {})
        if isinstance(potential_blob, Mapping):
            val = _safe_float(
                potential_blob.get(pot_key, potential_blob.get(key)),
                fallback=None,
            )
            if val is not None:
                return max(0.0, min(99.0, val))
    val = _safe_float(getattr(player, key, None), fallback=None)
    if val is None:
        return None
    return max(0.0, min(99.0, val))


def _player_age(player: object) -> int | None:
    age_val = getattr(player, "age", None)
    if isinstance(age_val, (int, float)):
        return max(14, min(50, int(age_val)))
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if len(birthdate) >= 4 and birthdate[:4].isdigit():
        birth_year = int(birthdate[:4])
        season_year = current_league_year()
        return max(14, min(50, season_year - birth_year))
    return None


def _prime_age_bonus(age: int | None, *, prime_age: int) -> float:
    if age is None:
        return 0.0
    distance = abs(int(age) - int(prime_age))
    return max(-1.2, 1.3 - (distance * 0.16))


def _youth_bonus(age: int | None) -> float:
    if age is None:
        return 0.0
    if age <= 23:
        return 1.4
    if age <= 26:
        return 0.7
    if age >= 32:
        return -0.8
    return 0.2


def _norm(value: object) -> float:
    numeric = _safe_float(value, fallback=0.0)
    return max(0.0, min(1.0, numeric / 99.0))


def _safe_float(value: object, *, fallback: float | None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return fallback


def _safe_int(value: object, *, fallback: int = 0) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except Exception:
        return int(fallback)


__all__ = [
    "CPU_OWNER_IDS",
    "CpuTradeEvaluation",
    "evaluate_cpu_trade_offer",
    "is_cpu_owned_team",
]
