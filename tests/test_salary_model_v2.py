"""Salary model v2: a convex, service-time-aware contract salary.

Two things are asserted here:

1. THE MODEL — a star-weighted quality maps onto a CONVEX open-market curve
   (stars earn disproportionately more), and a service-time tier discounts
   cost-controlled players (pre-arb ~ league minimum, arbitration a rising
   fraction, free agency full market).

2. THE GATE — deploying the new model must NEVER re-price contracts that
   already exist in a live league. The seeder only fills MISSING rows, so a
   redeploy over the alpha-test league (which already has a contract for every
   rostered player) cannot rewrite a single existing salary.
"""

import json
from types import SimpleNamespace

from services import contracts_service as cs
from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    MAX_ESTIMATED_SALARY,
    MARKET_MAX_SALARY,
    SALARY_MODEL_VERSION,
    estimate_contract_salary,
    estimate_market_value_for_player,
    seed_inaugural_contracts_from_rosters,
)

YEAR = 2032


def _hitter(ovr, *, pid="H", age=27):
    return SimpleNamespace(
        player_id=pid,
        birthdate=f"{YEAR - age}-06-15",
        is_pitcher=False,
        primary_position="1B",
        ch=ovr, ph=ovr, sp=ovr, eye=ovr, fa=ovr, arm=ovr,
    )


def _pitcher(ovr, *, pid="P", age=27):
    return SimpleNamespace(
        player_id=pid,
        birthdate=f"{YEAR - age}-06-15",
        is_pitcher=True,
        primary_position="P",
        arm=ovr, control=ovr, movement=ovr, endurance=ovr,
    )


# --- The market curve --------------------------------------------------------

def test_market_value_monotonic_and_bounded():
    prev = -1
    for ovr in range(30, 90, 5):
        v = estimate_market_value_for_player(_hitter(ovr))
        assert DEFAULT_MIN_SALARY <= v <= MAX_ESTIMATED_SALARY
        assert v >= prev, f"non-monotonic at ovr={ovr}"
        prev = v


def test_market_value_is_convex_stars_break_away():
    # Equal rating steps must produce ACCELERATING dollar steps.
    v40 = estimate_market_value_for_player(_hitter(40))
    v50 = estimate_market_value_for_player(_hitter(50))
    v60 = estimate_market_value_for_player(_hitter(60))
    v70 = estimate_market_value_for_player(_hitter(70))
    assert (v70 - v60) > (v60 - v50) > (v50 - v40)


def test_star_versus_scrub_has_a_real_gap():
    # The whole point: a star is worth many times a replacement player, not the
    # ~30% gap the old flat model produced.
    scrub = estimate_market_value_for_player(_hitter(42))
    star = estimate_market_value_for_player(_hitter(68))
    assert star > scrub * 5
    assert star >= 18_000_000


def test_elite_approaches_ceiling():
    elite = estimate_market_value_for_player(_hitter(80))
    assert elite >= MARKET_MAX_SALARY * 0.9


def test_pitcher_and_hitter_both_priced():
    assert estimate_market_value_for_player(_pitcher(68)) >= 18_000_000
    assert estimate_market_value_for_player(_pitcher(42)) < 3_000_000


def test_none_and_no_ratings_floor_to_minimum():
    assert estimate_market_value_for_player(None) == DEFAULT_MIN_SALARY
    blank = SimpleNamespace(is_pitcher=False, primary_position="1B",
                            ch=0, ph=0, sp=0, eye=0, fa=0, arm=0)
    assert estimate_market_value_for_player(blank) == DEFAULT_MIN_SALARY


# --- Service-time tiers ------------------------------------------------------

def test_pre_arb_is_league_minimum_regardless_of_quality():
    # A 22yo (no service history) is pre-arb -> paid the minimum even if elite.
    salary, market, stage, _ = estimate_contract_salary(_hitter(75), service_time_days=0, age=22)
    assert stage == "pre_arb"
    assert salary == DEFAULT_MIN_SALARY
    assert market >= 18_000_000  # ... but their market value is huge (a bargain)


def test_arbitration_is_a_rising_fraction_below_market():
    star = _hitter(68)
    market = estimate_market_value_for_player(star)
    arb1, _, s1, y1 = estimate_contract_salary(star, service_time_days=3 * 172, age=27)
    arb3, _, s3, y3 = estimate_contract_salary(star, service_time_days=5 * 172, age=29)
    assert s1 == s3 == "arb"
    assert y1 == 1 and y3 == 3
    assert DEFAULT_MIN_SALARY < arb1 < arb3 < market


def test_free_agent_is_full_market():
    star = _hitter(68)
    market = estimate_market_value_for_player(star)
    salary, _, stage, _ = estimate_contract_salary(star, service_time_days=7 * 172, age=31)
    assert stage == "fa"
    assert salary == market


def test_stage_inferred_from_age_when_no_service_history():
    star = _hitter(68)
    young = estimate_contract_salary(star, service_time_days=0, age=22)[0]
    mid = estimate_contract_salary(star, service_time_days=0, age=26)[0]
    vet = estimate_contract_salary(star, service_time_days=0, age=32)[0]
    assert young < mid < vet  # young cost-controlled, veteran at market


# --- THE GATE: existing contracts are never re-priced ------------------------

def _write_inaugural_league(tmp_path):
    data_dir = tmp_path / "league-data"
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n"
        "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n",
        encoding="utf-8",
    )
    (data_dir / "career_index.json").write_text(
        json.dumps({
            "version": 1,
            "league": {"id": "alpha"},
            "current": {"league_year": YEAR, "sequence": 1},
            "seasons": [],
        }),
        encoding="utf-8",
    )
    # EXISTING contract for P100 with a hand-set salary and NO salary_model stamp
    # (simulating a live league priced under the old model). P200 has none.
    (data_dir / "contracts.json").write_text(
        json.dumps({
            "version": 1,
            "players": {
                "P100": {
                    "team_id": "AAA",
                    "years_left": 4,
                    "annual_salary": 12_345_678,
                    "service_time_days": 0,
                    "arb_eligible": False,
                    "fa_year": YEAR + 4,
                    "guaranteed": True,
                    "options": [],
                    "incentives": [],
                },
            },
        }),
        encoding="utf-8",
    )
    (roster_dir / "AAA.csv").write_text("P100,ACT\nP200,ACT\n", encoding="utf-8")
    return data_dir


def test_seeding_never_reprices_existing_contracts(tmp_path):
    data_dir = _write_inaugural_league(tmp_path)

    summary = seed_inaugural_contracts_from_rosters(data_dir=data_dir)

    payload = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    # Existing contract is byte-for-byte preserved: salary unchanged, NOT stamped.
    assert payload["players"]["P100"]["annual_salary"] == 12_345_678
    assert "salary_model" not in payload["players"]["P100"]
    # Only the MISSING player was seeded, and it carries the new model stamp.
    assert summary["seeded"] == 1
    assert payload["players"]["P200"]["salary_model"] == SALARY_MODEL_VERSION


def test_reseed_is_idempotent_for_salaries(tmp_path):
    data_dir = _write_inaugural_league(tmp_path)
    seed_inaugural_contracts_from_rosters(data_dir=data_dir)
    first = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    p200_first = first["players"]["P200"]["annual_salary"]

    # Re-running the seeder (as a redeploy would) changes nothing.
    summary = seed_inaugural_contracts_from_rosters(data_dir=data_dir)
    second = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert summary["seeded"] == 0
    assert second["players"]["P100"]["annual_salary"] == 12_345_678
    assert second["players"]["P200"]["annual_salary"] == p200_first
