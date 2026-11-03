"""8.8.0: owners can trust where their free-agent bids stand (backlog #65, #67).

alpha-test's owners lost players their bids were shown leading: "leading"
was the biggest total on the table, but a player signs the biggest total
among the offers he would ACCEPT. Now:

- the card, the Spotlight, the outbid notice and the signing all use one
  rule; under offer rules 2 an owner's own offer below the ask is never
  called leading (that would give his hidden minimum away);
- the decision day is the real one, not the window's end date;
- the last look: a CPU offer posted or raised in a pass cannot sign the
  player in it, and CPU clubs do not bid in the pass that decides him;
- a failed signing goes on to the next offer he would take (16 alpha-test
  players were left unsigned with offers on the table);
- owners who bid hear how it ended;
- each bid carries the player's position, and only the club's owner (or the
  commissioner) may read its bids.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import fa_negotiations as neg

PLAYER = object()


def _offer(team, years, salary, *, cpu=False):
    return {
        "team_id": team,
        "years": years,
        "annual_salary": salary,
        "signing_bonus": 0,
        "level": "ACT",
        "date": "2026-10-19",
        "is_cpu": cpu,
    }


def _negotiation(*offers, rules=2, opened_day=1):
    return {
        "player_id": "P1",
        "rules": rules,
        "status": "open",
        "opened_day": opened_day,
        "opened_date": "2026-10-19",
        "deadline_date": "2026-11-02",
        "offers": list(offers),
        "resolution": None,
    }


@pytest.fixture
def terms(monkeypatch):
    """Offer rules 2 with an ask of $5M a year and a hidden minimum of $4M."""

    state = {"ask": 5_000_000, "minimum": 4_000_000, "too_long": False}

    def fa_terms(player, player_id, *, years):
        return {
            "ask": state["ask"],
            "minimum": state["minimum"],
            "preferred_years": 3,
            "too_long": state["too_long"],
        }

    def fa_accepts(player, player_id, *, years, salary):
        return salary >= state["minimum"] and not state["too_long"]

    monkeypatch.setattr("services.extension_talks.fa_terms", fa_terms)
    monkeypatch.setattr("services.extension_talks.fa_accepts", fa_accepts)
    return state


class _Ev:
    def __init__(self, decision):
        self.decision = decision


def _rules_1_minimum(monkeypatch, minimum):
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer",
        lambda p, **k: _Ev(
            "accepted" if k["offered_annual_salary"] >= minimum else "countered"
        ),
    )


def _signs(negotiation):
    """Who the player signs with if he decides now."""
    signed = {}

    def sign_fn(*, team_id, player_id, offer, player):
        signed["team"] = team_id
        return True

    neg._resolve(negotiation, "P1", PLAYER, sign_fn, None, "2026-11-02", forced=True)
    return signed.get("team")


# --- where a bid stands -----------------------------------------------------


def test_a_bigger_total_he_would_not_take_does_not_lead(monkeypatch):
    """alpha-test's COL: 3 x $5.25M (the biggest total) lost to IND's
    2 x $6.68M, the best offer the player would take."""

    _rules_1_minimum(monkeypatch, 6_000_000)
    n = _negotiation(
        _offer("COL", 3, 5_250_000), _offer("IND", 2, 6_680_000, cpu=True), rules=1
    )
    view = neg.team_standing(n, "COL", PLAYER)
    assert view["standing"] == "wont_accept"
    assert view["leading_offer"]["team_id"] == "IND"
    assert _signs(n) == "IND"


def test_an_offer_at_his_ask_with_the_biggest_total_leads(terms):
    n = _negotiation(_offer("BAL", 2, 5_000_000), _offer("CPU", 2, 4_500_000, cpu=True))
    view = neg.team_standing(n, "BAL", PLAYER)
    assert view["standing"] == "leading"
    assert view["ask"] == 5_000_000
    assert view["rival_offer"]["team_id"] == "CPU"
    assert _signs(n) == "BAL"


def test_a_bigger_total_he_would_take_outbids_you(terms):
    n = _negotiation(_offer("BAL", 2, 5_000_000), _offer("CPU", 3, 4_500_000, cpu=True))
    view = neg.team_standing(n, "BAL", PLAYER)
    assert view["standing"] == "outbid"
    assert view["leading_offer"]["team_id"] == "CPU"
    assert _signs(n) == "CPU"


def test_your_offer_below_his_ask_is_never_called_leading(terms):
    """Saying it leads would tell the owner it clears his hidden minimum."""

    # Above his minimum (so it would win), but below his ask.
    n = _negotiation(_offer("BAL", 3, 4_500_000), _offer("CPU", 2, 4_200_000, cpu=True))
    view = neg.team_standing(n, "BAL", PLAYER)
    assert view["standing"] == "below_ask"
    assert view["leading_offer"] is None
    # Below his minimum too: the same answer.
    terms["minimum"] = 4_600_000
    assert neg.team_standing(n, "BAL", PLAYER)["standing"] == "below_ask"
    # A rival he would take with a bigger total outbids it either way.
    n = _negotiation(_offer("BAL", 3, 4_500_000), _offer("CPU", 3, 4_800_000, cpu=True))
    assert neg.team_standing(n, "BAL", PLAYER)["standing"] == "outbid"


def test_a_deal_too_long_for_his_age(terms):
    terms["too_long"] = True
    n = _negotiation(_offer("BAL", 6, 9_000_000))
    assert neg.team_standing(n, "BAL", PLAYER)["standing"] == "too_long"


def test_the_card_and_the_signing_always_agree(terms):
    """Every standing the card shows matches whom he signs."""

    grid = [3_500_000, 4_200_000, 5_000_000, 6_000_000]
    for mine in grid:
        for rival in grid:
            for years in (1, 2, 3):
                n = _negotiation(
                    _offer("BAL", 2, mine), _offer("CPU", years, rival, cpu=True)
                )
                standing = neg.team_standing(n, "BAL", PLAYER)["standing"]
                winner = _signs(_negotiation(*[dict(o) for o in n["offers"]]))
                if standing == "leading":
                    assert winner == "BAL", (mine, rival, years)
                if standing == "outbid":
                    assert winner == "CPU", (mine, rival, years)


# --- when he decides ----------------------------------------------------------


def test_the_decision_day_is_his_own_not_the_windows_end():
    patience = neg._window_patience("P1", 14)
    n = _negotiation(_offer("BAL", 2, 5_000_000), opened_day=2)
    day = min(14, 2 + patience)
    window = {"status": "open", "day": 2, "total_days": 14}
    if day > 2:
        assert neg.decision_timing(n, window) == {"kind": "window_day", "day": day, "total": 14}
    window["day"] = day
    assert neg.decision_timing(n, window) == {"kind": "today", "day": day, "total": 14}
    assert neg.decision_timing(n, {"status": "closed"}) == {"kind": "next_sim_day"}
    season = dict(n, opened_day=None)
    assert neg.decision_timing(season, None) == {"kind": "date", "date": "2026-11-02"}


# --- the last look ------------------------------------------------------------


def _ripe_day():
    day = 1 + neg._window_patience("P1", 14)
    assert day < 14  # not the final day for this player id
    return day


def _market(monkeypatch, book):
    monkeypatch.setattr(
        "services.finance_ai.build_cpu_free_agent_bid_book", lambda p, teams, **k: dict(book)
    )
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 2)
    monkeypatch.setattr("services.contract_negotiator.fair_market_salary", lambda p, **k: 3_000_000)


def _accept_all(monkeypatch):
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer", lambda p, **k: _Ev("accepted")
    )


def _bid(tmp_path, team="BAL", salary=4_000_000):
    neg.submit_offer("P1", team, years=2, annual_salary=salary, sim_date="2026-10-19",
                     window_day=1, data_dir=tmp_path)


def _process(tmp_path, day, signed):
    return neg.process_negotiations(
        "2026-10-25", data_dir=tmp_path, players_by_id={"P1": PLAYER}, teams=[object()],
        sign_fn=lambda **k: signed.append(k["team_id"]) or True,
        window_day=day, window_total=14,
    )


def test_a_cpu_offer_cannot_sign_him_in_the_pass_it_appears(tmp_path, monkeypatch):
    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    _market(monkeypatch, {"CPU1": 9_000_000})
    _bid(tmp_path)
    signed: list = []
    summary = _process(tmp_path, _ripe_day(), signed)
    assert signed == [] and summary["last_look"] == ["P1"]
    view = neg.list_team_negotiations("BAL", data_dir=tmp_path, players_by_id={"P1": PLAYER})
    assert view[0]["standing"] == "outbid"
    # The owner did not answer: the next pass signs the CPU club.
    _process(tmp_path, _ripe_day() + 1, signed)
    assert signed == ["CPU1"]


def test_cpu_clubs_do_not_bid_in_the_pass_that_decides_him(tmp_path, monkeypatch):
    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    _market(monkeypatch, {"CPU1": 9_000_000})
    _bid(tmp_path)
    signed: list = []
    _process(tmp_path, 14, signed)
    assert signed == ["BAL"]
    offers = neg.get_negotiation("P1", data_dir=tmp_path)["offers"]
    assert [o["team_id"] for o in offers] == ["BAL"]


def test_without_an_owner_bid_the_cpu_market_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    _market(monkeypatch, {"CPU1": 9_000_000})
    _bid(tmp_path, team="CPU2", salary=1_000_000)
    payload = neg.load_negotiations(data_dir=tmp_path)
    payload["negotiations"]["P1"]["offers"][0]["is_cpu"] = True
    neg.save_negotiations(payload, data_dir=tmp_path)
    signed: list = []
    _process(tmp_path, _ripe_day(), signed)
    assert signed == ["CPU1"]


# --- failed signings and empty negotiations -----------------------------------


def test_a_failed_signing_at_the_deadline_goes_to_the_next_offer(tmp_path, monkeypatch):
    """alpha-test 2027: 16 players stayed unsigned after the window closed."""

    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    for team, salary in (("BOS", 4_400_000), ("CHA", 4_300_000), ("WAS", 4_200_000)):
        _bid(tmp_path, team=team, salary=salary)
    tried: list = []

    def sign_fn(*, team_id, player_id, offer, player):
        tried.append(team_id)
        return team_id != "BOS"  # BOS's roster is full

    summary = neg.process_negotiations(
        "2026-11-02", data_dir=tmp_path, players_by_id={"P1": PLAYER}, sign_fn=sign_fn
    )
    assert tried == ["BOS", "CHA"]
    assert [s["signed_team"] for s in summary["signed"]] == ["CHA"]
    n = neg.get_negotiation("P1", data_dir=tmp_path)
    assert n["status"] == "resolved" and n["resolution"]["signed_team"] == "CHA"


def test_every_signing_failing_at_the_deadline_closes_with_no_deal(tmp_path, monkeypatch):
    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    _bid(tmp_path, team="BOS")
    summary = neg.process_negotiations(
        "2026-11-02", data_dir=tmp_path, players_by_id={"P1": PLAYER},
        sign_fn=lambda **k: False,
    )
    assert summary["no_deal"] == ["P1"]
    assert neg.get_negotiation("P1", data_dir=tmp_path)["resolution"]["outcome"] == "no_deal"


def test_a_negotiation_with_no_offers_left_closes_at_its_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _bid(tmp_path, team="BOS")
    payload = neg.load_negotiations(data_dir=tmp_path)
    payload["negotiations"]["P1"]["offers"] = []
    neg.save_negotiations(payload, data_dir=tmp_path)
    neg.process_negotiations("2026-11-02", data_dir=tmp_path, players_by_id={"P1": PLAYER})
    assert neg.get_negotiation("P1", data_dir=tmp_path)["resolution"]["outcome"] == "no_deal"


# --- owners hear how it ended -------------------------------------------------


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text(
        "commish,pass,admin,\nbal_owner,pass,owner,BAL\nnyy_owner,pass,owner,NYY\n",
        encoding="utf-8",
    )
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\nP1,Ann,Able,SS,0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _history(team):
    from services.notification_engine import load_history

    return load_history(team)


def test_owners_who_bid_hear_who_signed_him(league, monkeypatch):
    from services.fa_window_notices import owner_notifier

    _accept_all(monkeypatch)
    players = {"P1": SimpleNamespace(first_name="Ann", last_name="Able")}
    notify = owner_notifier(league, players)
    bids = [
        _offer("BAL", 2, 4_000_000),
        _offer("NYY", 3, 5_000_000),
        _offer("CHA", 4, 6_000_000, cpu=True),
    ]
    notify({"type": "fa_signed", "player_id": "P1", "signed_team": "NYY",
            "offer": bids[1], "bids": bids, "rules": 1})
    lost = _history("BAL")[0]
    assert lost["rule_id"] == "fa_signed_elsewhere"
    assert lost["title"] == "Ann Able signed with NYY"
    assert lost["message"].startswith("Ann Able signed with NYY: 3 yrs at $5M/yr.")
    assert _history("NYY")[0]["title"] == "You signed Ann Able"
    notify({"type": "fa_no_deal", "player_id": "P1", "bids": bids})
    assert _history("BAL")[0]["title"] == "Ann Able took no deal"
    notify({"type": "fa_sign_failed", "player_id": "P1", "team_id": "BAL", "offer": bids[0]})
    assert _history("BAL")[0]["title"] == "Could not sign Ann Able"


def test_a_lost_notice_never_says_whether_he_would_have_taken_yours(league, monkeypatch):
    """That would give his hidden minimum away (the review of 8.8.0)."""

    from services.fa_window_notices import owner_notifier

    _rules_1_minimum(monkeypatch, 5_000_000)
    notify = owner_notifier(league, {"P1": PLAYER})
    bids = [_offer("BAL", 4, 4_000_000), _offer("CHA", 2, 6_000_000, cpu=True)]
    notify({"type": "fa_signed", "player_id": "P1", "signed_team": "CHA",
            "offer": bids[1], "bids": bids})
    message = _history("BAL")[0]["message"]
    assert "would not have taken" not in message
    assert "Your offer was 4 yrs at $4M/yr." in message


def test_an_owner_whose_signing_failed_is_not_told_another_club_won(league):
    from services.fa_window_notices import owner_notifier

    notify = owner_notifier(league, {"P1": PLAYER})
    bids = [_offer("BAL", 4, 6_000_000), _offer("NYY", 2, 5_000_000)]
    notify({"type": "fa_sign_failed", "player_id": "P1", "team_id": "BAL", "offer": bids[0]})
    notify({"type": "fa_signed", "player_id": "P1", "signed_team": "NYY",
            "offer": bids[1], "bids": bids, "failed_teams": ["BAL"]})
    assert [e["title"] for e in _history("BAL")] == ["Could not sign P1"]
    assert _history("NYY")[0]["title"] == "You signed P1"


def test_before_his_deciding_pass_a_failed_signing_tries_no_other_offer(tmp_path, monkeypatch):
    """The early-signing and last-look checks were made on that offer alone."""

    monkeypatch.setattr(neg, "OFFER_RULES", 1)
    _accept_all(monkeypatch)
    monkeypatch.setattr("services.contract_negotiator.fair_market_salary", lambda p, **k: 1_000_000)
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 2)
    _bid(tmp_path, team="BOS", salary=4_400_000)  # well above his value: signs early
    _bid(tmp_path, team="CHA", salary=1_000_000)
    tried: list = []
    neg.process_negotiations(
        "2026-10-21", data_dir=tmp_path, players_by_id={"P1": PLAYER},
        sign_fn=lambda **k: tried.append(k["team_id"]) or False,
    )
    assert tried == ["BOS"]
    n = neg.get_negotiation("P1", data_dir=tmp_path)
    assert n["status"] == "open" and [o["team_id"] for o in n["offers"]] == ["CHA"]


def test_no_notifier_off_the_active_league(tmp_path):
    from services.fa_window_notices import owner_notifier

    assert owner_notifier(tmp_path, {}) is None


# --- the bids list and the offer dialog ----------------------------------------


def test_only_the_clubs_owner_reads_its_bids(monkeypatch):
    import api.routers.free_agency as fa

    monkeypatch.setattr(neg, "list_team_negotiations", lambda team, **k: [])
    monkeypatch.setattr(fa, "_players_by_id", lambda: {})
    with pytest.raises(HTTPException) as err:
        fa.list_fa_negotiations(team_id="BOS", identity={"r": "owner", "t": "COL"})
    assert err.value.status_code == 403
    assert fa.list_fa_negotiations(team_id="COL", identity={"r": "owner", "t": "COL"})
    assert fa.list_fa_negotiations(team_id="BOS", identity={"r": "admin", "t": ""})


def test_each_bid_carries_the_players_position(monkeypatch):
    import api.routers.free_agency as fa

    rows = [{"player_id": "P1", "status": "open"}, {"player_id": "P2", "status": "open"}]
    monkeypatch.setattr(neg, "list_team_negotiations", lambda team, **k: [dict(r) for r in rows])
    monkeypatch.setattr(fa, "_players_by_id", lambda: {
        "P1": SimpleNamespace(first_name="Ann", last_name="Able", primary_position="SS",
                              is_pitcher=False),
        "P2": SimpleNamespace(first_name="Cal", last_name="Cole", primary_position="P",
                              is_pitcher=True),
    })
    monkeypatch.setattr(fa, "get_role", lambda p: "SP")
    out = fa.list_fa_negotiations(team_id="COL", identity={"r": "owner", "t": "COL"})
    by_id = {r["player_id"]: r for r in out["negotiations"]}
    assert (by_id["P1"]["primary_position"], by_id["P1"]["is_pitcher"], by_id["P1"]["role"]) == ("SS", False, "")
    assert (by_id["P2"]["is_pitcher"], by_id["P2"]["role"]) == (True, "SP")
    assert by_id["P1"]["player_name"] == "Ann Able"


def test_the_offer_dialog_says_how_he_answers(terms, monkeypatch):
    import api.routers.free_agency as fa

    assert fa._offer_verdict(PLAYER, "P1", 2, 2, 5_000_000)["code"] == "at_ask"
    below = fa._offer_verdict(PLAYER, "P1", 2, 2, 4_500_000)
    assert below["code"] == "below_ask" and "may not be enough" in below["text"]
    terms["too_long"] = True
    assert fa._offer_verdict(PLAYER, "P1", 2, 6, 9_000_000)["code"] == "too_long"
    monkeypatch.setattr("services.contract_negotiator._age_of", lambda p: 34)
    assert fa._length_rule(PLAYER, 2) == {"age": 34, "max_years": 3}
    monkeypatch.setattr("services.contract_negotiator._age_of", lambda p: 29)
    assert fa._length_rule(PLAYER, 2) == {"age": 29, "max_years": None}


@pytest.mark.parametrize("bidding", [False, True])
def test_the_offer_dialog_answers_only_outside_the_bidding_window(monkeypatch, bidding):
    """8.8.1 (owner call): an answer previewed while bidding is open reads as
    "you'll get him" when other clubs can still beat it, and on rules 1 lets
    an owner nudge the salary until it flips to find his exact price."""
    import api.routers.free_agency as fa
    from services.contract_negotiator import ExtensionEvaluation

    monkeypatch.setattr(fa, "_find_player", lambda pid: PLAYER)
    monkeypatch.setattr(fa, "_refuse_if_owned", lambda *a: None)
    monkeypatch.setattr(fa, "_offer_rules", lambda pid: 1)
    monkeypatch.setattr(fa, "_competing_bids", lambda *a, **k: [])
    monkeypatch.setattr(fa, "_phase_gate_for_fa", lambda: None)
    monkeypatch.setattr(fa, "_length_rule", lambda p, y: {"age": 30, "max_years": None})
    monkeypatch.setattr(fa, "_bidding_window_open", lambda: bidding)
    monkeypatch.setattr(
        fa, "evaluate_extension_offer",
        lambda *a, **k: ExtensionEvaluation(
            decision="countered", fair_market_salary=5_000_000, fair_market_years=3,
            counter_salary=4_800_000, counter_years=3, reason="below market",
            service_tier="free_agent",
        ),
    )
    monkeypatch.setattr(
        fa, "_offer_verdict", lambda *a: {"code": "wont_accept", "text": "no"}
    )
    out = fa.evaluate_fa_offer(
        "P1", {"years": 3, "annual_salary": 4_000_000}, identity={"r": "admin", "t": ""}
    )
    assert out["bidding_window"] is bidding
    assert out["fair_market_salary"] == 5_000_000
    if bidding:
        assert out["verdict"]["code"] == "bidding"
        assert "other clubs can still beat" in out["verdict"]["text"]
        assert out["decision"] is None and out["counter_salary"] is None
        assert out["counter_years"] is None and out["reason"] == ""
    else:
        assert out["verdict"]["code"] == "wont_accept"
        assert (out["decision"], out["counter_salary"]) == ("countered", 4_800_000)
