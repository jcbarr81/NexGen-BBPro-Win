#!/usr/bin/env python3
"""Append one release note entry to release_notes_draft.md."""

from __future__ import annotations

import argparse
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAFT_NOTES_FILE = ROOT / "release_notes_draft.md"


def sanitize_ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def append_note(note: str) -> None:
    clean = sanitize_ascii(note.strip())
    if not clean:
        raise ValueError("Note text is empty")
    with DRAFT_NOTES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"- {clean}\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Add a draft release note entry.")
    parser.add_argument("note", help="Release note text to append")
    args = parser.parse_args(argv)
    append_note(args.note)
    print(f"Appended note to {DRAFT_NOTES_FILE.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
