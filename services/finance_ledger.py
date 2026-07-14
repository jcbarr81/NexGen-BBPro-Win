"""Shared helpers for writing and querying the finance transaction ledger."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Mapping

from services.finance_settings import (
    FINANCIAL_TRANSACTIONS_FILENAME,
    FINANCIAL_TRANSACTIONS_HEADER,
)
from utils.path_utils import get_data_dir

__all__ = [
    "LEDGER_TEAM_SYSTEM",
    "CATEGORY_FINANCE_CYCLE",
    "CATEGORY_CONTRACT_BUYOUT",
    "CATEGORY_ARB_AWARD",
    "CATEGORY_PAYROLL_POLICY",
    "build_team_revenue_row",
    "build_team_expense_row",
    "post_team_revenue",
    "post_team_expense",
    "append_financial_rows",
    "list_financial_rows",
    "ledger_has_entry",
    "build_finance_cycle_marker_row",
    "post_finance_cycle_marker",
    "post_contract_buyout",
    "post_arb_award",
    "post_payroll_policy_event",
]

LEDGER_TEAM_SYSTEM = "__system__"
CATEGORY_FINANCE_CYCLE = "finance_cycle"
CATEGORY_CONTRACT_BUYOUT = "contract_buyout"
CATEGORY_ARB_AWARD = "arb_award"
CATEGORY_PAYROLL_POLICY = "payroll_policy"


def append_financial_rows(
    rows: Iterable[tuple[str, int, str, str, int, str] | Mapping[str, object]],
    *,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> int:
    """Append normalized rows to the league finance ledger."""

    ledger_path = _resolve_ledger_path(data_dir=data_dir, path=path)
    normalized_rows: list[tuple[str, int, str, str, int, str]] = []
    for raw in rows:
        clean = _normalize_row(raw)
        if clean is None:
            continue
        normalized_rows.append(clean)
    if not normalized_rows:
        return 0

    write_header = not ledger_path.exists() or ledger_path.stat().st_size == 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(FINANCIAL_TRANSACTIONS_HEADER)
        for row in normalized_rows:
            writer.writerow(row)
    return len(normalized_rows)


def list_financial_rows(
    *,
    team_id: str | None = None,
    category: str | None = None,
    memo: str | None = None,
    limit: int = 25,
    newest_first: bool = True,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> list[Dict[str, object]]:
    """List normalized finance ledger rows with optional filters."""

    ledger_path = _resolve_ledger_path(data_dir=data_dir, path=path)
    if not ledger_path.exists():
        return []

    clean_team_id = str(team_id or "").strip()
    clean_category = str(category or "").strip()
    clean_memo = str(memo or "").strip()

    # Fast path for the common "newest N rows" query: the ledger is
    # append-only (newest rows last) and can be ~18 MB, so parse only a tail
    # slice of raw lines instead of normalizing every row. Falls back to the
    # full scan below when the tail doesn't conclusively contain the answer.
    if newest_first and limit > 0:
        tail_rows = _tail_financial_rows(
            ledger_path,
            team_id=clean_team_id,
            category=clean_category,
            memo=clean_memo,
            limit=limit,
        )
        if tail_rows is not None:
            return tail_rows

    rows: list[Dict[str, object]] = []
    try:
        with ledger_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                row = _normalize_row(raw)
                if row is None:
                    continue
                row_payload = _row_tuple_to_dict(row)
                if clean_team_id and row_payload["team_id"] != clean_team_id:
                    continue
                if clean_category and row_payload["category"] != clean_category:
                    continue
                if clean_memo and row_payload["memo"] != clean_memo:
                    continue
                rows.append(row_payload)
    except Exception:
        return []

    if newest_first:
        rows = list(reversed(rows))
    if limit > 0:
        rows = rows[:limit]
    return rows


def _tail_financial_rows(
    ledger_path: Path,
    *,
    team_id: str,
    category: str,
    memo: str,
    limit: int,
) -> list[Dict[str, object]] | None:
    """Newest-first filtered rows parsed from a tail slice of the ledger.

    Reading raw lines is cheap next to csv-parsing + normalizing every row,
    so grab the last ~4x``limit`` data lines and parse just those. Returns
    ``None`` when the tail can't answer authoritatively (not enough matching
    rows in the slice, or quoted fields spanning physical lines) — the caller
    then does the original full scan. Filters (already-stripped) and output
    shape/ordering match the full-scan path exactly.
    """

    try:
        with ledger_path.open("r", newline="", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception:
        # The full scan would fail the same way; match its [] result.
        return []
    if len(lines) <= 1:
        # Header-only (or empty) file — DictReader consumes the first line as
        # the header, so there are no data rows either way.
        return []

    header_line, data_lines = lines[0], lines[1:]
    candidate_count = max(limit * 4, 100)
    tail_lines = data_lines[-candidate_count:]
    partial = len(tail_lines) < len(data_lines)
    if partial and any(line.count('"') % 2 for line in tail_lines):
        # An odd number of quotes on a physical line means a quoted field
        # spans lines; slicing by line isn't safe — full scan instead.
        return None

    try:
        fieldnames = next(csv.reader([header_line]), None)
        if not fieldnames:
            return []
        matched: list[Dict[str, object]] = []
        for values in csv.reader(tail_lines):
            # dict(zip(...)) mirrors DictReader: extra cells are ignored by
            # _normalize_row and missing cells read back as None.
            row = _normalize_row(dict(zip(fieldnames, values)))
            if row is None:
                continue
            row_payload = _row_tuple_to_dict(row)
            if team_id and row_payload["team_id"] != team_id:
                continue
            if category and row_payload["category"] != category:
                continue
            if memo and row_payload["memo"] != memo:
                continue
            matched.append(row_payload)
    except Exception:
        return None

    if partial and len(matched) < limit:
        # Older lines (outside the tail) may also match — need the full scan.
        return None
    matched.reverse()
    return matched[:limit]


def ledger_has_entry(
    *,
    team_id: str,
    category: str,
    memo: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Return ``True`` when a matching ledger entry exists."""

    clean_team_id = str(team_id or "").strip()
    clean_category = str(category or "").strip()
    clean_memo = str(memo or "").strip()
    if not clean_team_id or not clean_category:
        return False
    rows = list_financial_rows(
        team_id=clean_team_id,
        category=clean_category,
        memo=clean_memo if clean_memo else None,
        limit=1,
        newest_first=True,
        data_dir=data_dir,
        path=path,
    )
    return bool(rows)


