# Generation 7 switch: the ball-flight engine (operator runbook)

What moves a league to engine generation 7 (the ball-flight engine: carry
with drag, real ballparks and fences, the batted-ball kernel with pop-ups,
foul-outs, the fielding play model, the pitcher's ground-ball identity), how
to turn it on, how to hold it, and what turning it off does. Background:
`docs/audits/2026-10-06-engine-ratings-audit/RELEASE6_PLAN.md` section 9,
owner decisions 18-24. Generation 7 is built the way 8.0.0 built generation
6 and moves a league through the same code
(`docs/rating_scale_switch_runbook.md`); read that runbook first.

## 1. The settings (Cloud Run environment variables)

| Variable | Value | Effect |
|---|---|---|
| `NEXGEN_GENERATION7` | `1` (also `on`, `true`, `yes`) | THE switch. Off (unset) by default. Read ONLY while `NEXGEN_GENERATION6_SCALE2` is on (generation 7 needs rating scale 2, and the move to scale 2 is that switch's); alone it does nothing. With both on: every league moves to generation 7 at the start of its next season, and new leagues start on it. |
| `NEXGEN_GENERATION6_SCALE2` | `1` | The 8.0.0 switch (already on in production since 8.0.0). Must stay on. |
| `NEXGEN_NEW_SEASON_ENGINE` | `6`, `5` or `4` | The hold. `6`: new seasons get generation 6 (no move to 7; a scale 1 league still moves to scale 2 and 6). `5` / `4`: as in the 8.0.0 runbook. A hold applies to seasons that have not started; a season already recorded never changes engine. A league on generation 7 whose NEXT season starts under a hold of 6 plays that season on 6 (scale 2 plays correctly on 6; the slider rule of section 4 applies). |

**Turning `NEXGEN_GENERATION7` off (or `NEXGEN_GENERATION6_SCALE2` off)
breaks every league with a season on generation 7**, and so does routing
traffic back to a revision without the switch or older than the release
that carries generation 7: that revision does not know generation 7, and
those leagues' games fail on purpose ("unknown engine generation 7"; a
season never changes engine silently). To stop further moves, set
`NEXGEN_NEW_SEASON_ENGINE=6` on the current revision instead. Generation 7
also refuses a game whose park folder has no `ParkFences.csv`
(`ParkFencesMissing`), so removing that file breaks those leagues too.

## 2. When a league moves, and what it looks like

Exactly where 8.0.0 moves a league to generation 6 (the 8.0.0 runbook,
section 2), never mid-season:

- **At its rollover** (`services/league_rollover.py`): a league on scale 1
  is converted (the 8.0.0 move; `rating_scale.json` records `converted`
  with `engine_generation: 7`); a league already on scale 2 has nothing to
  convert. Its next season is recorded on generation 7 when it starts.
- **At the first season game of a season nobody rolled into**: the same,
  then generation 7 is recorded.
- **New leagues** created with both switches on are generated on scale 2
  and start on generation 7 (no conversion, no news).
- **Refusals and holds** are 8.0.0's: a league that cannot be converted
  (a top clip, or a bottom clip on a major-league roster) plays its next
  season on generation 5 and scale 1 and the commissioner is told; a league
  with a `"hold"` in `rating_scale.json` is not moved.

**News.** One item per league: a league converted in the same move gets the
engine-and-scale item with the ball-flight paragraph in it; a league already
on scale 2 gets its own ball-flight item ("... now plays on the newest game
engine, with real ball flight ..."), naming how many of its clubs play in
real major-league parks. Neither is posted twice.

**Sliders.** At the league's first generation 7 game its tuning file is
rewritten once: Home Run Rate and Launch Angle Base go back to neutral
(1.00 and 12.1) with their earlier values kept under `_pre_generation_7_r7`,
and the file is marked `_ballflight_sliders_rebased_r7`.

**Centres.** The season's `rating_centers.json` entry gains
`hitter_pull_center` and `pitcher_gf_usage_center`; a generation 7 game
refuses to start without them.

Cloud Logging: the conversion's `[rating-scale] ... (generation 7,
converted)` line for a scale 1 league; nothing extra for a scale 2 league.

## 3. Turning it on in production

Project `nexgen-bbpro`, service `nexgen-bbpro-api`, region `us-central1`.

1. **Upload the park data FIRST** (`docs/park_data_generation7_runbook.md`,
   steps 1-7): back up `gs://nexgen-bbpro-data/parks/`, then

       gsutil cp data/parks/ParkFences.csv data/parks/ParkHRTargets.csv gs://nexgen-bbpro-data/parks/

   and check that `ParkConfig.csv`, `ParkFactors.csv` and `Parks.csv` are
   unchanged (`gsutil ls -l gs://nexgen-bbpro-data/parks/` against the
   backup). Earlier generations do not read the two new files
   (`tests/test_r7_park_data.py::test_the_bucket_upload_leaves_earlier_generations_identical`):
   this step is safe with the switch off and can be done any time before.
2. Deploy the release carrying generation 7 with the switch OFF, and make
   sure no older revision serves traffic:

       gcloud run revisions list --service nexgen-bbpro-api --region us-central1 --project nexgen-bbpro

3. Pause the scheduler so no automatic sim runs during the revision swap:

       gcloud scheduler jobs list --location us-central1 --project nexgen-bbpro
       gcloud scheduler jobs pause <job> --location us-central1 --project nexgen-bbpro

4. Make sure no sim is running.
5. Set the switch (this creates a new revision; leave
   `NEXGEN_GENERATION6_SCALE2=1` as it is):

       gcloud run services update nexgen-bbpro-api --region us-central1 --project nexgen-bbpro --update-env-vars NEXGEN_GENERATION7=1

6. Wait until the new revision has 100% of traffic and the old one has no
   instance (`gcloud run revisions list ...`). During the overlap the old
   revision must not play a season the new one put on generation 7; that is
   why the scheduler is paused.
7. Resume the scheduler:

       gcloud scheduler jobs resume <job> --location us-central1 --project nexgen-bbpro

8. Each league moves at the start of its next season. Check its
   `rating_centers.json` (`"engine_generation": 7` for the new season), the
   news item, and for a scale 1 league its `rating_scale.json` event.

**To hold** new moves without breaking anyone:

    gcloud run services update nexgen-bbpro-api --region us-central1 --project nexgen-bbpro --update-env-vars NEXGEN_NEW_SEASON_ENGINE=6

## 4. Taking one league back to generation 6

A season in play on generation 7 should finish on it. Ways to put a league
on generation 6:

- **Every league's next season:** `NEXGEN_NEW_SEASON_ENGINE=6` before those
  seasons start (section 3, "To hold"). Nothing to restore.
- **One league whose season is recorded on 7 but not yet played** (its
  offseason or preseason, before the first game): rewrite the recorded
  generation on its durable copy, with the scheduler paused and no
  instance serving (the 8.0.0 runbook, section 6's procedure: a running
  instance pushes its working copy back over a restore):

      python -c "from services.rating_scale_migration import set_recorded_generation; print(set_recorded_generation(r'<copy>/leagues/<id>/data', '<season>', 6))"

  Upload `rating_centers.json`, `season_progress.json` and
  `rating_scale.json` (it records the `generation_set` event). The league
  stays on scale 2, which plays correctly on generation 6. Its earlier Home
  Run Rate and Launch Angle Base settings (kept under
  `_pre_generation_7_r7`) come back, unless the commissioner set those
  sliders while on generation 7: those settings stay and are then read with
  the earlier meaning (tell the commissioner to check them). With `NEXGEN_GENERATION7` still on, that league's FOLLOWING
  season moves to 7 again unless the hold is set.
- **Mid-season** the same call changes how the rest of that season plays;
  do it only to recover a league that cannot play (for example after the
  switch was turned off by mistake).

To also take a league back to scale 1, use the 8.0.0 runbook
(`scripts/rating_scale_rollback.py ... --generation 5`).

## 5. Rolling the binary back below the generation 7 release

An older build does not know generation 7. Before deploying one: pause the
scheduler, stop serving, put every league with a season on generation 7 on
generation 6 (section 4), then deploy. A league left on 7 is unreadable to
the old build's games until the release is back; nothing is corrupted.
