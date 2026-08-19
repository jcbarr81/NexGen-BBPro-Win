"""Team finance endpoints.

Reuses :func:`services.owner_finance_engine.get_team_finance_snapshot` and
:func:`services.owner_finance_engine.list_team_financial_transactions`, so
the Electron page renders the same numbers as the PyQt
``ui/owner_finance_page.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from services.owner_finance_engine import (
    get_team_finance_snapshot,
    list_team_financial_transactions,
)

from ..security import CurrentIdentity, require_bearer


def _current_qo_year() -> int:
    try:
        from services.trade_settings import current_league_year

        return int(current_league_year())
    except Exception:
        from datetime import date as _date

        return _date.today().year

router = APIRouter(
    prefix="/teams/{team_id}/finance",
    tags=["finance"],
    dependencies=[CurrentIdentity],
)


@router.get("/snapshot")
def team_finance_snapshot(team_id: str) -> Dict[str, Any]:
    try:
        snapshot = get_team_finance_snapshot(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute finance snapshot: {exc}",
        ) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No finance data for team {team_id}",
        )
    return snapshot.as_dict()


@router.put("/budgets")
def set_team_budgets(
    team_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Owner action (finance Phase 2): set this team's budget targets
    (training / scouting / development / facilities). Runs in the request's
    league context. Rejected (409) when finance is disabled or the league's
    ``owner_budgets`` module is off."""

    from services.owner_finance_engine import update_team_budget_targets

    budgets = payload.get("budgets")
    if not isinstance(budgets, dict):
        # Tolerate a flat {category: amount} body too.
        budgets = {k: v for k, v in payload.items() if k != "budgets"}
    try:
        result = update_team_budget_targets(team_id, budgets)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save budgets: {exc}",
        ) from exc
    if not result.get("saved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(result.get("message") or "Could not save budget targets."),
        )
    return result


@router.get("/payroll-context")
def team_payroll_context(team_id: str) -> Dict[str, Any]:
    """Payroll-vs-threshold outlook for the owner's headroom widget.

    Uses the same math settlement applies (thresholds, CBT tiers / overage
    fee, floor fee, Opening-Day debt-cap gate) so the numbers shown match
    the numbers charged.
    """
    from services.payroll_policy import build_team_payroll_outlook

    try:
        return build_team_payroll_outlook(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute payroll context: {exc}",
        ) from exc


