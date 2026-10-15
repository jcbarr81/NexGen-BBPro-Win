# 8.0.0 switch: generation 6 and the full rating scale (operator runbook)

What moves a league to engine generation 6 and stored ratings on the full
1-99 scale (rating scale 2), how to turn it on, how to watch it, what to do
with a league that cannot move, and how to take one league back. Background:
owner decisions 5 and 15 (`docs/audits/2026-10-06-engine-ratings-audit/
DECISIONS.md`), `RATING_SCALE_DESIGN.md` section 6,
`services/rating_scale_migration.py`.

## 1. The settings (Cloud Run environment variables)

| Variable | Value | Effect |
|---|---|---|
| `NEXGEN_GENERATION6_SCALE2` | `1` (also `on`, `true`, `yes`) | THE switch. Off (unset) by default: nothing differs from 7.51. On: every league moves to scale 2 at its next rollover (or, if it reaches a new season without one, at that season's first game) and plays that season on generation 6; new leagues and their draft classes are generated on scale 2 and start on generation 6. |
| `NEXGEN_RESPREAD_LEAGUES` | `alpha-test` | Leagues whose bunched ratings are also re-spread when they move (decision 15). Comma-separated league ids. Read at the moment a league converts. |
| `NEXGEN_NEW_SEASON_ENGINE` | `5` or `4` | The existing hold. With the switch on, `5` gives new seasons generation 5 and converts nobody; `4` holds everyone on the legacy engine. A league already on scale 2 keeps scale 2 (it plays correctly on any generation). |

**Turning the switch off breaks every league with a season on generation
6**, and so does **routing traffic back to a revision without the switch**
(a previous revision, or one deployed without the variable): that revision
does not know generation 6, and those leagues' games fail on purpose (a
season never changes engine silently). To stop further moves, set
`NEXGEN_NEW_SEASON_ENGINE=5` on the current revision instead.

**Generation 7.** With `NEXGEN_GENERATION7` also on (it ships off; it is
read only while this switch is on), the same move lands a league on
engine generation 7, the ball-flight engine, instead of 6, and a league on
scale 2 already moves to 7 at its next season. Everything in this runbook
applies to it; its own settings, park data step and switch-off rule are in
`docs/generation7_switch_runbook.md`. Turning THIS switch off also turns
generation 7 off.

## 2. When a league moves, and what it looks like

- **At its rollover** (`services/league_rollover.py`, after the season
  archive, the contracts and the finances, BEFORE the offseason development
  step): the league is converted; its draft, free agency and offseason are
  then on the new scale, and its first offseason develops on it. Its next
  season starts on generation 6 (recorded when that season starts). For a
  league listed in `NEXGEN_RESPREAD_LEAGUES` the rollover takes the
  re-spread's population (the ACT players and the clubs' rotations, as the
  season ENDED) before the contract rollover, which turns many active
  players into free agents (alpha-test: 134 of 509), and hands it to the
  move.
- **At the first season game of a season nobody rolled into** (a league
  created before the switch and still in its first preseason, a season set
  up another way): the same conversion, then generation 6 is recorded.
- **Never mid-season.** alpha-test and stats-test finish their current
  seasons as they are and move at their next rollovers.
- **New leagues** created with the switch on are generated on scale 2 and
  start on generation 6. They have no conversion, no backup and no
  `rating_scale.json` (section 7).

One conversion, all under the league's players-file lock (`.players.csv.lock`
beside `players.csv`; every writer of the file takes it):

1. `players.csv` is read raw, checked (section 3), re-spread if listed, and
   every row stretched to scale 2;
2. the original is saved as `players.scale1.<season>.csv` (a league moved
   again in the same season after a rollback: `players.scale1.<season>.2.csv`);
3. the file is read again; if anything wrote it meanwhile, the move is
   planned again from what is there; then the whole file is replaced
   atomically in the scale 2 format (`height_in`, which builds before
   8.0.0 refuse to load);
4. open draft pools (`draft_pool_<year>.json/.csv`, year >= the season) are
   converted, originals kept as `draft_pool_<year>.scale1.<season>.<ext>`;
