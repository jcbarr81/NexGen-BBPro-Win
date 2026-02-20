"""Inspect and optionally run legacy-to-multi-league migration checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.league_migration import (
    inspect_layout,
    migrate_legacy_layout_if_needed,
    restore_pre_multi_league_layout,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect league storage layout and optionally run migration.",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run legacy migration if needed before printing layout diagnostics.",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore pre-migration layout from a migration backup zip.",
    )
    parser.add_argument(
        "--backup-path",
        default="",
        help=(
            "Optional explicit migration backup zip path for --restore. "
            "When omitted, marker/most-recent backup discovery is used."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow --restore to overwrite existing files in the data root.",
    )
    parser.add_argument(
        "--data-root",
        default="",
        help="Optional explicit data-root path override.",
    )
    args = parser.parse_args(argv)
    if args.migrate and args.restore:
        parser.error("--migrate and --restore are mutually exclusive.")

    data_root = Path(args.data_root).resolve() if args.data_root else None

    if args.migrate:
        result = migrate_legacy_layout_if_needed(data_root=data_root)
        print(json.dumps(result.to_dict(), indent=2))
    elif args.restore:
        backup_path = Path(args.backup_path).resolve() if args.backup_path else None
        result = restore_pre_multi_league_layout(
            backup_path=backup_path,
            data_root=data_root,
            force=args.force,
        )
        print(json.dumps(result.to_dict(), indent=2))

    snapshot = inspect_layout(data_root=data_root)
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