def build_team_revenue_row(
    *,
    team_id: str,
    season_year: int,
    revenue_type: str,
    amount: int,
    memo: str | None = None,
    timestamp: str | None = None,
) -> tuple[str, int, str, str, int, str] | None:
    """Build a normalized team revenue ledger row."""

    clean_team = str(team_id or "").strip()
    clean_revenue = _normalize_category_key(revenue_type)
    clean_amount = max(0, _safe_int(amount))
    if not clean_team or not clean_revenue or clean_amount <= 0:
        return None
    return (
        str(timestamp or _timestamp()).strip(),
        _safe_int(season_year),
        clean_team,
        f"revenue_{clean_revenue}",
        clean_amount,
        str(memo or "").strip(),
    )


def build_team_expense_row(
    *,
    team_id: str,
    season_year: int,
    expense_type: str,
    amount: int,
    memo: str | None = None,
    timestamp: str | None = None,
) -> tuple[str, int, str, str, int, str] | None:
    """Build a normalized team expense ledger row."""

    clean_team = str(team_id or "").strip()
    clean_expense = _normalize_category_key(expense_type)
    clean_amount = max(0, _safe_int(amount))
    if not clean_team or not clean_expense or clean_amount <= 0:
        return None
    return (
        str(timestamp or _timestamp()).strip(),
        _safe_int(season_year),
        clean_team,
        f"expense_{clean_expense}",
        -clean_amount,
        str(memo or "").strip(),
    )


