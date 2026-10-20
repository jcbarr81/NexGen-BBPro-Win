"""8.3.0: a player's picture follows him to a new club.

``utils.avatar_generator.recolor_avatar`` redoes one picture in a club's
colors (an image EDIT of an AI portrait -- same face -- or a template
re-render), and ``services.avatar_recolor`` queues players who changed clubs
and drains the queue in the background. Vertex is always mocked here: no test
reaches the real image API.
"""

from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from services import avatar_recolor  # noqa: E402
from utils import avatar_generator as ag  # noqa: E402
from utils import vertex_image  # noqa: E402

PLAYER_HEADER = (
    "player_id,first_name,last_name,primary_position,is_pitcher,"
    "ethnicity,hair_color,facial_hair\n"
)


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    # Sentinels so get_data_dir() resolves this root, never a real league.
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n"
        "AAA,Aces,Austin,AAA,East,Park A,#112233,#aabbcc,\n"
        "BBB,Bees,Boston,BBB,East,Park B,#C00000,#FFFFFF,\n",
        encoding="utf-8",
    )
    (root / "players.csv").write_text(
        PLAYER_HEADER
        + "a1,Al,Able,SS,0,Anglo,brown,clean\n"
        + "a2,Art,Ames,C,0,Hispanic,black,goatee\n"
        + "b1,Bo,Bell,CF,0,African,black,clean\n"
        + "b2,Ben,Bray,1B,0,Asian,black,clean\n"
        + "fa1,Fred,Free,LF,0,Anglo,blonde,clean\n"
        + "fa2,Finn,Fox,RF,0,Anglo,red,clean\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("", encoding="utf-8")
    rosters = root / "rosters"
    rosters.mkdir()
    (rosters / "AAA.csv").write_text("a1,ACT\na2,AAA\n", encoding="utf-8")
    (rosters / "BBB.csv").write_text("b1,ACT\nb2,LOW\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    monkeypatch.setenv("NEXGEN_AVATAR_RECOLOR_WORKER", "0")
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _avatars(root: Path) -> Path:
    path = root / "images" / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ai_portrait(root: Path, pid: str, rgb=(10, 20, 30)) -> Path:
    out = _avatars(root) / f"{pid}.png"
    ag._save_ai_png(Image.new("RGB", (512, 512), rgb), out)
    return out


def _png_bytes(size=1024, rgb=(200, 0, 0)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (size, size), rgb).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_vertex(monkeypatch):
    """Vertex 'available' with a recording edit_png that returns a 1024px PNG."""
    calls: list[dict] = []

    def _edit(image_png_bytes, prompt):
        calls.append({"image": image_png_bytes, "prompt": prompt})
        return _png_bytes()

    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "edit_png", _edit)
    return calls


def _pending(root: Path) -> list[str]:
    state = json.loads((root / avatar_recolor.QUEUE_FILE).read_text(encoding="utf-8"))
    return [e["player_id"] for e in state["pending"]]


# --- recolor_avatar --------------------------------------------------------


def test_ai_portrait_is_edited_and_records_its_colors(league, fake_vertex):
    original = _ai_portrait(league, "a1")
    before = original.read_bytes()

    result = ag.recolor_avatar("a1", "AAA", data_dir=league)

    assert result["status"] == "ai_edited"
    assert result["colors"] == "#112233|#AABBCC"
    assert len(fake_vertex) == 1
    assert fake_vertex[0]["image"] == before  # the existing portrait is edited
    prompt = fake_vertex[0]["prompt"]
    assert "Change ONLY the colors of his clothing" in prompt
    # Same color NAMES as the generation prompt, plus the hex.
    assert f"cap plain {ag._hex_to_color_name('#112233')} (#112233)" in prompt
    assert f"jersey plain {ag._hex_to_color_name('#AABBCC')} (#AABBCC)" in prompt
    with Image.open(original) as im:
        assert im.size == (512, 512)
    assert ag._avatar_is_ai(original)
    assert ag._recorded_colors(original) == "#112233|#AABBCC"
    prev = original.with_name("a1.prev.png")
    assert prev.read_bytes() == before
    assert not list(original.parent.glob("*.tmp"))


def test_picture_already_in_the_club_colors_is_skipped(league, fake_vertex):
    _ai_portrait(league, "a1")
    ag.recolor_avatar("a1", "AAA", data_dir=league)
    assert len(fake_vertex) == 1

    again = ag.recolor_avatar("a1", "AAA", data_dir=league)

    assert again["status"] == "unchanged"
    assert len(fake_vertex) == 1  # no second (paid) edit


def test_colors_come_fresh_from_teams_csv(league, fake_vertex):
    _ai_portrait(league, "a1")
    ag.recolor_avatar("a1", "AAA", data_dir=league)
    teams = (league / "teams.csv").read_text(encoding="utf-8")
    (league / "teams.csv").write_text(teams.replace("#112233", "#00FF00"), encoding="utf-8")

    result = ag.recolor_avatar("a1", "AAA", data_dir=league)

    assert result["status"] == "ai_edited"
    assert result["colors"] == "#00FF00|#AABBCC"


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("Vertex image error 500: boom"),
     RuntimeError("Vertex AI response contained no image (finishReason=SAFETY).")],
)
def test_failed_edit_keeps_the_original(league, monkeypatch, failure):
    original = _ai_portrait(league, "a1")
    before = original.read_bytes()

    def _edit(*_a, **_k):
        raise failure

    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "edit_png", _edit)

    result = ag.recolor_avatar("a1", "AAA", data_dir=league)

    assert result["status"] == "failed"
    assert str(failure) in result["error"]
    assert original.read_bytes() == before
    assert not original.with_name("a1.prev.png").exists()
    assert not list(original.parent.glob("*.tmp"))


