import hashlib
import importlib
import json

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    return data_root


def test_import_and_apply_change_request(data_dir):
    import services.change_requests as change_requests
    importlib.reload(change_requests)

    content = "P1,ACT\nP2,AAA\n"
    request = change_requests.create_request(
        team_id="TST",
        owner_name="Owner",
        files=[{"path": "rosters/TST.csv", "content": content}],
        summary="Roster",
        status="exported",
    )

    inbox = change_requests.inbox_dir()
    export_path = change_requests.export_request(request, out_dir=inbox)
    assert export_path.exists()

    result = change_requests.import_requests_from_inbox()
    assert result.get("imported") == 1

    pending = change_requests.list_requests(status="pending")
    assert len(pending) == 1
    request_id = pending[0]["request_id"]

    approve = change_requests.approve_request(
        request_id,
        applied_by="Admin",
        auto_apply=True,
    )
    assert approve.get("status") == "applied"

    roster_path = data_dir / "rosters" / "TST.csv"
    assert roster_path.exists()
    assert roster_path.read_text(encoding="utf-8") == content

    audit_path = change_requests.audit_log_path()
    assert audit_path.exists()
    lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    actions = {entry.get("action") for entry in lines}
    assert "approved" in actions
    assert "applied" in actions

    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    hashes = [
        file_entry.get("sha256")
        for entry in lines
        for file_entry in entry.get("files", [])
        if file_entry.get("path") == "rosters/TST.csv"
    ]
    assert expected_hash in hashes
