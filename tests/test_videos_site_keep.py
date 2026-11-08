"""scripts/videos_site.py --keep: a hosting deploy must not lose /videos/.

``firebase deploy --only hosting`` releases desktop/dist alone. The postdeploy
hook in firebase.json runs ``--keep``, which copies the /videos/ files of the
newest earlier release into a copy of the new one, by hash, uploading nothing.
These tests stand in for Firebase's REST API; nothing leaves the machine.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("videos_site", ROOT / "scripts" / "videos_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def site(monkeypatch):
    vs = _load()
    versions = {
        "v3": {"/index.html": "h-index3", "/assets/a.js": "h-a3"},           # the CLI deploy, no videos
        "v2": {"/index.html": "h-index2", "/videos/trades.mp4": "h-trades",
               "/videos/index.html": "h-vindex"},
        "v1": {"/index.html": "h-index1", "/videos/old.mp4": "h-old"},
    }
    calls = []

    def call(method, url, body=None):
        calls.append((method, url, body))
        if "/releases?pageSize=" in url:
            return 200, {"releases": [{"version": {"name": f"sites/s/versions/{v}", "fileCount": 3}}
                                      for v in ("v3", "v2", "v1")]}
        if url.endswith(":clone"):
            return 200, {"done": True, "response": {"name": "sites/s/versions/new"}}
        if ":populateFiles" in url:
            return 200, {"uploadRequiredHashes": [], "uploadUrl": "https://upload"}
        if "update_mask=status" in url:
            return 200, {"status": "FINALIZED"}
        if "/releases?versionName=" in url:
            return 200, {"releaseTime": "now"}
        for v, files in versions.items():
            if f"/versions/{v}/files" in url:
                return 200, {"files": [{"path": p, "hash": h} for p, h in files.items()]}
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr(vs, "call", call)
    monkeypatch.setattr(vs, "token", lambda: "t")
    monkeypatch.setattr(vs, "upload", lambda *a: (_ for _ in ()).throw(AssertionError("no upload")))
    return vs, calls, versions


def test_keep_carries_the_newest_earlier_videos_by_hash(site):
    vs, calls, _ = site
    assert vs.keep() == 0
    populate = [b for m, u, b in calls if ":populateFiles" in u]
    assert populate == [{"files": {"/videos/trades.mp4": "h-trades", "/videos/index.html": "h-vindex"}}]
    assert any("/releases?versionName=sites/s/versions/new" in u for _, u, _ in calls)


def test_keep_does_nothing_when_the_release_already_has_videos(site):
    vs, calls, versions = site
    versions["v3"]["/videos/trades.mp4"] = "h-trades"
    assert vs.keep() == 0
    assert not any(u.endswith(":clone") for _, u, _ in calls)


def test_keep_refuses_when_firebase_lost_the_bytes(site, monkeypatch):
    vs, calls, _ = site
    real = vs.call

    def call(method, url, body=None):
        if ":populateFiles" in url:
            return 200, {"uploadRequiredHashes": ["h-trades"], "uploadUrl": "https://upload"}
        return real(method, url, body)

    monkeypatch.setattr(vs, "call", call)
    with pytest.raises(SystemExit) as err:
        vs.keep()
    assert "upload them with DIR --go" in str(err.value)
    assert not any("/releases?versionName=" in u for _, u, _ in calls)


def test_firebase_json_runs_keep_after_every_hosting_deploy():
    config = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
    assert config["hosting"]["postdeploy"] == "python scripts/videos_site.py --keep"
