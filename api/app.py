"""FastAPI application factory for the NexGen-BBPro sidecar."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from utils import path_utils


class LeagueContextMiddleware:
    """Bind each request to a league via a ContextVar that the route handler sees.

    Cloud multi-tenant: the SPA sends the selected league in the ``X-League-Id``
    header (``?__league=`` query param also honored, e.g. for curl through proxies
    that strip custom headers). When it names a real, existing league, that league
    overrides the process-global ``active_league.txt`` pointer for the duration of
    the request, so concurrent users can operate in different leagues at once.
    No header/param (Electron / single-tenant) → no-op; the global pointer is used.

    Implemented as pure ASGI (not BaseHTTPMiddleware) so the ContextVar set here
    actually propagates into the route handler's task.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        league = None
        for key, value in scope.get("headers") or []:
            if key == b"x-league-id":
                league = value.decode("latin-1").strip()
                break
        if not league:
            params = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            vals = params.get("__league")
            if vals:
                league = vals[0].strip()
        token = None
        if league:
            try:
                if path_utils.get_active_league_dir(league_id=league) is not None:
                    token = path_utils.set_request_league(league)
            except Exception:
                token = None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                path_utils.reset_request_league(token)


def _configure_logging() -> None:
    """Route every sidecar log to a file under the user data dir.

    Packaged builds have no console attached, so without this we lose every
    traceback. The log file becomes the go-to surface for "why did the
    sidecar return a 500?" questions.
    """

    log_dir = Path(path_utils.get_data_root()) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            log_dir / "sidecar.log", encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        root = logging.getLogger()
        # Avoid piling duplicate handlers on reload.
        if not any(
            isinstance(h, logging.FileHandler)
            and Path(h.baseFilename).name == "sidecar.log"
            for h in root.handlers
        ):
            root.addHandler(handler)
        root.setLevel(logging.INFO)
    except Exception:
        # Logging setup must never crash the sidecar on launch.
        pass