@router.get("/todo")
def team_finance_todo(team_id: str) -> Dict[str, Any]:
    """Phase-aware list of finance actions the owner should take.

    Pull-based (computed on demand) so it's free to surface as a banner without
    adding per-sim-day cost. Returns an empty list when finance is disabled.
    """

    from utils.path_utils import get_data_dir

    data_dir = get_data_dir()

    # Current phase (best-effort).
    phase = "REGULAR_SEASON"
    try:
        from playbalance.season_manager import SeasonManager

        phase = SeasonManager().phase.value
    except Exception:
        pass

    try:
        snapshot = get_team_finance_snapshot(team_id)
    except Exception:
        snapshot = None

    enabled = bool(getattr(snapshot, "financials_enabled", False)) if snapshot else False
    items: List[Dict[str, Any]] = []
    if not enabled:
        return {
            "team_id": team_id,
            "phase": phase,
            "finance_enabled": False,
            "items": items,
        }

    cash = int(getattr(snapshot, "cash_on_hand", 0) or 0)
    net = int(getattr(snapshot, "projected_net", 0) or 0)

    def add(item_id: str, severity: str, label: str, to: str) -> None:
        items.append({"id": item_id, "severity": severity, "label": label, "to": to})

    # Universal health checks.
    if cash < 0:
        add(
            "cash_negative",
            "critical",
            f"Cash on hand is negative (-${abs(cash):,}). Your ledger is in the red.",
            "/finance",
        )
    if net < 0:
        add(
            "negative_net",
            "warning",
            f"Projected monthly net is -${abs(net):,}. Review your budgets.",
            "/finance",
        )

    # Over the luxury threshold (only reported when enforcement is on).
    try:
        from services.payroll_policy import evaluate_payroll_delta

        policy = evaluate_payroll_delta(team_id, annual_delta=0, data_dir=data_dir)
        violation = (policy.violations or {}).get(team_id)
        if violation and str(violation.get("kind")) == "max":
            over = int(violation.get("over", 0) or 0)
            if over > 0:
                add(
                    "over_threshold",
                    "info",
                    f"Payroll is ${over:,} over the luxury threshold — the tax applies.",
                    "/finance",
                )
    except Exception:
        pass

    # Phase-specific steps.
    if phase == "PRESEASON":
        try:
            from services.payroll_policy import evaluate_opening_day_payroll

            solvency = evaluate_opening_day_payroll(team_id, data_dir=data_dir)
            if not solvency.allowed:
                add(
                    "opening_day_insolvent",
                    "critical",
                    "Clear debt or shed payroll — your team isn't solvent for Opening Day.",
                    "/finance",
                )
        except Exception:
            pass
        add("review_budget", "info", "Review your team budget for the new season.", "/finance")
    elif phase == "OFFSEASON":
        try:
            from services.offseason_finance_flow import (
                collect_offseason_finance_overview,
            )

            ov = collect_offseason_finance_overview(data_dir=data_dir)
            if int(ov.get("contracts_expiring", 0) or 0):
                add(
                    "expiring",
                    "info",
                    f"{int(ov['contracts_expiring'])} contract(s) expiring this offseason.",
                    "/offseason",
                )
            if int(ov.get("arbitration_candidates", 0) or 0):
                add(
                    "arbitration",
                    "warning",
                    f"{int(ov['arbitration_candidates'])} arbitration case(s) to resolve.",
                    "/offseason",
                )
            if int(ov.get("unsigned_players", 0) or 0):
                add(
                    "free_agency",
                    "info",
                    f"Free agency is open — {int(ov['unsigned_players'])} unsigned player(s).",
                    "/offseason",
                )
            try:
                from services.qualifying_offers import qualifying_offer_summary

                qo = qualifying_offer_summary(
                    int(ov.get("next_season_year") or 0), data_dir=data_dir
                )
                if int(qo.get("tendered", 0) or 0):
                    comp = int(qo.get("comp_awarded", 0) or 0)
                    label = f"{qo['tendered']} qualifying offer(s) tendered"
                    if comp:
                        label += f"; {comp} compensation pick(s) pending"
                    add("qualifying_offers", "info", label + ".", "/offseason")
            except Exception:
                pass
        except Exception:
            pass

    return {
        "team_id": team_id,
        "phase": phase,
        "finance_enabled": True,
        "items": items,
    }


@router.get("/qualifying-offers")
def team_qualifying_offers(team_id: str) -> Dict[str, Any]:
    """List this team's qualifying-offer records (pending owner decisions +
    resolved) for the current league year."""

    from utils.path_utils import get_data_dir
    from services.qualifying_offers import list_team_qualifying_offers

    year = _current_qo_year()
    try:
        offers = list_team_qualifying_offers(team_id, year, data_dir=get_data_dir())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load qualifying offers: {exc}",
        ) from exc
    return {"team_id": team_id, "year": year, "offers": offers}


@router.post("/qualifying-offers/{player_id}")
def resolve_team_qualifying_offer(
    team_id: str,
    player_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Owner decision on a pending qualifying offer. ``{"tender": true}`` extends
    the one-year offer (the player then accepts/declines on value); ``false``
    lets him leave as a free agent with no compensation."""

    from utils.path_utils import get_data_dir
    from services.qualifying_offers import resolve_qualifying_offer

    tender = bool(payload.get("tender", True))
    result = resolve_qualifying_offer(
        team_id, player_id, _current_qo_year(), tender=tender, data_dir=get_data_dir()
    )
    if not result.get("applied"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(result.get("reason") or "Could not resolve qualifying offer."),
        )
    return result


@router.get("/transactions")
def team_finance_transactions(
    team_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    try:
        rows = list_team_financial_transactions(team_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load ledger: {exc}",
        ) from exc
    # Coerce each row's values to JSON-friendly primitives. The ledger may
    # contain Decimals / dates that the default serializer rejects.
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry: Dict[str, Any] = {}
        for key, value in row.items():
            if value is None or isinstance(value, (bool, int, float, str)):
                entry[str(key)] = value
            else:
                entry[str(key)] = str(value)
        cleaned.append(entry)
    return {"team_id": team_id, "count": len(cleaned), "transactions": cleaned}
