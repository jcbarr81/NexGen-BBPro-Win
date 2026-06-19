"""Qualifying offers (QO) + draft compensation — CPU-resolved core (7.0).

A departing free agent who reached full free agency (≈6 service years) and was a
quality veteran can receive a one-year **qualifying offer** from his former team.
The player accepts (re-signs one year at the QO value) or declines (stays a free
agent). If a *declined*-QO player later signs with a **different** team, the
former team is owed draft compensation in the next amateur draft.

This module is CPU-resolved: tender / accept / decline are decided automatically.
A human-owner per-player decision UI is a future enhancement.

Compensation is modelled as **improved draft position** (the team that lost a
QO'd free agent moves ahead of the team that signed him) rather than a literal
extra pick — the draft engine uses a single repeating team order per round, so
true supplemental picks would require an engine change. Position compensation is
safe (same pick count, same order length) and captures the intent.

State lives in ``qualifying_offers_<year>.json``:
    {"year": Y, "qo_value": N,
     "players": {pid: {"team_id", "qo_value", "decision", "signed_with",
                       "comp_awarded"}}}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from utils.path_utils import get_data_dir

QO_VALUE = 20_000_000
# ≈6 service years ⇒ the player has reached full (non-arbitration) free agency.
_FULL_FA_SERVICE_DAYS = 6 * 172
# A "quality veteran worth a QO" proxy: his expiring salary was at least this.
_QO_QUALITY_SALARY = 8_000_000
# Days credited for the just-finished season when judging service at expiry.
_SEASON_SERVICE_DAYS = 172

__all__ = [
    "QO_VALUE",
    "snapshot_qo_candidates",
    "process_qualifying_offers",
    "track_qo_signing",
    "load_qo_state",
    "compensation_for_draft",
    "apply_draft_compensation",
    "qualifying_offer_summary",
    "list_team_qualifying_offers",
    "resolve_qualifying_offer",
]


def _cpu_owned(owner_id: object) -> bool:
    return str(owner_id or "").strip().lower() in {
        "",
        "cpu",
        "ai",
        "none",
        "computer",
        "bot",
    }


def human_team_ids(*, data_dir: Path | str | None = None) -> set[str]:
    """Team ids that are human-owned (their QO tenders are owner decisions)."""

    import csv

    resolved = _resolve_dir(data_dir)
    path = resolved / "teams.csv"
    out: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                tid = str(row.get("team_id") or "").strip()
                if tid and not _cpu_owned(row.get("owner_id")):
                    out.add(tid)
    except Exception:
        return set()
    return out


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _resolve_dir(data_dir: Path | str | None) -> Path:
    return get_data_dir() if data_dir is None else Path(data_dir)


def _qo_path(year: int, data_dir: Path) -> Path:
    return data_dir / f"qualifying_offers_{int(year)}.json"


def load_qo_state(year: int, *, data_dir: Path | str | None = None) -> Dict[str, object]:
    path = _qo_path(int(year), _resolve_dir(data_dir))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"year": int(year), "qo_value": QO_VALUE, "players": {}}
    if not isinstance(payload, dict):
        return {"year": int(year), "qo_value": QO_VALUE, "players": {}}
    if not isinstance(payload.get("players"), dict):
        payload["players"] = {}
    return payload


def _save_qo_state(year: int, state: Mapping[str, object], *, data_dir: Path) -> None:
    path = _qo_path(int(year), data_dir)
    try:
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def snapshot_qo_candidates(*, data_dir: Path | str | None = None) -> Dict[str, Dict[str, object]]:
    """Capture (team, service, salary) for players whose contract expires this
    offseason — call this BEFORE the contract rollover removes those deals.

    A candidate is a contract with ``years_left <= 1`` (expiring now) and no
    exercised option. Returns ``{player_id: {team_id, service_time_days, salary}}``.
    """

    resolved = _resolve_dir(data_dir)
    try:
        from services.contracts_service import load_contracts_payload

        payload = load_contracts_payload(data_dir=resolved)
    except Exception:
        return {}
    players = payload.get("players") if isinstance(payload, Mapping) else None
    if not isinstance(players, Mapping):
        return {}

    out: Dict[str, Dict[str, object]] = {}
    for raw_pid, raw in players.items():
        pid = str(raw_pid or "").strip()
        if not pid or not isinstance(raw, Mapping):
            continue
        years_left = _safe_int(raw.get("years_left", 1))
        if years_left > 1:
            continue  # not expiring this offseason
        # If a team option exists it will be exercised/declined by the rollover;
        # treat option contracts as non-QO candidates here for simplicity.
        options = raw.get("options")
        if isinstance(options, list) and options:
            continue
        team_id = str(raw.get("team_id") or "").strip()
        if not team_id:
            continue
        out[pid] = {
            "team_id": team_id,
            # Credit the season that just finished toward full-FA service.
            "service_time_days": _safe_int(raw.get("service_time_days", 0))
            + _SEASON_SERVICE_DAYS,
            "salary": _safe_int(raw.get("annual_salary", 0)),
        }
    return out


def _finance_qo_enabled(data_dir: Path, league_id: str | None) -> bool:
    try:
        from services.finance_settings import load_financial_settings

        settings = load_financial_settings(
            path=data_dir / "league_financial_settings.json", league_id=league_id
        )
        return bool(settings.enabled) and settings.module_level("gm_free_agency") != "off"
    except Exception:
        return False


def process_qualifying_offers(
    year: int,
    *,
    candidates: Mapping[str, Mapping[str, object]],
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    owner_teams: Optional[set] = None,
) -> Dict[str, object]:
    """CPU-resolve qualifying offers for ``candidates`` (from
    :func:`snapshot_qo_candidates`). Writes ``qualifying_offers_<year>.json``.

    Eligible = full FA (service ≥ ~6 yrs) + a quality salary. The former team
    auto-tenders. The player accepts the one-year QO when his expiring salary
    was at/under the QO value (re-signs that team), otherwise declines and bets
    on the open market. Accepted players get a one-year contract restored.
    """

    resolved = _resolve_dir(data_dir)
    if not _finance_qo_enabled(resolved, league_id):
        return {"applied": False, "reason": "finance_disabled", "tendered": 0}

    owners = {str(t).strip() for t in (owner_teams or set())}
    players: Dict[str, Dict[str, object]] = {}
    tendered = accepted = declined = pending = 0
    for pid, info in (candidates or {}).items():
        if not isinstance(info, Mapping):
            continue
        service = _safe_int(info.get("service_time_days", 0))
        salary = _safe_int(info.get("salary", 0))
        team_id = str(info.get("team_id") or "").strip()
        if not team_id:
            continue
        if service < _FULL_FA_SERVICE_DAYS or salary < _QO_QUALITY_SALARY:
            continue  # not a QO-worthy full free agent

        record = {
            "team_id": team_id,
            "qo_value": QO_VALUE,
            "salary": salary,
            "decision": "pending",
            "signed_with": None,
            "comp_awarded": False,
        }
        if team_id in owners:
            # Leave the tender to the human owner (resolve_qualifying_offer).
            pending += 1
            players[str(pid)] = record
            continue

        # CPU auto-tenders, then the player accepts/declines on value.
        tendered += 1
        accepts = salary <= QO_VALUE
        record["decision"] = "accepted" if accepts else "declined"
        if accepts:
            accepted += 1
            _resign_on_qo(str(pid), team_id, data_dir=resolved)
        else:
            declined += 1
        players[str(pid)] = record

    state = {"year": int(year), "qo_value": QO_VALUE, "players": players}
    _save_qo_state(int(year), state, data_dir=resolved)
    return {
        "applied": True,
        "tendered": tendered,
        "accepted": accepted,
        "declined": declined,
        "pending": pending,
    }


def _resign_on_qo(player_id: str, team_id: str, *, data_dir: Path) -> None:
    try:
        from services.contracts_service import upsert_contract

        upsert_contract(
            str(player_id),
            team_id=team_id,
            annual_salary=QO_VALUE,
            years_left=1,
            data_dir=data_dir,
        )
    except Exception:
        pass


def list_team_qualifying_offers(
    team_id: str, year: int, *, data_dir: Path | str | None = None
) -> List[Dict[str, object]]:
    """QO records (pending + resolved) for ``team_id`` in ``year``."""

    resolved = _resolve_dir(data_dir)
    state = load_qo_state(int(year), data_dir=resolved)
    players = state.get("players")
    tid = str(team_id or "").strip()
    out: List[Dict[str, object]] = []
    if isinstance(players, dict):
        for pid, rec in players.items():
            if isinstance(rec, dict) and str(rec.get("team_id") or "").strip() == tid:
                out.append({"player_id": pid, **rec})
    return out


def resolve_qualifying_offer(
    team_id: str,
    player_id: str,
    year: int,
    *,
    tender: bool,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Owner decision for a pending QO. ``tender=True`` extends the offer (the
    player then accepts/declines on value); ``tender=False`` lets him walk as a
    free agent with no compensation attached."""

    resolved = _resolve_dir(data_dir)
    y = int(year)
    state = load_qo_state(y, data_dir=resolved)
    players = state.get("players")
    if not isinstance(players, dict):
        return {"applied": False, "reason": "no_qo_state"}
    rec = players.get(str(player_id))
    if not isinstance(rec, dict) or str(rec.get("team_id") or "").strip() != str(team_id or "").strip():
        return {"applied": False, "reason": "not_found"}
    if rec.get("decision") != "pending":
        return {"applied": False, "reason": "already_resolved", "decision": rec.get("decision")}

    if not tender:
        rec["decision"] = "not_tendered"
        _save_qo_state(y, state, data_dir=resolved)
        return {"applied": True, "decision": "not_tendered"}

    salary = _safe_int(rec.get("salary", 0))
    accepts = salary <= QO_VALUE
    rec["decision"] = "accepted" if accepts else "declined"
    if accepts:
        _resign_on_qo(str(player_id), str(team_id), data_dir=resolved)
    _save_qo_state(y, state, data_dir=resolved)
    return {"applied": True, "decision": rec["decision"]}