def test_ai_portrait_is_left_alone_without_vertex(league, monkeypatch):
    original = _ai_portrait(league, "a1")
    before = original.read_bytes()
    monkeypatch.setattr(vertex_image, "is_available", lambda: False)

    def _never(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("no edit without Vertex")

    monkeypatch.setattr(vertex_image, "edit_png", _never)

    result = ag.recolor_avatar("a1", "AAA", data_dir=league)

    assert result["status"] == "no_vertex"
    assert original.read_bytes() == before  # never replaced by a template


def test_template_picture_is_rerendered_in_the_new_colors(league, monkeypatch):
    pytest.importorskip("cv2")
    out = _avatars(league) / "b1.png"
    Image.new("RGB", (512, 512), (1, 2, 3)).save(out, format="PNG")  # a template
    before = out.read_bytes()

    def _never(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("templates are never sent to Vertex")

    monkeypatch.setattr(vertex_image, "edit_png", _never)

    result = ag.recolor_avatar("b1", "BBB", data_dir=league)

    assert result["status"] == "template"
    assert ag._recorded_colors(out) == "#C00000|#FFFFFF"
    assert not ag._avatar_is_ai(out)
    assert out.with_name("b1.prev.png").read_bytes() == before


def test_player_without_a_picture_gets_a_template(league):
    pytest.importorskip("cv2")

    result = ag.recolor_avatar("fa1", "AAA", data_dir=league)

    assert result["status"] == "template"
    out = _avatars(league) / "fa1.png"
    assert ag._recorded_colors(out) == "#112233|#AABBCC"
    assert not out.with_name("fa1.prev.png").exists()


def test_template_engine_records_colors_for_new_pictures(league):
    pytest.importorskip("cv2")
    path = ag.generate_one_template_avatar(
        "b2",
        ethnicity="Asian",
        hair_color="black",
        facial_hair="clean",
        primary_color="#c00000",
        secondary_color="#fff",
        out_dir=str(_avatars(league)),
    )
    assert path is not None
    assert ag._recorded_colors(Path(path)) == "#C00000|#FFFFFF"


# --- vertex_image.edit_png ---------------------------------------------------


def test_edit_png_sends_the_picture_and_the_prompt(monkeypatch):
    sent: dict = {}
    raw = _png_bytes(8)

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "candidates": [{"content": {"parts": [
                    {"inlineData": {"mimeType": "image/png",
                                    "data": base64.b64encode(raw).decode()}}]}}],
                "usageMetadata": {"promptTokenCount": 1300, "candidatesTokenCount": 1290},
            }

    def _post(url, headers, json, timeout):
        sent.update(url=url, body=json)
        return _Resp()

    import httpx

    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "_access_token", lambda: ("tok", "proj"))
    monkeypatch.setattr(vertex_image, "_throttle", lambda: None)
    monkeypatch.setattr(vertex_image, "_MODEL", "gemini-2.5-flash-image")
    monkeypatch.setattr(httpx, "post", _post)

    assert vertex_image.edit_png(b"PNGDATA", "recolor him") == raw
    assert sent["url"].endswith("gemini-2.5-flash-image:generateContent")
    parts = sent["body"]["contents"][0]["parts"]
    assert parts[0]["inlineData"] == {
        "mimeType": "image/png", "data": base64.b64encode(b"PNGDATA").decode(),
    }
    assert parts[1] == {"text": "recolor him"}
    assert sent["body"]["generationConfig"] == {"responseModalities": ["IMAGE"]}


