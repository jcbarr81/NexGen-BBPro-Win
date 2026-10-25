"""Contract-extension talks (8.5.0, ``services.extension_talks``).

The player asks above what he'll take; an offer at or above his hidden
minimum is accepted; below it he counters and loses patience (a lowball
costs double and does not move him); out of patience he breaks off talks
for 7-30 days, counted in sim days in season and in free-agency window days
(7:1) in the window. Walk-year veterans may refuse in-season talks; a crazy
offer (1.5x his fair price) is accepted whatever else is going on.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import services.extension_talks as et

FAIR = 10_000_000


@pytest.fixture
def talks(tmp_path, monkeypatch):
    clock = {"now": ("sim", "2027-05-01")}
    monkeypatch.setattr(et, "fair_price", lambda *a, **k: FAIR)
    monkeypatch.setattr(et, "season_key", lambda base: "lg-2027")
    monkeypatch.setattr(et, "talks_clock", lambda base: clock["now"])
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 4)
    monkeypatch.setattr("services.contract_negotiator._age_of", lambda p: 29)
    news = []
    monkeypatch.setattr(et, "_tell_owner", lambda base, team, pid, name, msg: news.append(msg))
    return SimpleNamespace(dir=tmp_path, clock=clock, news=news)


def _pid(kind):
    """A player id with the given temperament."""
    return next(f"P{i}" for i in range(10_000) if et.temperament(f"P{i}") == kind)


PLAYER = SimpleNamespace(first_name="Pat", last_name="Smith")


def offer(t, pid, salary, *, years=3, phase="REGULAR_SEASON", years_left=2,
          service=3 * 172, team="BAL"):
    return et.respond_to_offer(
        PLAYER, pid, team_id=team, years=years, salary=salary,
        service_time_days=service, current_annual_salary=5_000_000,
        current_years_left=years_left, phase=phase, data_dir=t.dir,
    )


def view(t, pid, *, years=3, team="BAL"):
    return et.talks_view(PLAYER, pid, team_id=team, years=years,
                         service_time_days=3 * 172, current_annual_salary=5_000_000,
                         current_years_left=2, data_dir=t.dir)


def test_temperament_is_fixed_and_mixed():
    assert et.temperament("P42") == et.temperament("P42")
    kinds = {et.temperament(f"P{i}") for i in range(200)}
    assert kinds == {"easy", "normal", "hard"}


def test_ask_is_above_what_he_takes(talks):
    pid = _pid("normal")
    v = view(talks, pid)
    # 1.15 x fair, varied by up to 4% either way per player.
    assert 11_100_000 <= v["ask_salary"] <= 11_900_000
    assert v["mood"] == "open" and v["status"] == "open"
    # Nothing in the preview names his temperament (with the ask it would
    # give his minimum away).
    assert "temperament" not in v
    # An offer between his minimum (0.96 x fair) and his ask is accepted.
    r = offer(talks, pid, 9_700_000)
    assert r.decision == "accepted"
    # Accepted talks are cleared.
    assert pid not in json.loads((talks.dir / et.FILENAME).read_text())


def test_preview_decides_nothing(talks):
    pid = _pid("normal")
    view(talks, pid)
    assert not (talks.dir / et.FILENAME).exists()


def test_counter_moves_his_ask_and_costs_patience(talks):
    pid = _pid("normal")
    before = view(talks, pid)["ask_salary"]
    r = offer(talks, pid, 9_000_000)  # below 9.6M minimum, not a lowball
    assert r.decision == "countered"
    # About 40% (28-52%) of the way down to his 9.6M minimum.
    moved = (before - r.ask_salary) / (before - 9_600_000)
    assert 0.2 < moved < 0.6
    assert view(talks, pid)["mood"] == "open"  # 3 of 4 patience left
    offer(talks, pid, 9_000_000)
    assert view(talks, pid)["mood"] == "impatient"


def test_lowball_costs_double_and_does_not_move_him(talks):
    pid = _pid("normal")
    before = view(talks, pid)["ask_salary"]
    r = offer(talks, pid, 5_000_000)  # under 0.8 x 9.6M
    assert r.decision == "countered"
    assert r.ask_salary == before
    assert "insulted" in r.reason
    assert view(talks, pid)["mood"] == "impatient"  # 2 of 4 left


def test_out_of_patience_he_breaks_off_talks(talks):
    pid = _pid("normal")
    offer(talks, pid, 5_000_000)
    r = offer(talks, pid, 5_000_000)
    assert r.decision == "shutdown"
    assert 7 <= r.shutdown_days <= 30 and r.shutdown_unit == "days"
    assert talks.news and "broke off" in talks.news[0]
    # While shut down, a normal offer is not even heard...
    talks.clock["now"] = ("sim", "2027-05-03")
    assert offer(talks, pid, 11_000_000).decision == "blocked"
    assert view(talks, pid)["status"] == "shutdown"
    # ...but a crazy one is.
    assert offer(talks, pid, 15_000_000).decision == "accepted"


def test_talks_reopen_after_the_shutdown(talks):
    pid = _pid("normal")
    offer(talks, pid, 5_000_000)
    days = offer(talks, pid, 5_000_000).shutdown_days
    talks.clock["now"] = ("sim", f"2027-05-{1 + days:02d}")
    r = offer(talks, pid, 9_000_000)
    assert r.decision == "countered"
    assert view(talks, pid)["mood"] == "open"  # patience restored, one spent


def test_shutdown_in_the_window_counts_window_days(talks):
    pid = _pid("hard")  # patience 3, base 14 days
    talks.clock["now"] = ("fa", "3")
    offer(talks, pid, 5_000_000)
    r = offer(talks, pid, 5_000_000)
    assert r.decision == "shutdown" and r.shutdown_unit == "free-agency days"
    assert r.shutdown_days == -(-min(30, 14 + 8 + 10) // 7)  # ceil(days / 7)
    talks.clock["now"] = ("fa", "4")
    assert offer(talks, pid, 11_000_000).decision == "blocked"
    # The window closing (the clock changes kind) ends it.
    talks.clock["now"] = ("sim", "2028-04-01")
    assert offer(talks, pid, 9_000_000).decision != "blocked"


def test_walk_year_veteran_may_refuse_in_season(talks, monkeypatch):
    monkeypatch.setattr(et, "_refusal_chance", lambda player, kind: 1.0)
    pid = _pid("normal")
    vet = dict(years_left=1, service=6 * 172)
    r = offer(talks, pid, 11_000_000, **vet)
    assert r.decision == "refused"
    assert talks.news and "test free agency" in talks.news[0]
    assert offer(talks, pid, 12_000_000, **vet).decision == "refused"
    assert len(talks.news) == 1  # told once
    assert view(talks, pid)["status"] == "refuses"
    # A crazy offer still lands.
    assert offer(talks, pid, 15_000_000, **vet).decision == "accepted"


def test_refusals_only_in_season_and_only_walk_year_veterans(talks, monkeypatch):
    monkeypatch.setattr(et, "_refusal_chance", lambda player, kind: 1.0)
    # Offseason: no refusal.
    assert offer(talks, _pid("easy"), 11_000_000, phase="OFFSEASON",
                 years_left=1, service=6 * 172).decision == "accepted"
    # Not his walk year, or not 6 years of service: no refusal.
    assert offer(talks, _pid("normal"), 11_000_000, years_left=2,
                 service=6 * 172).decision == "accepted"
    assert offer(talks, _pid("hard"), 12_500_000, years_left=1,
                 service=3 * 172).decision == "accepted"


def test_a_new_club_or_season_starts_fresh(talks, monkeypatch):
    pid = _pid("normal")
    offer(talks, pid, 5_000_000)
    assert view(talks, pid)["mood"] == "impatient"
    assert view(talks, pid, team="NYY")["mood"] == "open"
    monkeypatch.setattr(et, "season_key", lambda base: "lg-2028")
    assert view(talks, pid)["mood"] == "open"


def test_too_long_for_his_age_is_countered_on_length(talks, monkeypatch):
    monkeypatch.setattr("services.contract_negotiator._age_of", lambda p: 34)
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 2)
    r = offer(talks, _pid("easy"), 11_000_000, years=5)
    assert r.decision == "countered" and r.counter_years == 2


# --- the endpoints, on the real pricing -------------------------------------------


class _Hitter:
    def __init__(self, pid, quality=58, age=28):
        from datetime import date

        self.player_id = pid
        self.first_name, self.last_name = "Pat", pid
        self.is_pitcher = False
        self.primary_position = "CF"
        self.birthdate = f"{date.today().year - age}-01-01"
        self.ph = self.ch = self.eye = self.sp = self.fa = self.arm = quality


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    from api.routers import contracts as router

    root = tmp_path / "data"
    root.mkdir()
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\nBAL,O,B,BAL,E,S,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    (root / "users.txt").write_text("commish,pass,admin,\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    monkeypatch.setattr(et, "season_key", lambda base: "lg-2027")
    monkeypatch.setattr(et, "talks_clock", lambda base: ("none", ""))
    monkeypatch.setattr(router, "_resolve_player", lambda pid: _Hitter(pid))
    monkeypatch.setattr(router, "_roster_team_index", lambda: {"P1": "BAL", "P2": "BAL"})
    monkeypatch.setattr(router, "_current_league_phase", lambda: "OFFSEASON")
    monkeypatch.setattr(router, "_service_for", lambda pid: (900, 2_000_000, 2))
    calls = []
    monkeypatch.setattr(router, "extend_contract",
                        lambda pid, **kw: calls.append((pid, kw)) or {"player_id": pid, **kw})
    yield SimpleNamespace(router=router, root=root, calls=calls)
    path_utils._DATA_DIR_CACHE.clear()


ADMIN = {"r": "admin", "u": "commish"}


def test_preview_shows_his_ask_but_no_answer(endpoint):
    out = endpoint.router.evaluate_extension("P1", {"years": 3}, identity=ADMIN)
    assert out["ask_salary"] > 0 and out["status"] == "open"
    for leak in ("decision", "counter_salary", "fair_market_salary"):
        assert leak not in out
    assert out["eligibility"]["eligible"] is True


def test_offering_his_ask_signs_him(endpoint):
    ask = endpoint.router.evaluate_extension("P1", {"years": 3}, identity=ADMIN)["ask_salary"]
    out = endpoint.router.extend_player_contract(
        "P1", {"additional_years": 3, "annual_salary": ask}, identity=ADMIN)
    assert out["negotiation"]["decision"] == "accepted"
    assert endpoint.calls == [("P1", {"additional_years": 3, "annual_salary": ask,
                                      "guaranteed": None, "buyout_guarantee": None})]


def test_a_low_offer_is_countered_with_a_409(endpoint):
    from fastapi import HTTPException

    ask = endpoint.router.evaluate_extension("P2", {"years": 3}, identity=ADMIN)["ask_salary"]
    with pytest.raises(HTTPException) as err:
        endpoint.router.extend_player_contract(
            "P2", {"additional_years": 3, "annual_salary": int(ask * 0.5)}, identity=ADMIN)
    assert err.value.status_code == 409
    detail = err.value.detail
    assert detail["code"] == "countered"
    assert detail["negotiation"]["ask_salary"] == ask  # a lowball doesn't move him
    assert endpoint.calls == []
    # The next preview shows him less patient.
    assert endpoint.router.evaluate_extension(
        "P2", {"years": 3}, identity=ADMIN)["mood"] == "impatient"


def test_counters_vary_so_two_asks_do_not_reveal_his_minimum(talks):
    steps = {round(et._step(f"P{i}", 1), 3) for i in range(20)}
    assert len(steps) > 10 and min(steps) >= 0.28 and max(steps) <= 0.52


def test_he_never_takes_a_pay_cut(talks, monkeypatch):
    # Overpaid: his fair price is floored at his 12M salary.
    monkeypatch.setattr(et, "fair_price", lambda *a, **k: 12_000_000)
    pid = _pid("easy")
    r = et.respond_to_offer(PLAYER, pid, team_id="BAL", years=3, salary=11_500_000,
                            service_time_days=0, current_annual_salary=12_000_000,
                            current_years_left=2, phase="OFFSEASON", data_dir=talks.dir)
    assert r.decision == "countered"


def test_mood_reads_full_once_a_shutdown_is_over(talks):
    pid = _pid("normal")
    offer(talks, pid, 5_000_000)
    days = offer(talks, pid, 5_000_000).shutdown_days
    assert view(talks, pid)["mood"] == "about to walk away"
    talks.clock["now"] = ("sim", f"2027-05-{1 + days:02d}")
    assert view(talks, pid)["mood"] == "open"