def track_qo_signing(
    player_id: str,
    new_team_id: str,
    *,
    year: int | None = None,
    data_dir: Path | str | None = None,
) -> bool:
    """When a free agent signs, flag draft compensation if he had a *declined*
    qualifying offer and signed with a **different** team than the one that
    tendered it. Returns True when compensation was newly awarded.
    """

    resolved = _resolve_dir(data_dir)
    pid = str(player_id or "").strip()
    new_team = str(new_team_id or "").strip()
    if not pid or not new_team:
        return False

    # Look across recent QO files (current + prior year) for this player.
    from datetime import date as _date

    candidate_years: List[int] = []
    if year is not None:
        candidate_years.append(int(year))
    else:
        this_year = _date.today().year
        candidate_years.extend([this_year, this_year - 1, this_year + 1])

    for y in candidate_years:
        state = load_qo_state(y, data_dir=resolved)
        players = state.get("players")
        if not isinstance(players, dict):
            continue
        rec = players.get(pid)
        if not isinstance(rec, dict):
            continue
        if rec.get("decision") != "declined":
            return False
        if rec.get("comp_awarded"):
            return False
        if str(rec.get("team_id") or "").strip() == new_team:
            # Re-signed with the same team — no compensation.
            rec["signed_with"] = new_team
            _save_qo_state(y, state, data_dir=resolved)
            return False
        rec["signed_with"] = new_team
        rec["comp_awarded"] = True
        _save_qo_state(y, state, data_dir=resolved)
        return True
    return False


