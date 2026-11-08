# Game replay data spec

Status: **stored record v1 shipped in 8.14.0**; play format (section 4) and
the 2D viewer shipped in 8.15.0. Backlog #74 in `docs/future_work.md` holds the plan
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

## 4. Play format `nexgen.plays/1` (8.15.0)

Built from the stored record on every request by `services/replay_plays.py`
(`build_plays`) and served by `GET /boxscore/replay/plays?path=<box score>`
(gzipped when the browser accepts it: about 250 KB of JSON, 40 KB on the
wire). Never stored, so a better converter re-renders every old game.

Document: `schema`, `game`, `players`, `lineups`, `final`, `field` (the
park's five fence distances and wall heights at -45/-22.5/0/22.5/45 degrees,
the bases, the rubber, each position's standing spot) and `plays`, one per
stored entry:

| Key | Contents |
| --- | --- |
| `i`, `inning`, `half`, `batting` | which entry, when, which side bats |
| `outs`, `outs_after`, `count`, `count_after` | the scoreboard before and after |
| `batter`, `pitcher`, `bases_before`, `bases_after`, `scored`, `score` | from the record; `score` is after the play |
| `pa_end`, `key` | the plate appearance ended here; something happened (a result, a runner moved, an out, a run): the *Key plays* mode shows these |
| `text` | one line, e.g. "Pat Lee grounds into a double play, 6-4-3" |
| `dur` | seconds the play runs (its last move plus a 0.6 s hold) |
| `pitch` | type, mph, location, call, swing |
| `ball` | `[t, x, y, z]` points (sampled every ~0.1 s in flight) |
| `fielders` | `{position: [[t, x, y], ...]}` for fielders who move; the rest stand at `field.positions` |
| `runners` | `{who, role (batter/runner), from, to (1-3, 4 scored, 0 out), out_at, replaced, path}` |
| `cues` | `{t, type, ...}`: pitch, swing, contact, catch, throw, field, tag, out, safe, score, home_run, strikeout, error, past (wild pitch / passed ball), balk |
| `throws` | `{t, base, by}`: when each throw is caught, where |

- **Field frame:** feet, home plate at the origin, +y toward center field
  through second base, +x toward first base / right field: the frame of
  `physics_sim/ballflight.py` (`_xy`).
- **Timing:** pitch flight = 54 ft / velocity; a batted ball's hang time is
  the carry table's (`ballflight.flight`) scaled so the carry matches the
  logged `distance` (any engine generation); a ground ball rolls at the
  fielding model's roll speed and is fielded where the play model's charge
  puts the credited fielder; runners 27 ft/s, the batter 4.3 s to first,
  throws 105-125 ft/s. These are animation speeds, not the engine's.
- **What the engine decided is never changed.** Who is out, who is safe,
  where every runner ends and who scores come from the record; the timing
  bends where it must so an out's throw beats the runner and a safe runner
  beats the throw. `check_plays` checks exactly that, plus that the outs and
  runs add up to each half-inning and the final score
  (`scripts/check_replay_plays.py` runs it over calibration games;
  `tests/test_replay_plays.py` also checks the checker catches broken plays).
- **Two viewing modes** (owner's choice): *Key plays* shows the plays with
  `key` set; *Every pitch* shows all of them. The 2D viewer is
  `/game-viewer?path=<box score>` (`desktop/src/pages/GameViewerPage.tsx`,
  `components/game-viewer/FieldCanvas.tsx`, `lib/game-viewer.ts`); the 3D
  viewer will read the same plays.

## 5. Known gaps

- The engine logs where a fielder made the play only as a position, not a
  spot; the converter places it from the ball-flight model.
- A pinch runner or an injured batter's replacement shows up only in the
  bases trace; the play's runner finishes as the replacement (`replaced`
  names who he stood in for).
- Throws are logged only through their outcomes (`tag3`, `go3`, error
  tokens), not as a thrower-to-base chain; relays are inferred.
- Steals, pickoffs and wild pitches name the runner only through the
  `bases` trace (before/after), which is enough to animate them.
- No pitch release point, spin or movement; the viewer uses a standard
  release by handedness.
- Intentional walks and bunts are single entries without pitches.
