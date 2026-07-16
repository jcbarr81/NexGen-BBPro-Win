import csv
import json
import importlib


def _write_min_league(tmp_path, team_ids):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    teams_file = data / "teams.csv"
    with teams_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "team_id",
                "name",
                "city",
                "abbreviation",
                "division",
                "stadium",
                "primary_color",
                "secondary_color",
                "owner_id",
            ],
        )
        writer.writeheader()
        for i, tid in enumerate(team_ids, start=1):
            writer.writerow(
                dict(
                    team_id=tid,
                    name=f"Team {i}",
                    city=f"City{i}",
                    abbreviation=tid,
                    division="EAST",
                    stadium=f"Stadium{i}",
                    primary_color="#112233",
                    secondary_color="#445566",
                    owner_id="",
                )
            )
    # season stats for order: worst first
    stats = {
        "teams": {
            team_ids[0]: {"w": 10, "l": 90, "r": 500, "ra": 800},
            team_ids[1]: {"w": 40, "l": 60, "r": 550, "ra": 600},
            team_ids[2]: {"w": 60, "l": 40, "r": 650, "ra": 600},
            team_ids[3]: {"w": 90, "l": 10, "r": 800, "ra": 500},
        }
    }
    (data / "season_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _score_simple(p):
    # Prospect dict may have strings or ints; coerce to int safely
    if p.get("is_pitcher"):
        return int(p.get("endurance", 0) or 0) + int(p.get("control", 0) or 0) + int(p.get("movement", 0) or 0)
    return int(p.get("ch", 0) or 0) + int(p.get("ph", 0) or 0) + int(p.get("sp", 0) or 0)


def test_draft_headless_first_round_writes_files(tmp_path, monkeypatch):
    # Route BASE to temporary directory before importing modules that cache it
    import utils.path_utils as path_utils

    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)
    # Import after patch so modules capture patched BASE
    draft_pool = importlib.import_module("playbalance.draft_pool")
    draft_state = importlib.import_module("services.draft_state")
    draft_pool = importlib.reload(draft_pool)
    draft_state = importlib.reload(draft_state)

    year = 2025
    seed = 12345
    team_ids = ["A", "B", "C", "D"]
    _write_min_league(tmp_path, team_ids)

    # Generate and save pool
    pool_objs = draft_pool.generate_draft_pool(year, size=40, seed=seed)
    draft_pool.save_draft_pool(year, pool_objs)
    pool = draft_pool.load_draft_pool(year)
    assert pool and (tmp_path / "data" / f"draft_pool_{year}.json").exists()
    assert (tmp_path / "data" / f"draft_pool_{year}.csv").exists()

    # Compute order and initialize state with seed
    order = draft_state.compute_order_from_season_stats(seed=seed)
    assert order[:2] == ["A", "B"]  # worst first
    state = draft_state.initialize_state(year, order=order, seed=seed)
    assert state["overall_pick"] == 1

    # Auto-pick one round (simple scoring)
    selected_ids = set()
    for i, tid in enumerate(order, start=1):
        remaining = [p for p in pool if p["player_id"] not in selected_ids]
        best = max(remaining, key=_score_simple)
        pid = best["player_id"]
        selected_ids.add(pid)
        draft_state.append_result(year, team_id=tid, player_id=pid, rnd=1, overall=i)
        state.setdefault("selected", []).append({
            "round": 1,
            "overall_pick": i,
            "team_id": tid,
            "player_id": pid,
        })
        state["overall_pick"] = i + 1
        draft_state.save_state(year, state)

    # Verify writes
    results = tmp_path / "data" / f"draft_results_{year}.csv"
    assert results.exists()
    with results.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(order)
    assert rows[0]["overall_pick"] == "1" and rows[0]["team_id"] == order[0]

    saved_state = json.loads((tmp_path / "data" / f"draft_state_{year}.json").read_text(encoding="utf-8"))
    assert len(saved_state.get("selected", [])) == len(order)
    assert saved_state.get("seed") == seed


def test_draft_resume_from_mid_round(tmp_path, monkeypatch):
    import utils.path_utils as path_utils

    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)
    draft_pool = importlib.import_module("playbalance.draft_pool")
    draft_state = importlib.import_module("services.draft_state")
    draft_pool = importlib.reload(draft_pool)
    draft_state = importlib.reload(draft_state)

    year = 2025
    seed = 23456
    team_ids = ["A", "B", "C", "D"]
    _write_min_league(tmp_path, team_ids)

    pool_objs = draft_pool.generate_draft_pool(year, size=30, seed=seed)
    draft_pool.save_draft_pool(year, pool_objs)
    pool = draft_pool.load_draft_pool(year)

    order = draft_state.compute_order_from_season_stats(seed=seed)
    state = draft_state.initialize_state(year, order=order, seed=seed)

    # Preselect two picks
    pre_selected = []
    for i, tid in enumerate(order[:2], start=1):
        best = max(pool, key=_score_simple)
        pid = best["player_id"]
        pool = [p for p in pool if p["player_id"] != pid]
        pre_selected.append({"round": 1, "overall_pick": i, "team_id": tid, "player_id": pid})
        draft_state.append_result(year, team_id=tid, player_id=pid, rnd=1, overall=i)
    state["selected"] = pre_selected
    state["overall_pick"] = 3
    draft_state.save_state(year, state)

    # Resume to finish round 1
    for i, tid in enumerate(order[2:], start=3):
        best = max(pool, key=_score_simple)
        pid = best["player_id"]
        pool = [p for p in pool if p["player_id"] != pid]
        draft_state.append_result(year, team_id=tid, player_id=pid, rnd=1, overall=i)
        state.setdefault("selected", []).append({
            "round": 1,
            "overall_pick": i,
            "team_id": tid,
            "player_id": pid,
        })
        state["overall_pick"] = i + 1
        draft_state.save_state(year, state)

    # Verify completion of round 1
    with (tmp_path / "data" / f"draft_results_{year}.csv").open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(order)


def test_pool_sanity_checks(tmp_path, monkeypatch):
    import utils.path_utils as path_utils
    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)
    draft_pool = importlib.import_module("playbalance.draft_pool")

    year = 2025
    pool = draft_pool.generate_draft_pool(year, size=200, seed=999)
    # Distribution sanity: pitchers between 35% and 55%
    pitch_cnt = sum(1 for p in pool if p.is_pitcher)
    ratio = pitch_cnt / len(pool)
    assert 0.35 <= ratio <= 0.55
    # Ensure key scarce positions exist
    primaries = {p.primary_position for p in pool}
    for pos in ("C", "SS", "CF"):
        assert pos in primaries
    # Birth years are plausible: draftees span a realistic class age range
    # (HS ~18 through college ~21), not a single uniform age.
    years = {int(p.birthdate.split("-")[0]) for p in pool}
    assert len(years) > 1
    assert all(year - 22 <= by <= year - 16 for by in years)