def test_edit_png_refuses_an_imagen_model(monkeypatch):
    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "_MODEL", "imagen-3.0-generate-002")
    with pytest.raises(RuntimeError):
        vertex_image.edit_png(b"x", "y")


# --- the queue ---------------------------------------------------------------


def test_queue_dedupes_and_survives_a_reload(league):
    assert avatar_recolor.enqueue(["a1", "b1"], "trade", data_dir=league) == 2
    assert avatar_recolor.enqueue(["a1", "fa1", "fa1"], "signing", data_dir=league) == 1

    assert _pending(league) == ["a1", "b1", "fa1"]
    # A fresh read (a new process) sees the same queue.
    import importlib

    reloaded = importlib.reload(avatar_recolor)
    assert reloaded.status(data_dir=league)["pending"] == 3


def test_entry_left_mid_edit_by_a_dead_instance_runs_first(league, fake_vertex):
    _ai_portrait(league, "a1")
    _ai_portrait(league, "b1")
    (league / avatar_recolor.QUEUE_FILE).write_text(json.dumps({
        "pending": [{"player_id": "b1", "reason": "trade", "attempts": 0}],
        "active": {"player_id": "a1", "reason": "trade", "attempts": 0},
    }), encoding="utf-8")

    counts = avatar_recolor.drain(data_dir=league)

    assert counts == {"ai_edited": 2}
    order = [r["player_id"] for r in avatar_recolor.status(data_dir=league)["recent"]]
    assert order == ["a1", "b1"]
    status = avatar_recolor.status(data_dir=league)
    assert status["pending"] == 0
    assert status["done"] == 2
    assert status["ai_edits"] == 2


def test_target_club_is_the_one_listing_him_when_processed(league, fake_vertex):
    _ai_portrait(league, "a1")
    avatar_recolor.enqueue(["a1"], "trade", data_dir=league)
    # He moved on again before the worker reached him.
    (league / "rosters" / "AAA.csv").write_text("a2,AAA\n", encoding="utf-8")
    (league / "rosters" / "BBB.csv").write_text("b1,ACT\nb2,LOW\na1,ACT\n", encoding="utf-8")

    avatar_recolor.drain(data_dir=league)

    assert ag._recorded_colors(_avatars(league) / "a1.png") == "#C00000|#FFFFFF"


def test_free_agent_is_dropped(league, fake_vertex):
    original = _ai_portrait(league, "fa1")
    before = original.read_bytes()
    avatar_recolor.enqueue(["fa1"], "commissioner", data_dir=league)

    counts = avatar_recolor.drain(data_dir=league)

    assert counts == {"free_agent": 1}
    assert fake_vertex == []
    assert original.read_bytes() == before  # keeps his last club's look
    status = avatar_recolor.status(data_dir=league)
    assert (status["pending"], status["skipped"], status["done"]) == (0, 1, 0)


