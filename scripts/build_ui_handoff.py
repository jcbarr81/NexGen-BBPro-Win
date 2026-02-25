#!/usr/bin/env python3
"""Build developer-only UI graphics handoff bundles."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.graphics_style import build_ui_prompt, load_manifest


UI_DIR = ROOT / "ui"
DEFAULT_OUT_DIR = ROOT / "reports" / "ui_handoff"
TARGET_BASES = {"QDialog", "QMainWindow", "QWidget"}


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _iter_ui_classes() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8-sig")
            module = ast.parse(text)
        except Exception:
            continue
        lines = text.splitlines()
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {_base_name(base) for base in node.bases}
            if not (base_names & TARGET_BASES):
                continue
            start = int(getattr(node, "lineno", 1))
            end = int(getattr(node, "end_lineno", start))
            snippet = "\n".join(lines[start - 1 : end]).rstrip() + "\n"
            rel_path = path.relative_to(ROOT).as_posix()
            screen_id = _slug(f"{path.stem}_{node.name}")
            records.append(
                {
                    "screen_id": screen_id,
                    "class_name": node.name,
                    "relative_path": rel_path,
                    "line_start": start,
                    "line_end": end,
                    "base_classes": sorted(base_names),
                    "source_snippet": snippet,
                    "source_full": text if text.endswith("\n") else text + "\n",
                }
            )
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export screen-level UI graphics handoff bundles for developers.",
    )
    parser.add_argument(
        "--manifest",
        default="config/graphics_style_manifest.json",
        help="Path to graphics style manifest.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for handoff bundles.",
    )
    parser.add_argument(
        "--screen",
        action="append",
        default=[],
        help=(
            "Optional screen filter. Matches screen_id/class name/path token. "
            "Can be provided multiple times."
        ),
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Write full source file into source.py instead of class snippet.",
    )
    return parser


def _matches_filter(record: dict[str, Any], filters: list[str]) -> bool:
    if not filters:
        return True
    haystack = " ".join(
        [
            str(record["screen_id"]),
            str(record["class_name"]),
            str(record["relative_path"]),
        ]
    ).lower()
    return any(token in haystack for token in filters)


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    filters = [str(token).strip().lower() for token in args.screen if str(token).strip()]
    records = [item for item in _iter_ui_classes() if _matches_filter(item, filters)]

    exported: list[dict[str, Any]] = []
    for record in records:
        bundle_dir = out_dir / str(record["screen_id"])
        bundle_dir.mkdir(parents=True, exist_ok=True)

        screenshot_placeholder = f"screens/{record['screen_id']}.png"
        prompt_payload = {
            "screen_id": record["screen_id"],
            "class_name": record["class_name"],
            "relative_path": record["relative_path"],
            "line_start": record["line_start"],
            "line_end": record["line_end"],
            "screenshot_path": screenshot_placeholder,
        }
        prompt = build_ui_prompt(prompt_payload, manifest)

        metadata = {
            "screen_id": record["screen_id"],
            "class_name": record["class_name"],
            "relative_path": record["relative_path"],
            "line_start": record["line_start"],
            "line_end": record["line_end"],
            "base_classes": record["base_classes"],
            "screenshot_path": screenshot_placeholder,
            "developer_only": True,
        }

        (bundle_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        source_body = record["source_full"] if args.include_source else record["source_snippet"]
        (bundle_dir / "source.py").write_text(source_body, encoding="utf-8")
        (bundle_dir / "screenshot_path.txt").write_text(
            screenshot_placeholder + "\n",
            encoding="utf-8",
        )

        prompt_md = "\n".join(
            [
                f"# UI Graphics Prompt - {record['screen_id']}",
                "",
                "Developer-only handoff artifact for UI redesign iteration.",
                "",
                "```text",
                prompt,
                "```",
                "",
            ]
        )
        (bundle_dir / "prompt.md").write_text(prompt_md, encoding="utf-8")
        exported.append(metadata)

    summary = {
        "status": "pass",
        "developer_only": True,
        "out_dir": str(out_dir),
        "count": len(exported),
        "screens": exported,
    }
    (out_dir / "index.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Exported {len(exported)} handoff bundles to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
