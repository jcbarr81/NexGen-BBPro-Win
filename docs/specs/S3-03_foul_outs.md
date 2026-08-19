# S3-03 — Foul-Outs / Popups (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 park/environment track.

## Objective

Two missing out types:
1. **No foul putouts.** Foul territory only raises the foul-*strike* rate
   (`physics_sim/physics.py:878-885`), so a batter never fouls out to the
   catcher/corner infielders — parks with big foul territory don't convert that
   into outs.
2. **No infield-fly / popup class.** `classify_ball_type` (`physics.py:944`)
   buckets batted balls into only `gb / ld / fb` by launch angle; a very-high
   launch angle is still just "fb". There is no popup (IFFB) class despite an
   `iffb_pct` benchmark existing.

## Verified current state

- `physics.py:878-885` — foul territory scales `foul_rate` (more foul strikes)
  via `foul_territory_scale`; no catch roll on fouls.
- `physics.py:944-951` — `classify_ball_type(launch_angle, tuning)`:
  ```python
  if launch_angle < gb_cutoff: return "gb"   # bip_gb_cutoff 6.0
  if launch_angle < ld_cutoff: return "ld"   # bip_ld_cutoff 13.0
  return "fb"
  ```
  No high-angle popup branch.
- `park.foul_territory_scale` is already plumbed into the per-game context
  (`engine.py:4305`).
- `iffb_pct` benchmark exists in `data/MLB_avg/` but is unused by the harness.

## Acceptance criteria

1. High-launch-angle fly balls can be classified as **popups** (`pop` / IFFB)
   via a new cutoff, and popups are near-automatic outs (very low hit value)
   credited as putouts to the correct infield position.
2. A **foul-out catch roll** on high-launch-angle foul balls, scaled by
   `park.foul_territory_scale` (bigger foul territory → more foul-outs),
   crediting a putout to C / 1B / 3B by spray.
3. New **putouts-by-position** and **IFFB%** KPIs, gated vs benchmark.
4. Overall BABIP, K%, and batted-ball mix (GB/LD/FB) gates stay green — the
   popup class is carved out of the top of the FB bucket, so FB% shifts; retune
   `bip_*` cutoffs / hit values so league lines hold (`--strict`, seeds 1 & 2).

## Decisions (no open choices)

- **D1 — Popup = FB with launch angle above `bip_popup_cutoff`** (≈ 50°, new
  knob). `classify_ball_type` gains a `"pop"` return above the cutoff; the hit
  model treats `pop` like an automatic out (hit prob ≈ 0.02) unless dropped.
- **D2 — Foul-out is a post-foul roll**, not a new ball type. When a foul is
  generated (physics.py:878-885), roll `p_foulout = base * (foul_territory_scale
  ...)` gated to high-angle fouls; on success, record an out + putout instead of
  a foul strike. Keep it rare (real foul-outs are ~1-2% of PA).
- **D3 — Fielder credit** reuses the existing `_find_fielder` / `_fielding_line`
  putout machinery (`engine.py:1565+`): popup → nearest IF by spray; foul-out →
  C for pop-behind-plate, 1B/3B by spray.

## Files to change

| File | Change |
|---|---|
| `physics_sim/physics.py` | `classify_ball_type` popup branch (`bip_popup_cutoff`); foul-out catch roll in the foul path. |
| `physics_sim/config.py` | `bip_popup_cutoff`, `pop_hit_prob`, `foulout_base_rate`; retune `bip_*` + hit values. |
| `physics_sim/engine.py` | Route `pop`/foul-out to putout credit; emit IFFB in the batted-ball counters. |
| `scripts/physics_sim_season_kpis.py` | `iffb_pct` + putouts-by-position KPIs + tolerances. |
| `tests/test_foul_outs.py` (new) | High-LA ball → popup out; big-foul-territory park → more foul-outs; putout credited to the right position. |

## Verification gate

- KPI `--strict` green seeds 1 & 2 incl. `iffb_pct` + putouts-by-position;
  BABIP / K% / GB-LD-FB league gates unchanged (retuned).

## Non-goals

- Foul-ball baserunner advancement / tag-ups on fouls. Wall-ball / fan
  interference. Sun/lights drops. Popup "can of corn" fielder-choice drama.
