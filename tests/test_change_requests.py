import hashlib
import importlib
import json
import re
import zipfile

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
    assert export_path.suffix == ".zip"
    assert re.match(
        r"^change_request_[a-z0-9-]+_[a-z0-9-]+_\d{8}-\d{4}(?:_\d+)?\.zip$",
        export_path.name,
    )
    with zipfile.ZipFile(export_path, "r") as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "request.json" in names
        assert "files/rosters/TST.csv" in names

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


def test_import_cancel_request_from_zip_bundle(data_dir):
    import services.change_requests as change_requests
    importlib.reload(change_requests)

    request = change_requests.create_request(
        team_id="TST",
        owner_name="Owner",
        files=[{"path": "rosters/TST.csv", "content": "P1,ACT\n"}],
        summary="Roster",
        status="exported",
    )
    change_requests.add_request(request)

    inbox = change_requests.inbox_dir()
    cancel_path = change_requests.export_cancel_request(
        request_id=request["request_id"],
        team_id="TST",
        owner_name="Owner",
        out_dir=inbox,
    )
    assert cancel_path.exists()
    assert cancel_path.suffix == ".zip"

    result = change_requests.import_requests_from_inbox()
    assert result.get("canceled") == 1
    assert result.get("failed") == 0

    requests = change_requests.list_requests(team_id="TST")
    assert requests
    assert requests[0].get("status") == "canceled"


def test_import_legacy_json_submit_payload_still_supported(data_dir):
    import services.change_requests as change_requests
    importlib.reload(change_requests)

    request = change_requests.create_request(
        team_id="TST",
        owner_name="Owner",
        files=[{"path": "rosters/TST.csv", "content": "P1,ACT\n"}],
        summary="Roster",
        status="exported",
    )
    payload = {
        "version": 1,
        "action": "submit",
        "exported_at": "2026-02-23T00:00:00Z",
        "request": request,
    }
    inbox = change_requests.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    legacy_path = inbox / "legacy_change_request.json"
    legacy_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = change_requests.import_requests_from_inbox()
    assert result.get("imported") == 1
    assert result.get("failed") == 0
