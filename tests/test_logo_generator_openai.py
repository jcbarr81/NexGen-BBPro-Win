import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
pytest.importorskip("PIL")
from PIL import Image

from images import auto_logo
from models.team import Team
from utils import logo_generator


def _fake_b64_png(size: int) -> str:
    img = Image.new("RGBA", (size, size))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_generates_logo_and_calls_callback(tmp_path, monkeypatch):
    team = Team(
        team_id="TST",
        name="Testers",
        city="Testville",
        abbreviation="TST",
        division="Test",
        stadium="Test Field",
        primary_color="#112233",
        secondary_color="#445566",
        owner_id="0",
    )

    # Patch load_teams to return our single team
    monkeypatch.setattr(logo_generator, "load_teams", lambda _: [team])

    calls = {}
    logo_size = 256
    api_size = 1024

    class DummyImages:
        def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=_fake_b64_png(api_size))])

    monkeypatch.setattr(logo_generator, "client", SimpleNamespace(images=DummyImages()))

    progress = []

    def cb(done, total):
        progress.append((done, total))

    statuses = []

    out_dir = tmp_path
    logo_generator.generate_team_logos(
        out_dir=str(out_dir),
        size=logo_size,
        progress_callback=cb,
        status_callback=statuses.append,
    )

    assert calls["size"] == "1024x1024"
    # Prompt is now a MASCOT-forward emblem prompt: it references the team name
    # and a color scheme, deliberately OMITS the city, and uses descriptive
    # color names instead of hex codes (image models render names better).
    assert "Testers" in calls["prompt"]
    assert "MASCOT" in calls["prompt"]
    assert "Color scheme:" in calls["prompt"]
    assert "mascot artwork only" in calls["prompt"]
    assert "Testville" not in calls["prompt"]
    assert "#112233" not in calls["prompt"]

    outfile = out_dir / "tst.png"
    assert outfile.exists()
    with Image.open(outfile) as img:
        assert img.size == (logo_size, logo_size)
    assert progress == [(0, 1), (1, 1)]
    assert statuses == ["openai"]


def test_generate_team_logos_uses_prompt_builder(tmp_path, monkeypatch):
    team = Team(
        team_id="TST",
        name="Testers",
        city="Testville",
        abbreviation="TST",
        division="Test",
        stadium="Test Field",
        primary_color="#112233",
        secondary_color="#445566",
        owner_id="0",
    )
    monkeypatch.setattr(logo_generator, "load_teams", lambda _: [team])

    calls = {}

    class DummyImages:
        def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=_fake_b64_png(1024))])

    monkeypatch.setattr(logo_generator, "client", SimpleNamespace(images=DummyImages()))

    out_dir = tmp_path
    logo_generator.generate_team_logos(
        out_dir=str(out_dir),
        prompt_builder=lambda t: f"CUSTOM PROMPT FOR {t.team_id}",
    )

    assert calls["prompt"] == "CUSTOM PROMPT FOR TST"
    assert (out_dir / "tst.png").exists()


def test_existing_logos_are_removed(tmp_path, monkeypatch):
    team = Team(
        team_id="TST",
        name="Testers",
        city="Testville",
        abbreviation="TST",
        division="Test",
        stadium="Test Field",
        primary_color="#112233",
        secondary_color="#445566",
        owner_id="0",
    )

    monkeypatch.setattr(logo_generator, "load_teams", lambda _: [team])

    class DummyImages:
        def generate(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(b64_json=_fake_b64_png(1024))])

    monkeypatch.setattr(logo_generator, "client", SimpleNamespace(images=DummyImages()))

    stale = tmp_path / "old.png"
    stale.write_text("old")

    logo_generator.generate_team_logos(out_dir=str(tmp_path))

    assert not stale.exists()
    assert (tmp_path / "tst.png").exists()


def test_auto_logo_fallback_without_client(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_generator, "client", None)
    monkeypatch.setattr(logo_generator, "load_teams", lambda _: [])

    called = {}

    def fake_fallback(teams, out_dir, size, progress_callback):
        called["args"] = (teams, out_dir, size, progress_callback)

    monkeypatch.setattr(logo_generator, "_auto_logo_fallback", fake_fallback)

    statuses = []
    logo_generator.generate_team_logos(out_dir=str(tmp_path), status_callback=statuses.append)
    assert "args" in called
    assert statuses == ["auto_logo"]


def test_auto_logo_fallback_uses_location_and_mascot_seed(tmp_path, monkeypatch):
    team = Team(
        team_id="TST",
        name="Testers",
        city="Testville",
        abbreviation="TST",
        division="Test",
        stadium="Test Field",
        primary_color="#112233",
        secondary_color="#445566",
        owner_id="0",
    )

    monkeypatch.setattr(logo_generator, "client", None)
    captured = {}

    def fake_generate_logo(spec, size=1024):
        captured["spec"] = spec
        return Image.new("RGBA", (size, size))

    def fake_save_logo(img, path):
        captured["path"] = path

    monkeypatch.setattr(auto_logo, "generate_logo", fake_generate_logo)
    monkeypatch.setattr(auto_logo, "save_logo", fake_save_logo)

    logo_generator._auto_logo_fallback(
        teams=[team],
        out_dir=str(tmp_path),
        size=256,
        progress_callback=None,
    )

    spec = captured["spec"]
    assert spec.location == team.city
    assert spec.mascot == team.name
    assert spec.abbrev == team.team_id
    assert spec.seed == auto_logo._seed_from_name(team.city, team.name)
    assert "tst" in captured["path"].lower()


def test_raises_without_client_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_generator, "client", None)
    monkeypatch.setattr(logo_generator, "load_teams", lambda _: [])
    with pytest.raises(RuntimeError):
        logo_generator.generate_team_logos(out_dir=str(tmp_path), allow_auto_logo=False)
