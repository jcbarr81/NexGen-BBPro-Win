# Game replay data spec

Status: **stored record v1 shipped in 8.14.0**; play format (section 4) is a
draft for the 2D viewer. Backlog #74 in `docs/future_work.md` holds the plan
and the owner's decisions.

The goal is a viewer for real season and postseason games: a 2D field first,
then 3D with Mixamo-animated players (the approach of the football game's
viewer, `C:\dev\fbsim\gridiron-3d`), and eventually owners managing their own
games live. The same rule holds throughout: **the engine decides, the viewer
only shows.** Nothing in a replay feeds back into a game, and the engine is
never changed to make a replay look better.

## 1. Layers

1. **Stored record** (`nexgen.replay/1`, section 3): what the engine logged,
   saved beside each box score. Written once per game; never rewritten.
2. **Play format** (section 4): timed events per play, derived from the
   stored record by a converter. Can be regenerated whenever the converter
   improves, so it is not stored.
3. **Viewer plan**: per-frame positions and animation cues, built in the
   client from the play format (the football viewer's `choreograph` step).

A live game later would produce layer 2 directly from the running engine, so
the viewers never need to know whether a game is a replay.

## 2. Where it lives

- File: `boxscores/<season|playoffs>/<game id>.replay.json.gz`, beside
  `<game id>.html`. Gzipped JSON, about 12 KB per game (11-15 KB measured on calibration games).
- Written by `services/game_replay.py` (`build_replay`, `encode_replay`,
  `save_game_replay`). The game runner (`playbalance/game_runner.py`,
  `_attach_game_replay`) puts the encoded document in the game's meta under
  `replay_gz`; the season save (`api/routers/season.py`) and the playoff save
  (`playbalance/playoffs.py`) pop it and write it next to the box score.
- Served by `GET /boxscore/replay?path=<box score path>`: the decoded JSON,
  or 404 "No replay was kept for this game." for games before 8.14.0.
- Exhibitions are not kept. `NEXGEN_GAME_REPLAY=0` turns writing off.
- Deleting `boxscores/season` (the reset's purge option) deletes the replays
  with the box scores.

## 3. Stored record `nexgen.replay/1`

Floats are rounded to 2 decimals; keys with no value are omitted.

| Key | Contents |
| --- | --- |
| `schema` | `"nexgen.replay/1"` |
| `game` | `date`, `home`, `away`, `home_name`, `away_name`, `park`, `park_altitude_ft`, `seed`, `postseason`, `engine_generation` |
| `players` | `{player id: {name, bats, throws, pos}}` for everyone who appears |
| `lineups` | `{away, home: [[player id, position], ...]}` in batting order (DH included) |
| `substitutions` | the engine's `metadata.substitutions`: `{team, inning, role (PH/PR/DEF...), out, in, position, pitcher_id}` |
| `pitches` | the engine's `pitch_log`, one entry per pitch (plus one per intentional walk and per bunt), fields below |
| `bases` | `{entry index: {before, after, scored}}`: `before` / `after` are `[first, second, third]` player ids or null; `scored` lists the runners who scored on that entry's play |
| `fielded` | `{entry index: position}` the engine credited the out in play to, or charged the error on it to |
| `errors` | `[{i, source, pos, fielder, side}]` every error charged |
| `final` | `score`, `inning_runs`, `innings` |

`bases.after` is written when an entry's play ends a plate appearance or a
half-inning; for a pitch in the middle of a plate appearance it is the next
entry's `before`. A pinch runner shows as a change between one entry's
`after` and the next one's `before`.

### Pitch entry fields

- Pitch: `pitch_type`, `pitch_quality`, `velocity` (mph), `location` ([x, z]
  ft at the plate), `in_zone`, `called_in_zone`, `objective`, `intent`.
- Swing: `swing`, `contact`, `foul`, `in_play`, `outcome` (ball / strike /
  swinging_strike / foul / in_play / hbp / interference; `ibb` and `bunt`
  for those single entries).
- Batted ball: `exit_velo`, `launch_angle`, `spray_angle` (deg, + toward
  right field), `distance` (ft), `ball_type` (gb/ld/fb/pu), `hit_type`,
  `out_type`, `reached_on_error`.
- Context: `count` ("b-s" before the pitch), `pitch_count`, `pitcher_id`,
  `batter_id`, `tto`, `fatigue_penalty`.
- First entry of each plate appearance: `pa_start`, `inning`, `half`
  (`top`/`bottom`), `outs_before`, `bases_before` (bitmask 1/2/4),
  `bat_score_before`, `fld_score_before`.
- Results: `pa_result`, `strikeout`, `strikeout_type`, `k_reached`,
  `infield_hit`, `error_type`, `error_on`, `foul_out_fielder`, `injury`.
- Runners: `runner_event` ("+"-joined tokens: `sb2 sb3 sbh cs2 cs3 csh po1-3
  wp pb k_wp k_pb dp tp fc fc_home sac bunt_hit e_th ...`), `event_bases`,
  `event_outs`, `hit_adv` ([runner, from, to, error] rows, to 0 = out, 4 =
  scored), `go3`, `tag2`, `tag3`.

## 4. Play format (draft, for the 2D viewer)

One object per play, built by a converter from the stored record:

```json
{
  "i": 212, "inning": 7, "half": "bottom", "outs": 1,
  "count": "2-1", "batter": "P0123", "pitcher": "P0456",
  "bases_before": [null, "P0777", null], "bases_after": ["P0123", null, null],
  "events": [
    {"t": 0.00, "type": "release", "by": "P0456"},
    {"t": 0.42, "type": "plate", "x": 0.3, "z": 2.4, "call": "in_play"},
    {"t": 0.42, "type": "contact", "ev": 98.1, "la": 14.0, "spray": -12.0},
    {"t": 2.31, "type": "land", "x": -58.0, "y": 262.0},
    {"t": 3.40, "type": "field", "by": "LF", "x": -60.0, "y": 268.0},
    {"t": 4.60, "type": "throw", "from": "LF", "to": "home"},
    {"t": 4.65, "type": "arrive", "runner": "P0777", "base": "home"},
    {"t": 4.90, "type": "catch", "by": "C", "base": "home"}
  ],
  "result": {"text": "Single to left, runner scores", "runs": 1, "outs": 0}
}
```

- **Field frame:** feet, home plate at the origin, +y toward center field
  through second base, +x toward the first-base side (right field). This is
  the frame `physics_sim/ballflight.py` already uses (`_xy`).
  `playbalance/field_geometry.py` uses a rotated frame (x toward first, y
  toward third); the converter converts from it, not the other way around.
- **Timing** comes from what the engine already models: pitch flight =
  60.5 ft / velocity, hang time and descent from the ball-flight carry table
  (`ballflight.flight`, scaled so the carry matches the logged `distance`,
  which works for every engine generation), fielder reaction and speed from
  the `bb6_*` tuning, throws at `bb6_throw_speed`, runner home-to-first from
  `bb6_run_time`. The viewer may smooth paths but never changes who is safe
  or out.
- **Two viewing modes** (owner's choice): *Key pitch* shows only the pitch
  each plate appearance's result happened on, between scoreboard updates;
  *Every pitch* shows every pitch and every play. Both read the same plays.

## 5. Known gaps

- The engine logs where a fielder made the play only as a position, not a
  spot; the converter places it from the ball-flight model.
- Throws are logged only through their outcomes (`tag3`, `go3`, error
  tokens), not as a thrower-to-base chain; relays are inferred.
- Steals, pickoffs and wild pitches name the runner only through the
  `bases` trace (before/after), which is enough to animate them.
- No pitch release point, spin or movement; the viewer uses a standard
  release by handedness.
- Intentional walks and bunts are single entries without pitches.
