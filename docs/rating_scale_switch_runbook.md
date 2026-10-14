# 8.0.0 switch: generation 6 and the full rating scale (operator runbook)

What moves a league to engine generation 6 and stored ratings on the full
1-99 scale (rating scale 2), how to turn it on, how to watch it, how to hold
it, and how to take one league back. Background: owner decisions 5 and 15
(`docs/audits/2026-10-06-engine-ratings-audit/DECISIONS.md`),
`RATING_SCALE_DESIGN.md` section 6, `services/rating_scale_migration.py`.

## 1. The settings (Cloud Run environment variables)

| Variable | Value | Effect |
|---|---|---|
| `NEXGEN_GENERATION6_SCALE2` | `1` (also `on`, `true`, `yes`) | THE switch. Off (unset) by default: nothing differs from 7.51. On: every league moves to generation 6 and scale 2 when its next season starts; new leagues and their draft classes are generated on scale 2 and start on generation 6. |
| `NEXGEN_RESPREAD_LEAGUES` | `alpha-test` | Leagues whose bunched ratings are also re-spread when they move (decision 15). Comma-separated league ids. Read only at the moment a league converts. |
| `NEXGEN_NEW_SEASON_ENGINE` | `5` or `4` | The existing hold. With the switch on, `5` gives new seasons generation 5 and converts nobody; `4` holds everyone on the legacy engine. A league already on scale 2 keeps scale 2 (it plays correctly on any generation). |

**Never turn the switch off while any league has a season on generation 6.**
With the switch off a build does not know generation 6, and that season's
games fail (on purpose: a season never changes engine silently). To stop
further moves, set `NEXGEN_NEW_SEASON_ENGINE=5` instead.

## 2. When a league moves, and what it looks like

A league moves at the first season game (or first saved tuning setting) of a
season that has nothing recorded and no game played -- the same moment
7.51 gives a season generation 5. A season already under way never moves:
alpha-test and stats-test finish their current seasons as they are and move
at their next ones.

In one locked step, before the season's engine is written down:

1. `players.csv` is read raw, checked (see 3), re-spread if listed, and
   every row stretched to scale 2;
2. the original is saved as `players.scale1.<season>.csv`;
3. the whole file is replaced atomically, in the scale 2 format (the height
   column is named `height_in`; builds before 8.0.0 refuse to load it);
4. open draft pools (`draft_pool_<year>.json/.csv`, year >= the season) are
   converted, originals saved as `draft_pool_<year>.scale1.<season>.<ext>`;
5. `rating_scale.json` gets a `converted` event (counts, clips, the
   re-spread, the headline numbers), and the league's news feed gets the
   engine-and-scale item (and the re-spread item, for a listed league);
6. then the season's entry in `rating_centers.json` and the witness in
   `season_progress.json` record generation 6, with the season's centres
   computed from the converted file.

Cloud Logging shows a `[rating-scale] ... players converted to rating scale
2 for season <year> (generation 6)` line per league.

**If a league cannot convert**, its season starts on generation 5 on scale
1, `rating_scale.json` gets a `refused` event with the reason, the news feed
gets a `[commissioner]` item, and the log shows `[rating-scale] ... NOT
moved`. It is offered the move again at its next season. Reasons: a rating
of a player on an ACTIVE roster that would fall outside 1-99 on scale 2 (it
would no longer play as it did; clips on minor leaguers and potentials cut
at 99 are allowed and logged), a players file split evenly between scales,
an unreadable file, or an operator hold (6).

## 3. Before turning it on (checklist)

- The release that carries this is 8.0.0 and has been deployed with the
  switch OFF; no revision older than 8.0.0 is serving
  (`gcloud run revisions list --service <svc> --region <region>` and the
  traffic split). A 7.51.x instance cannot read a converted league.
- The development model has replaced training camp: until then training
  camp REFUSES a scale 2 player (`require_engine_scale_players`), which
  would stop every converted league's next spring.
- The display step (screens show the stored rating) is in the same release.
- Dry-run every live league on a scratch copy (never the live data):

      python -c "from services.rating_scale_migration import plan_move; p = plan_move(r'<copy>/data', respread=False); print(p.blocker, len(p.active_clips), len(p.clips))"

  Measured 2026-10-14 on the scratch copies: alpha-test converts (two
  rating clips, two LOW-level 2026 draft picks: Eye 33 and Power 23 stored
  as 1; 33 potentials cut at 99; with its re-spread, one clip, the Power
  23), stats-test/stats-clean converts with no rating clip (57 potentials
  cut). The repo's sample `data/players.csv` would be refused (405 ratings
  outside the scale, no rosters, so every player counts as active).

