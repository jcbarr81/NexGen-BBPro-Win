# S3-17 — Dedicated Catcher Framing / Blocking Skill (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 Manager-depth track. Note: the plan's anchor
> `engine.py:1617-1628` is **stale** (that range is `_advance_on_error` /
> `_advance_on_air_out`); catcher receiving currently rides the generic fielding
> (`fa`) rating with no dedicated skill.

## Objective

Catcher defense behind the plate is undifferentiated — a great pitch-framer and
a bad one convert borderline pitches identically, and blocking (wild pitch /
passed ball prevention) uses generic fielding. Add a **framing** effect on
called strikes for borderline pitches and a **blocking** effect on WP/PB,
derived from the catcher's ratings, so an elite receiver is a real asset.

## Verified current state

- No `frame`/`framing`/`block` term in the engine (verify with a grep of
  `physics_sim/engine.py`).
- Called-strike / ball resolution for a taken pitch happens in the pitch-outcome
  path (search where a taken pitch is scored strike vs ball — the zone/borderline
  logic). This is the framing hook.
- Wild pitch / passed ball generation (search `wild_pitch` / `passed_ball` /
  `_wp` / `_pb`) is the blocking hook.
- Catcher identity: the defensive catcher is resolvable from the lineup/positions
  (primary_position "C"); ratings available include `fa`/`arm` and possibly a
  glove/receiving rating — confirm the exact rating to key framing on
  (default: `fa`, optionally a dedicated `catcher_frame` if the model has one).

## Acceptance criteria

1. **Framing:** borderline taken pitches (near the edge of the zone) get a small
   called-strike probability bump/penalty scaled by the catcher's framing
   rating; centered-zone and clearly-out pitches are unaffected.
2. **Blocking:** WP/PB probability on pitches in the dirt scales inversely with
   the catcher's blocking rating.
3. Net league effect is small and centered: called-strike% and WP+PB/game league
   means stay within the KPI band (`--strict`, seeds 1 & 2) — a good framer gains
   strikes at a bad framer's expense (redistribution), not league inflation.
4. Over a season, per-catcher framing runs / WP+PB-allowed spread out (elite vs
   poor receivers separate).

## Decisions (no open choices)

- **D1 — Framing applies ONLY to borderline pitches.** Gate the framing
  adjustment to pitches within a small band of the zone edge (new knob
  `frame_edge_band`); apply `called_strike_prob *= 1 + frame_scale *
  (catcher_frame - 50)/50`, clamped. No effect on obvious balls/strikes.
- **D2 — Blocking scales WP/PB.** `wp_pb_prob *= 1 - block_scale *
  (catcher_block - 50)/50`, clamped ≥ 0. Key on the catcher receiving rating.
- **D3 — Rating source.** If the model has a dedicated catcher receiving rating,
  use it; else derive framing/blocking from `fa` (with a documented mapping) so
  this doesn't require a data migration. New knobs `frame_scale`, `block_scale`,
  `frame_edge_band`.

## Files to change

| File | Change |
|---|---|
| `physics_sim/engine.py` | Framing bump at the called-strike decision (borderline only); blocking factor at WP/PB generation; resolve the defensive catcher + rating. |
| `physics_sim/config.py` | `frame_scale`, `block_scale`, `frame_edge_band`. |
| `scripts/physics_sim_season_kpis.py` | Confirm called-strike% + WP/PB bands; optional per-catcher framing-runs spread sanity. |
| `tests/test_catcher_framing.py` (new) | Elite framer > poor framer called-strike% on identical borderline pitches; centered pitches unchanged; elite blocker allows fewer WP/PB. |

## Verification gate

- Unit tests above. KPI `--strict` green seeds 1 & 2 — called-strike% and
  WP+PB/game league means unchanged; per-catcher spread up.

## Non-goals

- Pitch-tracking / catcher target modeling. Umpire-specific zones. Catcher game-
  calling / pitch-sequencing intelligence. A ratings-schema migration for a new
  dedicated catcher skill (derive from `fa` unless one already exists).
