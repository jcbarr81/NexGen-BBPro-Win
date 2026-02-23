from __future__ import annotations

from datetime import datetime

from services.transaction_log import clear_transactions, load_transactions, record_transaction
from services.unified_data_service import get_unified_data_service


def test_transaction_log_updates_cache(tmp_path):
    path = tmp_path / "transactions.csv"
    service = get_unified_data_service()
    service.invalidate_document(path, topic="transactions")

    record_transaction(
        action="draft",
        team_id="AAA",
        player_id="p001",
        player_name="Test Prospect",
        season_date="2025-07-01",
        timestamp=datetime(2025, 7, 1, 12, 0, 0),
        path=path,
    )

    first = load_transactions(path=path)
    assert len(first) == 1

    record_transaction(
        action="promote",
        team_id="AAA",
        player_id="p002",
        player_name="Second Prospect",
        season_date="2025-07-02",
        timestamp=datetime(2025, 7, 2, 9, 30, 0),
        path=path,
    )

    second = load_transactions(path=path)
    assert len(second) == 2
    assert second[0]["action"] == "promote"
    assert second[1]["action"] == "draft"

    # Ensure callers receive copies and do not mutate the cache.
    second.pop()
    third = load_transactions(path=path)
    assert len(third) == 2


def test_clear_transactions_resets_file_and_cache(tmp_path):
    path = tmp_path / "transactions.csv"
    service = get_unified_data_service()
    service.invalidate_document(path, topic="transactions")

    record_transaction(
        action="draft",
        team_id="AAA",
        player_id="p001",
        player_name="Test Prospect",
        season_date="2025-07-01",
        timestamp=datetime(2025, 7, 1, 12, 0, 0),
        path=path,
    )
    assert len(load_transactions(path=path)) == 1

    observed = []
    unsubscribe = service.events.subscribe(
        "transactions.updated",
        lambda payload: observed.append(payload.get("path")),
    )
    try:
        clear_transactions(path=path)
    finally:
        unsubscribe()

    assert load_transactions(path=path) == []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert observed