def test_failure_is_retried_then_counted(league, monkeypatch):
    _ai_portrait(league, "a1")
    tries: list[int] = []

    def _edit(*_a, **_k):
        tries.append(1)
        raise RuntimeError("Vertex image error 503")

    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "edit_png", _edit)
    avatar_recolor.enqueue(["a1"], "trade", data_dir=league)

    avatar_recolor.drain(data_dir=league)

    assert len(tries) == avatar_recolor.MAX_ATTEMPTS
    status = avatar_recolor.status(data_dir=league)
    assert (status["pending"], status["failed"], status["ai_edits"]) == (0, 1, 0)


def test_enqueue_never_raises(league, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(avatar_recolor, "_write", _boom)
    assert avatar_recolor.enqueue(["a1"], "trade", data_dir=league) == 0


def test_drain_marks_a_background_writer_and_pushes(league, monkeypatch):
    from api import working_copy

    _ai_portrait(league, "a1")
    busy_during_edit: list[dict] = []

    def _edit(*_a, **_k):
        busy_during_edit.append(dict(working_copy._busy))
        return _png_bytes()

    pushes: list = []
    monkeypatch.setattr(vertex_image, "is_available", lambda: True)
    monkeypatch.setattr(vertex_image, "edit_png", _edit)
    monkeypatch.setattr(working_copy, "is_enabled", lambda: True)
    monkeypatch.setattr(working_copy, "push_changes", lambda lid=None, **_k: pushes.append(lid))
    avatar_recolor.enqueue(["a1"], "trade", data_dir=league)

    avatar_recolor.drain(data_dir=league, league_id="lg1")

    assert busy_during_edit == [{"avatar-recolor": 1}]
    assert "avatar-recolor" not in working_copy._busy  # released between pictures
    assert pushes and set(pushes) == {"lg1"}


def _wait_idle(root: Path, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = avatar_recolor.status(data_dir=root)
        if status["pending"] == 0 and not status["worker_running"]:
            return status
        time.sleep(0.05)
    raise AssertionError("recolor worker did not finish")


def test_enqueue_starts_the_background_worker(league, fake_vertex, monkeypatch):
    monkeypatch.setenv("NEXGEN_AVATAR_RECOLOR_WORKER", "1")
    _ai_portrait(league, "a1")
    _ai_portrait(league, "b1")

    avatar_recolor.enqueue(["a1", "b1"], "trade")

    status = _wait_idle(league)
    assert status["done"] == 2 and status["ai_edits"] == 2
    assert ag._recorded_colors(_avatars(league) / "b1.png") == "#C00000|#FFFFFF"


def test_resume_picks_up_a_queue_left_by_a_restart(league, fake_vertex, monkeypatch):
    _ai_portrait(league, "a1")
    avatar_recolor.enqueue(["a1"], "trade", start=False)
    assert avatar_recolor.resume() is False  # worker off: nothing starts

    monkeypatch.setenv("NEXGEN_AVATAR_RECOLOR_WORKER", "1")
    assert avatar_recolor.resume() is True

    assert _wait_idle(league)["done"] == 1
    assert avatar_recolor.resume() is False  # empty queue: no worker


def test_scheduler_tick_resumes_each_league(monkeypatch):
    from api.routers import season

    asked: list = []
    monkeypatch.setattr(season, "_iter_league_ids", lambda: ["lg1", "lg2"])
    monkeypatch.setattr(
        avatar_recolor, "resume", lambda lid=None: asked.append(lid) or lid == "lg2"
    )

    assert season._tick_avatar_recolor() == ["lg2"]
    assert asked == ["lg1", "lg2"]


# --- triggers -----------------------------------------------------------------


def test_trade_queues_both_directions(league, monkeypatch):
    from models.trade import Trade
    from services.trade_execution import commit_trade

    monkeypatch.setattr("services.trade_execution.record_transaction", lambda **_k: None)

    commit_trade(Trade("t1", "AAA", "BBB", ["a1"], ["b1"]), data_dir=league)

    assert sorted(_pending(league)) == ["a1", "b1"]


def test_negotiated_signing_queues_the_player(league):
    from services.free_agency import finalize_fa_signing

    assert finalize_fa_signing("BBB", "fa1", data_dir=league, cpu_placement=False)

    assert _pending(league) == ["fa1"]


def test_cpu_market_signing_queues_the_player(league):
    from services.free_agency import _add_player_to_team_roster

    assert _add_player_to_team_roster("AAA", "fa2", data_dir=league) is not None

    assert _pending(league) == ["fa2"]


def test_signing_endpoint_queues_the_player(league):
    from api.routers.free_agency import sign_free_agent

    out = sign_free_agent(
        "AAA",
        payload={"player_id": "fa1", "level": "AAA", "force": True},
        identity={"r": "admin", "t": ""},
    )

    assert out["signed"] is True
    assert _pending(league) == ["fa1"]


def test_cpu_roster_fill_queues_signed_free_agents(league, monkeypatch):
    from utils.roster_backfill import ensure_active_rosters

    players = {
        "a1": SimpleNamespace(player_id="a1", primary_position="SS", is_pitcher=False),
        "fa1": SimpleNamespace(player_id="fa1", primary_position="LF", is_pitcher=False),
    }
    monkeypatch.setattr(
        "utils.roster_backfill.load_teams",
        lambda *a, **k: [SimpleNamespace(team_id="AAA")],
    )
    (league / "rosters" / "AAA.csv").write_text("a1,ACT\n", encoding="utf-8")

    ensure_active_rosters(
        players=players, roster_dir=league / "rosters", min_hitters=2, active_max=2,
    )

    assert "fa1" in (league / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    assert _pending(league) == ["fa1"]


def test_club_color_change_queues_the_whole_roster(league):
    from api.routers.team_settings import save_settings

    save_settings("BBB", payload={"stadium": "Park B"}, identity={"r": "admin"})
    assert not (league / avatar_recolor.QUEUE_FILE).exists()  # same colors

    save_settings("BBB", payload={"primary_color": "#00ff00"}, identity={"r": "admin"})

    assert sorted(_pending(league)) == ["b1", "b2"]


def test_same_club_level_move_does_not_queue(league, monkeypatch):
    from api.routers import roster
    from api.routers.roster import move_roster

    # The response's roster payload needs full player rows; not under test.
    monkeypatch.setattr(roster, "team_roster", lambda team_id: {})

    move_roster("AAA", payload={"player_id": "a1", "to": "AAA"}, identity={"r": "admin"})

    assert "a1,AAA" in (league / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    assert not (league / avatar_recolor.QUEUE_FILE).exists()


# --- endpoints ----------------------------------------------------------------


def _client(identity: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers import admin, players
    from api.security import require_bearer

    app = FastAPI()
    app.include_router(players.router)
    app.include_router(admin.router)
    app.dependency_overrides[require_bearer] = lambda: identity
    return TestClient(app)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/players/a1/avatar/recolor", None),
        ("post", "/admin/avatars/recolor", {"player_ids": ["a1"]}),
        ("get", "/admin/avatars/recolor", None),
    ],
)
def test_recolor_endpoints_are_admin_only(league, method, path, body):
    client = _client({"r": "owner", "t": "AAA"})
    resp = getattr(client, method)(path, **({"json": body} if body else {}))
    assert resp.status_code == 403
    assert not (league / avatar_recolor.QUEUE_FILE).exists()


def test_commissioner_refreshes_one_picture(league, fake_vertex):
    _ai_portrait(league, "a1")
    client = _client({"r": "admin", "t": ""})

    first = client.post("/players/a1/avatar/recolor")
    second = client.post("/players/a1/avatar/recolor")

    assert first.status_code == 200 and first.json()["changed"] is True
    assert first.json()["status"] == "ai_edited"
    assert second.json()["status"] == "unchanged"
    assert len(fake_vertex) == 1
    status = client.get("/admin/avatars/recolor").json()
    assert status["ai_edits"] == 1 and status["done"] == 1 and status["skipped"] == 1


def test_commissioner_queues_a_catch_up_batch(league):
    client = _client({"r": "admin", "t": ""})

    resp = client.post("/admin/avatars/recolor", json={"player_ids": ["a1", "b1", "a1"]})

    assert resp.status_code == 200
    assert resp.json()["queued"] == 2
    assert resp.json()["pending"] == 2
    assert client.post("/admin/avatars/recolor", json={"player_ids": []}).status_code == 422
