"""Rebuild ``physics_sim/carry_table.json`` (Release 6b, ``carry_model``).

The table is the drag-and-lift trajectory of ``physics_sim.ballflight``
precomputed on its grid (2 mph x 1 degree; sea-level and Coors air), so a
game never integrates a trajectory. Run after changing the trajectory or
the grid; ``tests/test_r7_carry.py`` checks that the file matches the
integrator.

    python scripts/build_carry_table.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from physics_sim.ballflight import CARRY_TABLE_FILE, build_carry_table  # noqa: E402


def render(payload: dict) -> str:
    """One row of the grid per line, so a diff of the file is readable."""
    lines = ["{"]
    lines.append(f'  "version": {payload["version"]},')
    lines.append(f'  "exit_velo": {json.dumps(payload["exit_velo"])},')
    lines.append(f'  "launch_angle": {json.dumps(payload["launch_angle"])},')
    lines.append('  "layers": [')
    for n, layer in enumerate(payload["layers"]):
        lines.append("    {")
        lines.append(f'      "density": {json.dumps(layer["density"])},')
        for k, name in enumerate(("carry", "hang", "descent")):
            rows = layer[name]
            lines.append(f'      "{name}": [')
            for r, row in enumerate(rows):
                sep = "," if r < len(rows) - 1 else ""
                lines.append(f"        {json.dumps(row)}{sep}")
            lines.append("      ]" + ("," if k < 2 else ""))
        lines.append("    }" + ("," if n < len(payload["layers"]) - 1 else ""))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if the file differs from a fresh build; write nothing.",
    )
    args = parser.parse_args()
    text = render(build_carry_table())
    if args.check:
        current = CARRY_TABLE_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != text:
            print(f"{CARRY_TABLE_FILE} is out of date")
            return 1
        print(f"{CARRY_TABLE_FILE} is up to date")
        return 0
    CARRY_TABLE_FILE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {CARRY_TABLE_FILE} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
