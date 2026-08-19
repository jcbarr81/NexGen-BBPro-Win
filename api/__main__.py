"""CLI entry point for the NexGen-BBPro FastAPI sidecar.

Electron spawns this process on startup. To avoid firewall prompts we always
bind ``127.0.0.1`` only. If ``--port 0`` (the default) is supplied we let the
OS pick a free port and print the selected port + the per-launch session
token as a single JSON line on stdout so the parent process can read it.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys

import uvicorn

# Use absolute imports so this module works in all three launch modes:
# (a) ``python -m api`` via the normal package path,
# (b) PyInstaller's frozen bundle where __main__ has no parent package,
# (c) direct ``python api/__main__.py`` invocation (rare, but handy).
from api.app import create_app
from api.security import issue_launch_token


def _pick_port(requested: int) -> int:
    if requested > 0:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="api", description="NexGen-BBPro sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = OS-assigned free port")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )
    parser.add_argument(
        "--print-handshake",
        action="store_true",
        help="Emit a single-line JSON handshake ({port, token}) on stdout before serving.",
    )
    args = parser.parse_args(argv)

    port = _pick_port(args.port)
    token = issue_launch_token()

    if args.print_handshake:
        sys.stdout.write(json.dumps({"port": port, "token": token}) + "\n")
        sys.stdout.flush()

    app = create_app()
    uvicorn.run(app, host=args.host, port=port, log_level=args.log_level)
    return 0


if __name__ == "__main__":  # pragma: no cover
    # S1-10: when this sidecar is a PyInstaller-frozen exe, the parallel-day
    # ProcessPoolExecutor (spawn) re-launches THIS executable for each worker.
    # Without freeze_support() a spawned worker would fall through to main() and
    # start another uvicorn server (and then spawn its own workers) — a fork
    # bomb. freeze_support() runs the worker task and exits instead; it is a
    # no-op in a normal ``python -m api`` (unfrozen) launch.
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