5. `rating_scale.json` gets a `converted` event: counts, every clip, the
   pools' clips (`draft_pool_clips`), the potentials raised
   (`potentials_raised_to_current`), the re-spread with its inputs, the
   headline numbers; the news feed gets the engine-and-scale item (and the
   re-spread item for a listed league). The same rollover then posts the
   offseason development item (how many players improved and declined,
   the biggest risers and declines with before and after).

Cloud Logging shows `[rating-scale] ... players converted to rating scale 2
for season <year> (generation 6, converted)`.

**Potentials.** The move raises every potential that sits below its
player's current rating up to that rating (about 2,800 per live league
without a re-spread: alpha-test 2,854, stats-test 2,799; 1,257 on
alpha-test with its re-spread, measured at a real rollover of a copy).
Potentials are hidden from owners; they feed development and CPU
decisions. A backup rollback restores them; an inverse rollback does not.

## 3. What refuses a move

A rating that would not fit the full scale is CLIPPED, and a clipped rating
plays differently for good:

- a **top clip** (the value would store above 99; the player is held at 99
  and plays WORSE) refuses the move for ANY player: a club's active roster,
  injured list, minor leagues, or a free agent;
- a **bottom clip** (raised to 1; the player plays slightly BETTER) refuses
  it for a player on an active or injured major-league roster (`ACT`, `DL`,
  `DL15`, `DL45`, `IR`), and for anyone in a league with no rosters; on a
  minor leaguer or a free agent it is allowed and logged;
- potentials cut at 99 never refuse (logged).

Also refused: an operator hold (section 6), a players file split evenly
between scales, an unreadable file.

A refused league plays its next season on generation 5 and scale 1. The
commissioner gets ONE `[commissioner]` news item per season naming each
blocking player and rating (for example "Sam Smith (P1234, DL15): Contact 92 would be
held at 99 and play worse"), `rating_scale.json` gets a `refused` event with
the full list (`blocking`), and the log shows `[rating-scale] ... NOT moved`.

Measured 2026-10-14 on the scratch copies under this rule: **neither live
league would be refused.** alpha-test has two bottom clips, both LOW-level
2026 draft picks (Eye 33 and Power 23 stored as 1; allowed, logged); with
its re-spread only the Power 23 is left. A real rollover of an alpha-test
copy (end of its 2026 playoffs, switch on, listed) gave exactly that: 12
ratings re-spread (hitters' Eye, fielding, arm, ground-ball and pull;
pitchers' control, movement, arm, endurance, hold, fielding and
ground-ball), 1,257 potentials raised, one allowed bottom clip (draft pick
D20260053, Power 23 stored as 1, LOW) and 59 potentials cut at 99; 1,080
players converted. stats-test has no clip. The repo's sample
`data/players.csv` would be refused (405 top clips; it has no rosters).
An allowed bottom clip on a draft pick can reach a major-league roster in
the same offseason through the CPU's roster fill; it plays a point better
than its stored 1 says, nothing else.

### A league that cannot move

It is offered the move again every season and refused again until the
blocking ratings change, so it does not resolve itself. Options, on the
league's durable copy with instances stopped (section 6's procedure):

1. **Bring the blocking ratings inside the scale.** Set each named rating
   to the limit the scale can hold (top: Contact 73, Power 66, Eye 59,
   fielding/arm 76 for hitters; control 73, movement 75, arm 80 for
   pitchers; bottom: Contact/Power 26, Eye 34, control 28, movement 30,
   fielding/arm 3, pitcher arm 7). Those players play exactly as they
   would have after a clip; everyone else is untouched. The league moves at
   its next rollover. Tell the commissioner which players changed.
2. **Release or retire the player** (commissioner tools) when he is a
   free agent or a fringe minor leaguer.
3. **Keep the league on scale 1**: add `"hold": {"reason": "kept on scale
   1"}` to its `rating_scale.json`. It stays on generation 5 and scale 1 and
   is not offered the move again. Generation 5 stays supported.

## 4. Before turning it on (checklist)

