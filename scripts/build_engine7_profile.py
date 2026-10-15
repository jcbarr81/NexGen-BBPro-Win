"""Build engine generation 7's profile from its stages (Release 6b).

``physics_sim/profiles/engine_7.json`` (and its harness copy
``scripts/kpi_profiles/r7.json``) is generation 6's profile with each build
stage's file laid over it in ``R7_STAGES`` order: a stage may re-value a key
an earlier one (or generation 6) set, in place, and adds its own keys after.
Every value can so be traced to the stage that set it; tests/test_r7_tools_
generation.py checks the files equal this build.

    python scripts/build_engine7_profile.py [--check] [--through STAGE]

``--through`` builds the profile of the stages up to and including STAGE
(written to stdout, for measuring a stage).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROFILES = REPO / "scripts" / "kpi_profiles"
REGISTRY_6 = REPO / "physics_sim" / "profiles" / "engine_6.json"
REGISTRY_7 = REPO / "physics_sim" / "profiles" / "engine_7.json"
HARNESS_COPY = PROFILES / "r7.json"

# The stages, in build order (RELEASE6_PLAN section 4, 6b).
R7_STAGES: tuple[str, ...] = (
    "carry",  # 1. carry with drag, five-point fences, altitude
    "kernel",  # 2. the exit-velocity / launch-angle kernel, Statcast classes
    "fielding",  # 3. the fielding play model, hit types from landing spots
    "foulout",  # 4. foul-outs
    "spray",  # 5. spray widening, pulled air balls hit harder
    "pitcher_gb",  # 6. the pitcher's ground-ball identity
    "refit",  # 7. scripted re-fits: tag-up race, range slopes, Power top
    "retune",  # 8. the first joint retune (level, K / BB, pitcher term)
    "parks",  # owner decisions 18 / 20: each park's HR by batter side
)


def stage_path(stage: str) -> Path:
    return PROFILES / f"r7_{stage}.json"


def build(through: str | None = None) -> dict:
    profile = json.loads(REGISTRY_6.read_text(encoding="utf-8"))
    for stage in R7_STAGES:
        layer = json.loads(stage_path(stage).read_text(encoding="utf-8"))
        for key, value in layer.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                profile[key] = {**profile[key], **value}
            else:
                profile[key] = value
        if stage == through:
            break
    return profile


def render(profile: dict) -> str:
    return json.dumps(profile, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--through", default=None, choices=R7_STAGES)
    args = parser.parse_args()
    if args.through:
        sys.stdout.write(render(build(args.through)))
        return 0
    text = render(build())
    if args.check:
        stale = [
            path for path in (REGISTRY_7, HARNESS_COPY)
            if path.read_text(encoding="utf-8").replace("\r\n", "\n") != text
        ]
        for path in stale:
            print(f"{path} is out of date")
        return 1 if stale else 0
    for path in (REGISTRY_7, HARNESS_COPY):
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