from .routers import (
    account,
    activity,
    admin,
    admin_league,
    ai_settings,
    all_star,
    auth,
    awards,
    boxscore,
    command_center,
    commissioner,
    contracts,
    dashboard,
    depth_chart,
    discovery,
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
    invites,
    join_requests,
    leaders,
    league_create,
    leagues,
    lineups,
    news,
    notifications,
    offseason,
    platform_admin,
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
from . import working_copy


def _read_version() -> str:
    try:
        version_path = path_utils.get_base_dir() / "VERSION"
        return version_path.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def create_app() -> FastAPI:
    _configure_logging()

    app = FastAPI(
        title="NexGen-BBPro Sidecar",
        version=_read_version(),
        description="Local HTTP/WebSocket API consumed by the Electron UI.",
    )

    # Catch-all exception handler. FastAPI's default returns plain-text
    # "Internal Server Error" for any exception not caught by a route's
    # own try/except — which makes debugging packaged builds miserable.
    # This handler logs the full traceback to sidecar.log AND returns it
    # in the JSON body so the Electron UI can surface the real cause.
    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        tb = traceback.format_exc()
        logging.getLogger("nexgen.sidecar").error(
            "Unhandled exception: %s\n%s", exc, tb
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "message": str(exc) or exc.__class__.__name__,
                    "traceback": tb,
                }
            },
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

    # --- Cloud working-copy sync (no-op unless NEXGEN_WORKING_COPY=1) ---
    # Pull the durable GCS-backed data onto fast local disk at startup, and
    # flush changed files back after every mutating request. See working_copy.py.
    @app.on_event("startup")
    def _firebase_init() -> None:
        from api import firebase_auth

        try:
            firebase_auth.init_firebase()
        except Exception:
            logging.getLogger("nexgen.firebase").exception(
                "firebase init failed"
            )

    @app.on_event("startup")
    def _assets_check() -> None:
        # Confirm the avatar templates were bundled (they're recolored at runtime;
        # if missing, avatar generation silently produces nothing). print() so it
        # shows in Cloud Run logs (app-logger INFO is suppressed there).
        try:
            tmpl = path_utils.get_base_dir() / "images" / "avatars" / "Template"
            n = len(list(tmpl.rglob("*.png"))) if tmpl.is_dir() else 0
            print(
                f"[assets] avatar templates dir={tmpl} exists={tmpl.is_dir()} png_count={n}",
                flush=True,
            )
        except Exception as exc:
            print(f"[assets] template check failed: {exc}", flush=True)

    @app.on_event("startup")
    def _working_copy_pull() -> None:
        if working_copy.is_enabled():
            try:
                working_copy.bulk_pull()
            except Exception:
                logging.getLogger("nexgen.working_copy").exception(
                    "working-copy startup pull failed"
                )

    @app.middleware("http")
    async def _working_copy_persist(request: Request, call_next):
        response = await call_next(request)
        if working_copy.is_enabled() and request.method in {
            "POST", "PUT", "PATCH", "DELETE",
        }:
            try:
                from starlette.concurrency import run_in_threadpool

                # Capture the request's league here (while the request-scoped
                # ContextVar is guaranteed bound) and hand it to the push so it
                # can scope its walk to that league's dir + root-level files
                # instead of rglob-ing the entire multi-league data root.
                await run_in_threadpool(
                    working_copy.push_changes,
                    path_utils.get_request_league(),
                )
            except Exception:
                logging.getLogger("nexgen.working_copy").exception(
                    "working-copy push failed"
                )
        return response

    # --- Per-request league context (cloud multi-tenant) ---
    # Added as a PURE-ASGI middleware (see LeagueContextMiddleware) rather than
    # @app.middleware/BaseHTTPMiddleware, because the latter runs the route
    # handler in a child task and a ContextVar set in it would NOT reach the
    # endpoint. Outermost so the league is bound before anything downstream.
    app.add_middleware(LeagueContextMiddleware)

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    def healthz() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=_read_version(),
            data_root=str(Path(path_utils.get_data_root())),
            active_league=path_utils.get_active_league_id(),
        )

    # App-specific health alias. ``/healthz`` is a conventional infrastructure
    # path that proxies, security appliances, and load balancers frequently
    # intercept (returning their own 404 with no CORS headers, which a browser
    # reports as "Failed to fetch"). The Electron/web UI hits this alias instead
    # so the startup gate isn't at the mercy of such intermediaries. ``/healthz``
    # is kept for Cloud Run's own platform health checks.
    @app.get("/meta/app-status", response_model=HealthResponse, tags=["meta"])
    def app_status() -> HealthResponse:
        return healthz()

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
    app.include_router(contracts.router)
    app.include_router(awards.router)
    app.include_router(all_star.router)
    app.include_router(admin.router)
    app.include_router(season.router)
    app.include_router(training.router)
    app.include_router(training.player_router)
    app.include_router(training.league_router)
    app.include_router(team_settings.router)
    app.include_router(boxscore.router)
    app.include_router(activity.router)
    app.include_router(news.router)
    app.include_router(notifications.router)
    app.include_router(injuries.router)
    app.include_router(free_agency.router)
    app.include_router(leaders.router)
    app.include_router(stats.router)
    app.include_router(stats.team_router)
    app.include_router(history.router)
    app.include_router(commissioner.router)
    app.include_router(command_center.router)
    app.include_router(finance_queue.router)
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
    app.include_router(account.router)
    app.include_router(discovery.router)
    app.include_router(platform_admin.router)
    app.include_router(invites.router)
    app.include_router(join_requests.router)
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

    # Serve the built React UI from the same origin, if present. The cloud image
    # copies the Vite bundle to <base>/desktop/dist; pure-API/dev runs omit it.
    # Mounted LAST so every API route above takes precedence; the SPA uses
    # HashRouter, so the server only ever serves "/" and static assets.
    try:
        from fastapi.staticfiles import StaticFiles

        ui_dir = path_utils.get_base_dir() / "desktop" / "dist"
        if ui_dir.is_dir():
            app.mount(
                "/", StaticFiles(directory=str(ui_dir), html=True), name="ui"
            )
    except Exception:
        logging.getLogger("nexgen.sidecar").exception(
            "Failed to mount UI static files"
        )

    return app


app = create_app()
