#!/usr/bin/env python3
"""Post a "new version deployed" message to a Discord channel via webhook.

Run this as the final step of a deploy so the Discord server is told about the
new version. It reads the current version from the ``VERSION`` file and, by
default, uses the latest git commit subject as the change summary.

Discord webhook URL resolution (first match wins):
  1. ``--webhook`` argument
  2. ``NEXGEN_DISCORD_WEBHOOK_URL`` environment variable
  3. ``scripts/.discord_webhook`` file (git-ignored; a single line)

The webhook URL is a secret — anyone who has it can post to the channel — so it
is never committed. To create one: Discord → Server Settings → Integrations →
Webhooks → New Webhook → pick the channel → Copy Webhook URL.

Examples:
    python scripts/announce_release.py --dry-run
    python scripts/announce_release.py --message "Auto-assign preview + fill-gaps mode"
    NEXGEN_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \\
        python scripts/announce_release.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
WEBHOOK_FILE = ROOT / "scripts" / ".discord_webhook"
APP_URL = "https://nexgen-bbpro.web.app"


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def resolve_webhook(explicit: str | None) -> str | None:
    if explicit:
        return explicit.strip()
    env = (os.environ.get("NEXGEN_DISCORD_WEBHOOK_URL") or "").strip()
    if env:
        return env
    if WEBHOOK_FILE.exists():
        text = WEBHOOK_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


def latest_commit_subject() -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def build_message(version: str, summary: str) -> str:
    """The Discord message content (markdown)."""
    lines = [f"🚀 **NexGen-BBPro v{version} is live**"]
    if summary:
        lines.append("")
        lines.append(summary)
    lines.append("")
    lines.append(f"▶️ {APP_URL}")
    return "\n".join(lines)


def post_to_discord(webhook: str, content: str) -> None:
    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        # Discord returns 204 No Content on success.
        if resp.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {resp.status}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webhook", help="Discord webhook URL (overrides env/file).")
    parser.add_argument(
        "--message",
        help="Change summary to include (defaults to the latest git commit subject).",
    )
    parser.add_argument(
        "--version",
        help="Version string to announce (defaults to the VERSION file).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the message that would be posted; do not send it.",
    )
    return parser


def main(argv: list[str]) -> int:
    # Windows consoles default to cp1252 and choke on the emoji in a dry-run
    # print; the actual POST always encodes UTF-8, so this only affects output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    args = build_parser().parse_args(argv)

    version = (args.version or read_version()).strip()
    summary = args.message if args.message is not None else latest_commit_subject()
    # The commit subject often ends with "(7.20.0)" — redundant with the header.
    suffix = f"({version})"
    if summary.endswith(suffix):
        summary = summary[: -len(suffix)].strip()
    content = build_message(version, summary)

    if args.dry_run:
        print("--- Discord message (dry run, not sent) ---")
        print(content)
        return 0

    webhook = resolve_webhook(args.webhook)
    if not webhook:
        print(
            "No Discord webhook configured. Set NEXGEN_DISCORD_WEBHOOK_URL, pass "
            "--webhook, or create scripts/.discord_webhook.",
            file=sys.stderr,
        )
        return 2

    try:
        post_to_discord(webhook, content)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        print(f"Discord post failed: HTTP {exc.code} {body}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Discord post failed: {exc}", file=sys.stderr)
        return 1

    print(f"Announced v{version} to Discord.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
