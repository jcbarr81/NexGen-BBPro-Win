"""Live simulation WebSocket.

Phase 5 iteration 1. We don't touch ``physics_sim/engine.py`` yet; instead
we call :func:`physics_sim.engine.simulate_matchup_from_files` to completion
in a worker thread (it's ~sub-second for a full game), then replay the
``pitch_log`` to the WebSocket client at a configurable pace.

Protocol (server → client):

* ``{type: "start", game_id, away, home, park?, total_pitches}``
* ``{type: "pitch", seq, total, data: <pitch_log_entry>}``
* ``{type: "final", totals, metadata}``
* ``{type: "error", message}``

Protocol (client → server):

* ``{type: "speed", ms: <int>}`` — delay between pitches, 0–2000ms
* ``{type: "pause"}`` / ``{type: "resume"}``
* ``{type: "skip"}`` — drain immediately, emit final

The client authenticates via the ``token`` query parameter and selects a
matchup via ``?away=<team>&home=<team>&seed=<int?>&speed=<ms>``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from physics_sim.engine import GameResult, simulate_matchup_from_files

from ..security import decode_token

router = APIRouter(tags=["sim"])
_LOGGER = logging.getLogger(__name__)

_DEFAULT_SPEED_MS = 250
_MAX_SPEED_MS = 2000
_MIN_SPEED_MS = 0


async def _send(ws: WebSocket, payload: Dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(payload, default=str))
    except Exception:
        # Client likely gone; let the outer loop handle disconnect.
        raise


@router.websocket("/ws/sim/{game_id}")
async def sim_socket(websocket: WebSocket, game_id: str) -> None:
    params = websocket.query_params
    token = params.get("token", "")
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    away = params.get("away", "").strip()
    home = params.get("home", "").strip()
    if not away or not home:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        seed: Optional[int] = int(params["seed"]) if params.get("seed") else None
    except ValueError:
        seed = None
    try:
        speed_ms = max(_MIN_SPEED_MS, min(_MAX_SPEED_MS, int(params.get("speed", _DEFAULT_SPEED_MS))))
    except ValueError:
        speed_ms = _DEFAULT_SPEED_MS

    await websocket.accept()

    # Shared playback state managed from the control task.
    state: Dict[str, Any] = {"speed_ms": speed_ms, "paused": False, "skipped": False}
    control_event = asyncio.Event()

    async def control_loop() -> None:
        try:
            while True:
                message = await websocket.receive_text()
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                mtype = payload.get("type")
                if mtype == "speed":
                    try:
                        state["speed_ms"] = max(
                            _MIN_SPEED_MS,
                            min(_MAX_SPEED_MS, int(payload.get("ms", _DEFAULT_SPEED_MS))),
                        )
                    except (TypeError, ValueError):
                        pass
                elif mtype == "pause":
                    state["paused"] = True
                elif mtype == "resume":
                    state["paused"] = False
                    control_event.set()
                elif mtype == "skip":
                    state["skipped"] = True
                    state["paused"] = False
                    control_event.set()
        except WebSocketDisconnect:
            state["skipped"] = True
            state["closed"] = True
            control_event.set()
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("sim control loop error: %s", exc)

    control_task = asyncio.create_task(control_loop())

    try:
        # Run the (synchronous) simulator in a worker thread so we don't block
        # the event loop -- even though the sim is fast, uvicorn workers still
        # benefit from yielding here.
        try:
            result: GameResult = await asyncio.to_thread(
                simulate_matchup_from_files,
                away_team=away,
                home_team=home,
                seed=seed,
            )
        except Exception as exc:
            await _send(
                websocket,
                {"type": "error", "message": f"Simulation failed: {exc}"},
            )
            return

        pitch_log = list(result.pitch_log or [])
        total = len(pitch_log)
        metadata = result.metadata or {}
        await _send(
            websocket,
            {
                "type": "start",
                "game_id": game_id,
                "away": away,
                "home": home,
                "park": metadata.get("park_name"),
                "total_pitches": total,
            },
        )

        for idx, entry in enumerate(pitch_log):
            # Pause loop: wait until either resumed or skipped.
            while state.get("paused") and not state.get("skipped") and not state.get("closed"):
                control_event.clear()
                try:
                    await control_event.wait()
                except asyncio.CancelledError:
                    return

            if state.get("closed"):
                return

            try:
                await _send(
                    websocket,
                    {
                        "type": "pitch",
                        "seq": idx + 1,
                        "total": total,
                        "data": entry,
                    },
                )
            except Exception:
                return

            if state.get("skipped"):
                continue

            delay = max(0, state.get("speed_ms", _DEFAULT_SPEED_MS)) / 1000
            if delay > 0:
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return

        try:
            await _send(
                websocket,
                {
                    "type": "final",
                    "totals": result.totals,
                    "metadata": metadata,
                },
            )
        except Exception:
            return
    finally:
        control_task.cancel()
        try:
            await control_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await websocket.close()
        except Exception:
            pass