- The release that carries this is 8.0.0 and has been deployed with the
  switch OFF; no revision older than 8.0.0 is serving
  (`gcloud run revisions list --service <svc> --region <region>` and the
  traffic split). A 7.51.x instance cannot read a converted league.
- The development model (r8-develop) is in the same release: its rollover
  step must come right after this move (section 2), and training camp must
  no longer refuse scale 2 players.
- The display step (screens show the stored rating) is in the same release.
- Dry-run every live league on a scratch copy (never the live data):

      python -c "from services.rating_scale_migration import plan_move; p = plan_move(r'<copy>/data', respread=False); print(p.blocker); print([b['text'] for b in p.blocking])"

  For alpha-test (listed for the re-spread) use `respread=True` and print
  what the rollover will record:

      python -c "from services.rating_scale_migration import plan_move; p = plan_move(r'<copy>/data', respread=True); print(p.blocker); print([(r.group, r.key) for r in p.respread.moved]); print(sum(p.potentials_raised.values()), [(c.player_id, c.key) for c in p.allowed_clips])"

  Take the copy at the END of the season (after the playoffs, before the
  rollover). The rollover reads the re-spread's population from exactly
  those rosters, so this dry run reproduces it: the same 12 ratings, the
  same population, potentials raised and clips (checked on an alpha-test
  copy, 2026-10-14). A dry run on a copy taken AFTER the rollover's
  contracts reads the emptier rosters and can differ (on alpha-test Eye
  stops looking bunched: ACT sd ratio .582 -> .629, 11 ratings).

## 5. Turning it on in production

1. Pause the scheduler so no automatic sim runs during the revision swap:
   `gcloud scheduler jobs pause <job> --location <region>`.
2. Make sure no sim is running.
3. Set the variables (this creates a new revision):

       gcloud run services update <service> --region <region> \
         --update-env-vars NEXGEN_GENERATION6_SCALE2=1,NEXGEN_RESPREAD_LEAGUES=alpha-test

4. Wait until the new revision has 100% of traffic and the old one has no
   instance (`gcloud run revisions list`). During the overlap the old
   revision (switch off) must not play a season the new one put on
   generation 6; that is why the scheduler is paused.
5. Resume the scheduler.
6. Each league moves at its next rollover. Check its `rating_scale.json`,
   the news item and the log line.

**Watching.**

- `rating_scale.json` events: `converted` (a move; `recovered: true` when it
  is the record of a move that crashed before logging), `repaired`,
  `reformatted`, `draft_pools_converted`, `refused`, `rolled_back`,
  `generation_set`.
- `repaired`: scale 1 rows in a league that has moved (a stale copy pushed
  back, a restore, a save of players loaded before the move) were converted
  again at the next game, with the move's re-spread re-applied when it had
  one. Nothing played wrong (each row carries its own scale).
- A season game that fails with `MoveBusy` / "players file busy": another
  live process held the league's players-file lock for the few seconds the
  move waits. Nothing was decided; the next sim tries again. A lock left by
  a dead process is broken automatically (at once on the same host, after
  60 seconds otherwise).
- The working copy refuses to push a `players.csv` in the old format over
  one in the scale 2 format (`skip rating-scale overwrite` in the log).
- A league that will not load with `Missing required field: height_in
  (player <id> was written by a build older than 8.0.0 ...)`: an older
  build appended that row (a draft pick during a rollback or an overlap).
  Its ratings may be stretched values without their scale. Fix it from the
  draft pool and the draft results by hand (set `height_in`, and
  `rating_scale` 2 if the pool it came from was on scale 2), or remove the
  row and re-run the pick.

## 6. Taking one league back

Procedure (memory: "Restoring GCS under a live instance"): pause the
scheduler; make sure no instance is serving (a running instance pushes its
own working copy back over a restore minutes later); download the league's
data directory; run the script on the copy; upload; restart.

    python scripts/rating_scale_rollback.py --league-dir <copy>/leagues/<id>/data --dry-run
    python scripts/rating_scale_rollback.py --league-dir ... --mode inverse
    python scripts/rating_scale_rollback.py --league-dir ... --mode backup
    python scripts/rating_scale_rollback.py --league-dir ... --mode inverse --generation 5