def post_team_revenue(
    *,
    team_id: str,
    season_year: int,
    revenue_type: str,
    amount: int,
    memo: str | None = None,
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write a canonical team revenue ledger row."""

    row = build_team_revenue_row(
        team_id=team_id,
        season_year=season_year,
        revenue_type=revenue_type,
        amount=amount,
        memo=memo,
        timestamp=timestamp,
    )
    if row is None:
        return False
    return (
        append_financial_rows([row], data_dir=data_dir, path=path)
        > 0
    )


def post_team_expense(
    *,
    team_id: str,
    season_year: int,
    expense_type: str,
    amount: int,
    memo: str | None = None,
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write a canonical team expense ledger row."""

    row = build_team_expense_row(
        team_id=team_id,
        season_year=season_year,
        expense_type=expense_type,
        amount=amount,
        memo=memo,
        timestamp=timestamp,
    )
    if row is None:
        return False
    return (
        append_financial_rows([row], data_dir=data_dir, path=path)
        > 0
    )


def build_finance_cycle_marker_row(
    *,
    season_year: int,
    period_key: str,
    timestamp: str | None = None,
) -> tuple[str, int, str, str, int, str] | None:
    """Build the canonical finance-cycle marker row."""

    clean_period = str(period_key or "").strip()
    if not clean_period:
        return None
    return (
        str(timestamp or _timestamp()).strip(),
        _safe_int(season_year),
        LEDGER_TEAM_SYSTEM,
        CATEGORY_FINANCE_CYCLE,
        0,
        clean_period,
    )


def post_finance_cycle_marker(
    *,
    season_year: int,
    period_key: str,
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write the canonical monthly finance-cycle marker row."""

    row = build_finance_cycle_marker_row(
        season_year=season_year,
        period_key=period_key,
        timestamp=timestamp,
    )
    if row is None:
        return False
    written = append_financial_rows(
        [row],
        data_dir=data_dir,
        path=path,
    )
    return written > 0


def post_contract_buyout(
    *,
    team_id: str,
    season_year: int,
    player_id: str,
    buyout_amount: int,
    detail: str = "",
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write a canonical contract buyout expense row."""

    clean_team = str(team_id or "").strip()
    clean_player = str(player_id or "").strip()
    clean_detail = str(detail or "").strip()
    amount = max(0, _safe_int(buyout_amount))
    if not clean_team or not clean_player or amount <= 0:
        return False
    memo_detail = clean_detail if clean_detail else "Contract buyout"
    written = append_financial_rows(
        [
            (
                str(timestamp or _timestamp()).strip(),
                _safe_int(season_year),
                clean_team,
                CATEGORY_CONTRACT_BUYOUT,
                -amount,
                f"{memo_detail}: {clean_player}",
            )
        ],
        data_dir=data_dir,
        path=path,
    )
    return written > 0


def post_arb_award(
    *,
    team_id: str,
    season_year: int,
    salary_delta: int,
    memo: str | None = None,
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write a canonical arbitration award expense row."""

    clean_team = str(team_id or "").strip()
    delta = max(0, _safe_int(salary_delta))
    if not clean_team or delta <= 0:
        return False
    clean_memo = str(memo or "").strip() or "Offseason arbitration awards"
    written = append_financial_rows(
        [
            (
                str(timestamp or _timestamp()).strip(),
                _safe_int(season_year),
                clean_team,
                CATEGORY_ARB_AWARD,
                -delta,
                clean_memo,
            )
        ],
        data_dir=data_dir,
        path=path,
    )
    return written > 0


def post_payroll_policy_event(
    *,
    team_id: str,
    season_year: int | None,
    action: str,
    outcome: str,
    kind: str,
    projected: int,
    threshold: int,
    delta: int = 0,
    over: int = 0,
    under: int = 0,
    estimated_tax: int = 0,
    timestamp: str | None = None,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Write a payroll-policy audit row for a team."""

    clean_team = str(team_id or "").strip()
    clean_action = _normalize_category_key(action)
    clean_outcome = _normalize_category_key(outcome)
    clean_kind = _normalize_category_key(kind)
    if not clean_team or not clean_action or not clean_outcome:
        return False
    year = _safe_int(season_year) or datetime.utcnow().year
    memo = (
        f"action={clean_action};outcome={clean_outcome};kind={clean_kind};"
        f"projected={_safe_int(projected)};threshold={_safe_int(threshold)};"
        f"delta={_safe_int(delta)};over={_safe_int(over)};under={_safe_int(under)};"
        f"estimated_tax={_safe_int(estimated_tax)}"
    )
    written = append_financial_rows(
        [
            (
                str(timestamp or _timestamp()).strip(),
                year,
                clean_team,
                CATEGORY_PAYROLL_POLICY,
                0,
                memo,
            )
        ],
        data_dir=data_dir,
        path=path,
    )
    return written > 0


def _resolve_ledger_path(
    *,
    data_dir: Path | str | None = None,
    path: Path | str | None = None,
) -> Path:
    if path is not None:
        return Path(path)
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    return resolved_data_dir / FINANCIAL_TRANSACTIONS_FILENAME


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _normalize_row(
    raw: tuple[str, int, str, str, int, str] | Mapping[str, object],
) -> tuple[str, int, str, str, int, str] | None:
    if isinstance(raw, tuple) and len(raw) == 6:
        timestamp, season_year, team_id, category, amount, memo = raw
        clean_row = (
            str(timestamp or "").strip(),
            _safe_int(season_year),
            str(team_id or "").strip(),
            str(category or "").strip(),
            _safe_int(amount),
            str(memo or "").strip(),
        )
    elif isinstance(raw, Mapping):
        clean_row = (
            str(raw.get("timestamp") or "").strip(),
            _safe_int(raw.get("season_year", 0)),
            str(raw.get("team_id") or "").strip(),
            str(raw.get("category") or "").strip(),
            _safe_int(raw.get("amount", 0)),
            str(raw.get("memo") or "").strip(),
        )
    else:
        return None
    if not clean_row[2] or not clean_row[3]:
        return None
    return clean_row


def _row_tuple_to_dict(row: tuple[str, int, str, str, int, str]) -> Dict[str, object]:
    return {
        "timestamp": row[0],
        "season_year": row[1],
        "team_id": row[2],
        "category": row[3],
        "amount": row[4],
        "memo": row[5],
    }


def _normalize_category_key(value: object) -> str:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized_chars = [
        ch for ch in token
        if ch.isalnum() or ch == "_"
    ]
    normalized = "".join(normalized_chars).strip("_")
    return normalized


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
