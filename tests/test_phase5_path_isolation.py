import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace


def _reload_module(module_name: str):
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _setup_multi_league(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils = _reload_module("utils.path_utils")
    path_utils._DATA_DIR = None
    league_registry = _reload_module("services.league_registry")

    league_registry.register_league("alpha", display_name="Alpha League")
    league_registry.register_league("beta", display_name="Beta League")
    league_registry.set_active_league("alpha", ensure_data_dir=True)

    alpha_data = league_registry.get_league_data_dir("alpha", create=True)
    beta_data = league_registry.get_league_data_dir("beta", create=True)
    return path_utils, league_registry, alpha_data, beta_data


def test_phase5_services_respect_active_league_after_switch(tmp_path, monkeypatch):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    news_logger = _reload_module("utils.news_logger")
    draft_state = _reload_module("services.draft_state")
    progress_flags = _reload_module("services.season_progress_flags")
    injury_settings = _reload_module("services.injury_settings")
    training_settings = _reload_module("services.training_settings")
    transaction_log = _reload_module("services.transaction_log")

    alpha_news = alpha_data / "news_feed.txt"
    alpha_draft_state = alpha_data / "draft_state_2099.json"
    alpha_progress = alpha_data / "season_progress.json"
    alpha_injury = alpha_data / "injury_settings.json"
    alpha_training = alpha_data / "training_settings.json"
    alpha_transactions = alpha_data / "transactions.csv"

    before_alpha = {
        "news": _read_text(alpha_news),
        "draft_state": _read_text(alpha_draft_state),
        "progress": _read_text(alpha_progress),
        "injury": _read_text(alpha_injury),
        "training": _read_text(alpha_training),
        "transactions": _read_text(alpha_transactions),
    }

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    news_logger.log_news_event("phase5-news-check")
    draft_state.save_state(2099, {"round": 1, "order": ["T1"]})
    progress_flags.mark_draft_completed(2099)
    injury_settings.set_injury_level("off")
    training_settings.update_league_training_defaults(
        hitters={"contact": 20, "power": 20, "speed": 20, "discipline": 20, "defense": 20},
        pitchers={
            "command": 20,
            "movement": 15,
            "stamina": 15,
            "velocity": 20,
            "hold": 15,
            "pitch_lab": 15,
        },
    )
    transaction_log.record_transaction(
        action="phase5-check",
        team_id="AAA",
        player_id="P-1",
        player_name="Phase Five",
    )

    beta_news = beta_data / "news_feed.txt"
    beta_draft_state = beta_data / "draft_state_2099.json"
    beta_progress = beta_data / "season_progress.json"
    beta_injury = beta_data / "injury_settings.json"
    beta_training = beta_data / "training_settings.json"
    beta_transactions = beta_data / "transactions.csv"

    assert "phase5-news-check" in (beta_news.read_text(encoding="utf-8"))
    assert json.loads(beta_draft_state.read_text(encoding="utf-8")).get("round") == 1
    progress_payload = json.loads(beta_progress.read_text(encoding="utf-8"))
    assert 2099 in progress_payload.get("draft_completed_years", [])
    injury_payload = json.loads(beta_injury.read_text(encoding="utf-8"))
    training_payload = json.loads(beta_training.read_text(encoding="utf-8"))
    assert injury_payload.get("leagues")
    assert training_payload.get("leagues")
    assert "phase5-check" in beta_transactions.read_text(encoding="utf-8")

    assert _read_text(alpha_news) == before_alpha["news"]
    assert _read_text(alpha_draft_state) == before_alpha["draft_state"]
    assert _read_text(alpha_progress) == before_alpha["progress"]
    assert _read_text(alpha_injury) == before_alpha["injury"]
    assert _read_text(alpha_training) == before_alpha["training"]
    assert _read_text(alpha_transactions) == before_alpha["transactions"]


def test_career_data_reads_follow_active_league_switch(tmp_path, monkeypatch):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    alpha_career = alpha_data / "careers" / "career_teams.json"
    beta_career = beta_data / "careers" / "career_teams.json"
    alpha_career.parent.mkdir(parents=True, exist_ok=True)
    beta_career.parent.mkdir(parents=True, exist_ok=True)

    alpha_career.write_text(
        json.dumps({"teams": {"A": {"totals": {"w": 1}}}}, indent=2),
        encoding="utf-8",
    )
    beta_career.write_text(
        json.dumps({"teams": {"B": {"totals": {"w": 2}}}}, indent=2),
        encoding="utf-8",
    )

    team_loader = _reload_module("utils.team_loader")

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    payload = team_loader._load_career_teams()
    assert payload == {"B": {"totals": {"w": 2}}}


def test_phase5_additional_services_follow_active_league_switch(tmp_path, monkeypatch):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    tuning_settings = _reload_module("services.physics_tuning_settings")
    hall_of_fame = _reload_module("services.hall_of_fame")
    record_notifications = _reload_module("services.record_notifications")

    alpha_tuning = alpha_data / "physics_tuning_overrides.json"
    alpha_hof = alpha_data / "hall_of_fame.json"
    alpha_records = alpha_data / "record_book_snapshot.json"

    before_alpha = {
        "tuning": _read_text(alpha_tuning),
        "hof": _read_text(alpha_hof),
        "records": _read_text(alpha_records),
    }

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    tuning_settings.save_physics_tuning_overrides({"offense_scale": 1.11})
    hall_of_fame.save_hall_of_fame(hall_of_fame.load_hall_of_fame())
    record_notifications.save_record_snapshot({"test-record": {"value": 1}})

    beta_tuning = beta_data / "physics_tuning_overrides.json"
    beta_hof = beta_data / "hall_of_fame.json"
    beta_records = beta_data / "record_book_snapshot.json"

    assert json.loads(beta_tuning.read_text(encoding="utf-8"))["offense_scale"] == 1.11
    assert json.loads(beta_hof.read_text(encoding="utf-8")).get("version")
    assert json.loads(beta_records.read_text(encoding="utf-8")).get("records", {}).get(
        "test-record"
    )

    assert _read_text(alpha_tuning) == before_alpha["tuning"]
    assert _read_text(alpha_hof) == before_alpha["hof"]
    assert _read_text(alpha_records) == before_alpha["records"]


def test_phase5_playbalance_and_generator_paths_follow_active_league_switch(
    tmp_path, monkeypatch
):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    alpha_bench = alpha_data / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
    beta_bench = beta_data / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
    alpha_bench.parent.mkdir(parents=True, exist_ok=True)
    beta_bench.parent.mkdir(parents=True, exist_ok=True)
    alpha_bench.write_text("metric_key,value\nalpha_metric,1\n", encoding="utf-8")
    beta_bench.write_text("metric_key,value\nbeta_metric,2\n", encoding="utf-8")

    alpha_players = alpha_data / "players.csv"
    beta_players = beta_data / "players.csv"
    alpha_players.write_text(
        "first_name,last_name,ethnicity\nAlpha,One,Test\n", encoding="utf-8"
    )
    beta_players.write_text(
        "first_name,last_name,ethnicity\nBeta,Two,Test\n", encoding="utf-8"
    )

    pb_benchmarks = _reload_module("playbalance.benchmarks")
    pb_config = _reload_module("playbalance.playbalance_config")
    player_generator = _reload_module("playbalance.player_generator")

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    bench = pb_benchmarks.load_benchmarks()
    assert "beta_metric" in bench
    assert "alpha_metric" not in bench

    cfg = pb_config.PlayBalanceConfig()
    cfg.speedBase = 77
    cfg.save_overrides()
    assert (beta_data / "playbalance_overrides.json").exists()
    assert not (alpha_data / "playbalance_overrides.json").exists()

    # The generator's active data paths must follow the league switch. Its name
    # POOL deliberately unions the shared data-root names.csv (so cloud leagues
    # aren't all "John Doe", see _load_name_pool), which means a specific
    # generate_name() output is NOT league-deterministic — assert the resolved
    # path instead of a sampled name.
    assert Path(player_generator.PLAYER_PATH).resolve() == beta_players.resolve()


def test_phase5_playbalance_config_defaults_refresh_after_league_switch(
    tmp_path, monkeypatch
):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    for data_dir, speed_base, ppa in (
        (alpha_data, 55, 3.7),
        (beta_data, 77, 4.6),
    ):
        bench_path = data_dir / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
        bench_path.parent.mkdir(parents=True, exist_ok=True)
        bench_path.write_text(
            (
                "metric_key,value\n"
                f"pitches_put_in_play_pct,0.180\n"
                f"pitches_per_pa,{ppa}\n"
                "bip_double_play_pct,0.030\n"
                "bip_gb_pct,0.440\n"
            ),
            encoding="utf-8",
        )
        (data_dir / "playbalance_overrides.json").write_text(
            json.dumps({"speedBase": speed_base}, indent=2),
            encoding="utf-8",
        )

    pb_config = _reload_module("playbalance.playbalance_config")

    alpha_cfg = pb_config.PlayBalanceConfig()
    assert int(alpha_cfg.speedBase) == 55
    assert float(alpha_cfg.targetPitchesPerPA) == 3.7

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    beta_cfg = pb_config.PlayBalanceConfig()
    assert int(beta_cfg.speedBase) == 77
    assert float(beta_cfg.targetPitchesPerPA) == 4.6


def test_phase5_player_loader_and_rating_display_caches_follow_active_league(
    tmp_path, monkeypatch
):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    player_csv_header = (
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,"
        "gf,ch,ph,sp,pl,vl,sc,fa,arm,is_pitcher\n"
    )
    alpha_players_csv = player_csv_header + "P1,Alpha,One,2000-01-01,72,190,R,SS,55,10,10,10,10,10,10,10,10,false\n"
    beta_players_csv = player_csv_header + "P1,Beta,Two,2000-01-01,72,190,R,SS,55,90,10,10,10,10,10,10,10,false\n"

    (alpha_data / "players.csv").write_text(alpha_players_csv, encoding="utf-8")
    (beta_data / "players.csv").write_text(beta_players_csv, encoding="utf-8")

    alpha_stats_path = alpha_data / "season_stats.json"
    beta_stats_path = beta_data / "season_stats.json"
    alpha_career_dir = alpha_data / "careers"
    beta_career_dir = beta_data / "careers"
    alpha_career_dir.mkdir(parents=True, exist_ok=True)
    beta_career_dir.mkdir(parents=True, exist_ok=True)

    alpha_stats_path.write_text(
        json.dumps({"players": {"P1": {"h": 1}}, "teams": {}, "history": []}, indent=2),
        encoding="utf-8",
    )
    beta_stats_path.write_text(
        json.dumps({"players": {"P1": {"h": 9}}, "teams": {}, "history": []}, indent=2),
        encoding="utf-8",
    )
    (alpha_career_dir / "career_players.json").write_text(
        json.dumps({"players": {"P1": {"totals": {"h": 11}}}}, indent=2),
        encoding="utf-8",
    )
    (beta_career_dir / "career_players.json").write_text(
        json.dumps({"players": {"P1": {"totals": {"h": 99}}}}, indent=2),
        encoding="utf-8",
    )

    target_mtime = 1_700_000_000
    for path in (
        alpha_stats_path,
        beta_stats_path,
        alpha_career_dir / "career_players.json",
        beta_career_dir / "career_players.json",
    ):
        os.utime(path, (target_mtime, target_mtime))

    player_loader = _reload_module("utils.player_loader")
    rating_display = _reload_module("utils.rating_display")

    alpha_players = player_loader.load_players_from_csv("data/players.csv")
    assert alpha_players[0].season_stats["h"] == 1
    assert alpha_players[0].career_stats["h"] == 11
    assert rating_display._select_distribution("ch", False) == [10]

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    beta_players = player_loader.load_players_from_csv("data/players.csv")
    assert beta_players[0].season_stats["h"] == 9
    assert beta_players[0].career_stats["h"] == 99
    assert rating_display._select_distribution("ch", False) == [90]


def test_phase5_injury_catalog_and_game_runner_caches_follow_active_league(
    tmp_path, monkeypatch
):
    path_utils, league_registry, alpha_data, beta_data = _setup_multi_league(
        tmp_path, monkeypatch
    )

    for data_dir, tag in ((alpha_data, "alpha"), (beta_data, "beta")):
        (data_dir / "injury_catalog.json").write_text(
            json.dumps(
                {
                    "metadata": {"name": f"{tag}-catalog"},
                    "triggers": {"collision": {"base_probability": 0.1}},
                    "injuries": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (data_dir / "teams.csv").write_text(
            (
                "team_id,name,city,abbreviation,division,stadium,primary_color,"
                "secondary_color,owner_id\n"
                f"T1,{tag.title()} Team,City,{tag[:3].upper()},East,Park,#111111,#222222,\n"
            ),
            encoding="utf-8",
        )

    injury_sim = importlib.import_module("services.injury_simulator")
    game_runner = _reload_module("playbalance.game_runner")

    alpha_catalog = injury_sim.load_injury_catalog()
    assert alpha_catalog["metadata"]["name"] == "alpha-catalog"

    game_runner.build_default_game_state = lambda *args, **kwargs: SimpleNamespace(
        team=None
    )
    game_runner.reorder_pitchers = lambda state, starter_id: None
    alpha_state = game_runner.prepare_team_state("T1")
    assert alpha_state.team is not None
    assert alpha_state.team.name == "Alpha Team"
    alpha_usage_state, alpha_day = game_runner._physics_usage_context("2026-04-01")
    assert alpha_day == 0

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None

    beta_catalog = injury_sim.load_injury_catalog()
    assert beta_catalog["metadata"]["name"] == "beta-catalog"
    beta_state = game_runner.prepare_team_state("T1")
    assert beta_state.team is not None
    assert beta_state.team.name == "Beta Team"
    beta_usage_state, beta_day = game_runner._physics_usage_context("2026-04-01")
    assert beta_day == 0
    assert beta_usage_state is not alpha_usage_state