## 4. Turning it on in production

1. Pause the scheduler so no automatic sim runs during the revision swap:
   `gcloud scheduler jobs pause <job> --location <region>`.
2. Make sure no sim is running (League Command Center / `sim_running`).
3. Set the variables on the service (this creates a new revision):

       gcloud run services update <service> --region <region> \
         --update-env-vars NEXGEN_GENERATION6_SCALE2=1,NEXGEN_RESPREAD_LEAGUES=alpha-test

4. Wait until the new revision has 100% of traffic and the old one has no
   instance (`gcloud run revisions list`). During the overlap the old
   revision (switch off) could start a season on generation 5 -- harmless,
   that league moves a season later -- but must not play a season the new
   one put on generation 6; that is why the scheduler is paused.
5. Resume the scheduler.
6. Nothing visible happens until each league's next season starts. When
   one does, check its `rating_scale.json`, the news item and the log line.

## 5. Watching it

- `rating_scale.json` (league data dir): `converted`, `reformatted`,
  `repaired`, `refused`, `rolled_back`, `generation_set` events.
- `repaired` means a players file came back on scale 1 under a season
  recorded on generation 6 (a stale copy pushed back, a restore) and was
  converted again at the next game. Nothing played wrong (each row carries
  its own scale), but find out where the stale copy came from.
- The working copy refuses to push a `players.csv` in the old format over
  one in the scale 2 format (`skip rating-scale overwrite` in the log), as
  it refuses to push a lower engine generation over a higher one.
- A league that will not load with `Missing required field: height_in
  (player <id> was written by a build older than 8.0.0 ...)`: an older
  build appended that row (a draft pick during a rollback or an overlap).
  Its ratings may be stretched values without their scale. Fix it from the
  draft pool and the draft results by hand (set `height_in`, and
  `rating_scale` 2 if the pool it came from was on scale 2), or remove the
  row and re-run the pick.

## 6. Taking one league back

Use `scripts/rating_scale_rollback.py` on a COPY of the league's data, with
the GCS restore discipline (memory: "Restoring GCS under a live instance"):
pause the scheduler, make sure no instance is serving the league (a running
instance pushes its own working copy back over a restore minutes later),
download, run, upload, restart.

    python scripts/rating_scale_rollback.py --league-dir <copy>/leagues/<id>/data --dry-run
    python scripts/rating_scale_rollback.py --league-dir <copy>/leagues/<id>/data --mode backup
    python scripts/rating_scale_rollback.py --league-dir <copy>/leagues/<id>/data --mode inverse
    python scripts/rating_scale_rollback.py --league-dir ... --mode backup --generation 5

- `--mode backup` (default) restores `players.scale1.<season>.csv` and the
  pools' backups: the league exactly as it was at the move. Anything that
  happened to players since (injuries, trades, signings, picks) is lost.
  Undoes a re-spread.
- `--mode inverse` un-stretches today's file in place with the exact
  inverse map: every change since the move is kept; a value developed since
  comes back to the nearest whole engine point; a potential keeps its gap
  (a potential that was below the rating, or cut at 99, is not restored). It
  does NOT undo a re-spread.
- Either way the league is put on HOLD (`"hold"` in `rating_scale.json`):
  it is not converted again at its next game or its next season. Delete the
  key to let it move again.
- The season's engine is left as recorded. Scale 1 plays correctly on
  generation 6, so a scale rollback needs nothing else. Add
  `--generation 5` only when the league must also leave generation 6 (for a
  binary rollback, below). It rewrites the season's `rating_centers.json`
  entry and the `season_progress.json` witness together; the working copy
  will not push that over a higher generation, which is why this is done on
  the durable copy with instances stopped. A mid-season change of engine
  changes how the rest of that season plays.
- Tested on scratch leagues: `tests/test_r8_switch_rollback.py`.

## 7. Rolling the binary back below 8.0.0

A 7.51.x build refuses a converted league's `players.csv` (measured on a
7.51.3 export: `ValueError: Missing required field: height` from
`load_players_from_csv`) and does not know generation 6 (its games raise
`unknown engine generation 6`). So, before deploying an older binary:

1. Pause the scheduler; stop serving (or take the leagues offline).
2. For every league with a `converted` event in `rating_scale.json`: run
   the rollback with `--generation 5` (or `4`) on its durable copy.
3. Deploy the older revision.

A league converted and NOT rolled back stays unreadable to the old build;
nothing is corrupted, but nobody can use it until 8.0.0 is back.