- **`--mode inverse` is the normal choice after any play.** It un-stretches
  today's file in place: every change since the move is kept (injuries,
  trades, signings, development, draft picks); a value developed since comes
  back to the nearest whole engine point; a potential keeps its gap (the
  ones the move raised to the current rating are not lowered again). It does
  NOT undo a re-spread.
- **`--mode backup` loses everything done to players since the move.** It
  restores the file as it was at the move (and undoes a re-spread). Rosters,
  contracts, draft results and transactions written since keep pointing at
  players who are then missing from the file (draft picks) or back in their
  old state. Use it only when nothing has been played since the move, or
  when the move itself went wrong.
- Draft pools come back on scale 1 either way (from their backups, and any
  pool generated after the move through the inverse).
- The default season is the league's last real move; `--season` must name
  a season with a recorded move.
- The league is put on **hold** first (`"hold"` in `rating_scale.json`), so
  an interrupted rollback is never undone by the next game.
- The season's engine is left as recorded unless `--generation N` is given.
  Scale 1 plays correctly on generation 6, so a scale rollback needs nothing
  else. **A rollback before the season's first game** (a league moved at
  its rollover, rolled back in the offseason or preseason) makes that
  season generation 5: its generation is recorded at the first game, and a
  held league on scale 1 is given generation 5.
- **No double growth.** A rollback after the rollover's development step
  marks that offseason as developed (`development_last.json`,
  `scale1_camp_gains_withheld`): the scale 1 spring camp that follows marks
  players ready and reports the offseason's development, with no rating
  gains of its own. The next spring trains as usual. `--generation` rewrites the season's `rating_centers.json` entry and
  its `season_progress.json` witness (a witness that already belongs to a
  later season is left alone). A mid-season engine change changes how the
  rest of that season plays.

**Files to upload after a rollback:** `players.csv`, `rating_scale.json`,
every `draft_pool_<year>.json` and `draft_pool_<year>.csv` the script lists
(`draft_pools` in its output), and with `--generation` also
`rating_centers.json` and `season_progress.json`. The backups
(`players.scale1.*.csv`, `draft_pool_*.scale1.*`) are not changed.

**Telling the owners.** A rollback posts nothing. Post this (League
Admin, news) or send it to the owners, filled in:

> The rating-scale update has been taken back for now. Your league's
> ratings are shown on the earlier scale again, exactly as they play; no
> player's ability changed. [This season is played on the earlier game
> engine / This season stays on the newest engine.] Player development
> from this offseason stays, and spring training adds nothing on top of
> it this year. We will tell you before the league moves again.

**Lifting the hold.** Delete the `"hold"` key from `rating_scale.json`.
- On a league whose current season is recorded on **generation 6**, its
  NEXT GAME converts it again (it is a generation 6 season with scale 1
  rows): a fresh move, with a new backup (`players.scale1.<season>.2.csv`)
  and the re-spread list as it is set then. Its news is one short item,
  "ratings re-converted to the full 1-99 scale after a rollback" (plus the
  re-spread item if something was re-spread), not a second engine-and-scale
  announcement.
- Otherwise it moves at its next rollover (or next season start).

## 7. Leagues created with the switch on

They were generated on scale 2: no conversion record, no backup, no
`rating_scale.json`. There is nothing to restore; to put one on scale 1
use the inverse explicitly:

    python scripts/rating_scale_rollback.py --league-dir ... --mode inverse --season <year> --no-conversion-record

## 8. Rolling the binary back below 8.0.0

A 7.51.x build refuses a converted league's `players.csv` (measured on a
7.51.3 export: `ValueError: Missing required field: height` from
`load_players_from_csv`) and does not know generation 6 (its games raise
`unknown engine generation 6`). Before deploying an older binary:

1. Pause the scheduler; stop serving.
2. For every league with a `converted` event (and every league created on
   scale 2): roll back with `--mode inverse --generation 5` on its durable
   copy and upload the files listed above.
3. Deploy the older revision.

A league converted and NOT rolled back stays unreadable to the old build;
nothing is corrupted, but nobody can use it until 8.0.0 is back.
