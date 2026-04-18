"""FastAPI application factory for the NexGen-BBPro sidecar."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils import path_utils

from .routers import (
    activity,
    admin,
    admin_league,
    ai_settings,
    auth,
    boxscore,
    change_request_export,
    change_requests,
    command_center,
    commissioner,
    dashboard,
    depth_chart,
    draft,
    exhibition,
    exports,
    finance,
    finance_queue,
    finance_stability,
    free_agency,
    help as help_router,
    history,
    hof,
    injuries,
    leaders,
    league_create,
    leagues,
    lineups,
    news,
    offseason,
    parks,
    players,
    playoffs,
    reassign,
    records,
    roster,
    schedule,
    season,
    standings,
    standings_league,
    stats,
    team_settings,
    teams,
    trades,
    training,
    tuning,
    validation,
)
from .schemas import HealthResponse
from .ws import sim as ws_sim


def _read_version() -> str:
    try:
        version_path = path_utils.get_base_dir() / "VERSION"
        return version_path.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def create_app() -> FastAPI:
    app = FastAPI(
        title="NexGen-BBPro Sidecar",
        version=_read_version(),
        description="Local HTTP/WebSocket API consumed by the Electron UI.",
    )

    # Electron dev server loads from http://localhost:5173 by default. We keep
    # CORS permissive for 127.0.0.1/localhost only; the sidecar never binds a
    # public interface, so this stays safe.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "app://nexgen-bbpro",  # Electron custom protocol (future)
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    def healthz() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=_read_version(),
            data_root=str(Path(path_utils.get_data_root())),
            active_league=path_utils.get_active_league_id(),
        )

    app.include_router(auth.router)
    app.include_router(leagues.router)
    app.include_router(teams.router)
    app.include_router(players.router)
    app.include_router(standings.router)
    app.include_router(standings_league.router)
    app.include_router(schedule.router)
    app.include_router(trades.router)
    app.include_router(draft.router)
    app.include_router(playoffs.router)
    app.include_router(finance.router)
    app.include_router(admin.router)
    app.include_router(season.router)
    app.include_router(training.router)
    app.include_router(team_settings.router)
    app.include_router(boxscore.router)
    app.include_router(activity.router)
    app.include_router(news.router)
    app.include_router(injuries.router)
    app.include_router(free_agency.router)
    app.include_router(leaders.router)
    app.include_router(stats.router)
    app.include_router(stats.team_router)
    app.include_router(history.router)
    app.include_router(commissioner.router)
    app.include_router(command_center.router)
    app.include_router(finance_queue.router)
    app.include_router(change_requests.router)
    app.include_router(change_request_export.router)
    app.include_router(hof.router)
    app.include_router(exports.router)
    app.include_router(ai_settings.router)
    app.include_router(records.router)
    app.include_router(help_router.router)
    app.include_router(tuning.router)
    app.include_router(league_create.router)
    app.include_router(league_create.admin_router)
    app.include_router(depth_chart.router)
    app.include_router(dashboard.router)
    app.include_router(roster.router)
    app.include_router(lineups.router)
    app.include_router(offseason.router)
    app.include_router(reassign.team_router)
    app.include_router(reassign.all_router)
    app.include_router(finance_stability.router)
    app.include_router(parks.router)
    app.include_router(validation.router)
    app.include_router(exhibition.router)
    app.include_router(admin_league.router)
    app.include_router(ws_sim.router)

    return app


app = create_app()