def compensation_for_draft(
    draft_year: int, *, data_dir: Path | str | None = None
) -> Dict[str, List[str]]:
    """Return ``{"comp_teams": [...], "forfeit_teams": [...]}`` for the amateur
    draft in ``draft_year`` — derived from the prior offseason's QO results
    (the offseason that ended ``draft_year - 1``)."""

    resolved = _resolve_dir(data_dir)
    comp: List[str] = []
    forfeit: List[str] = []
    for y in (int(draft_year) - 1, int(draft_year)):
        state = load_qo_state(y, data_dir=resolved)
        players = state.get("players")
        if not isinstance(players, dict):
            continue
        for rec in players.values():
            if not isinstance(rec, dict) or not rec.get("comp_awarded"):
                continue
            team = str(rec.get("team_id") or "").strip()
            signed = str(rec.get("signed_with") or "").strip()
            if team:
                comp.append(team)
            if signed and signed != team:
                forfeit.append(signed)
        if comp or forfeit:
            break
    return {"comp_teams": comp, "forfeit_teams": forfeit}


def apply_draft_compensation(
    order: List[str],
    draft_year: int,
    *,
    data_dir: Path | str | None = None,
) -> List[str]:
    """Reflect QO compensation in the draft ``order`` by nudging each team owed
    compensation to sit just ahead of the team that signed its free agent.

    Pure + safe: returns a list with the **same teams and length** (no extra or
    missing picks), so the draft pick engine is untouched. Returns ``order``
    unchanged on any problem.
    """

    try:
        result = list(order or [])
        if not result:
            return result
        comp = compensation_for_draft(int(draft_year), data_dir=data_dir)
        pairs = list(zip(comp.get("comp_teams", []), comp.get("forfeit_teams", [])))
        for comp_team, forfeit_team in pairs:
            if comp_team not in result or forfeit_team not in result:
                continue
            ci = result.index(comp_team)
            fi = result.index(forfeit_team)
            if ci <= fi:
                continue  # comp team already drafts ahead — nothing to do
            # Move the comp team to just before the forfeiting team.
            result.pop(ci)
            result.insert(result.index(forfeit_team), comp_team)
        return result
    except Exception:
        return list(order or [])


def qualifying_offer_summary(
    year: int, *, data_dir: Path | str | None = None
) -> Dict[str, int]:
    """Counts for the offseason finance to-do."""

    state = load_qo_state(int(year), data_dir=data_dir)
    players = state.get("players")
    if not isinstance(players, dict):
        return {"tendered": 0, "accepted": 0, "declined": 0, "comp_awarded": 0}
    def _count(decision: str) -> int:
        return sum(
            1 for r in players.values() if isinstance(r, dict) and r.get("decision") == decision
        )

    comp = sum(1 for r in players.values() if isinstance(r, dict) and r.get("comp_awarded"))
    return {
        "tendered": len(players),
        "accepted": _count("accepted"),
        "declined": _count("declined"),
        "pending": _count("pending"),
        "comp_awarded": comp,
    }
