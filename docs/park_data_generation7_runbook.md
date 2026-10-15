# Park data for engine generation 7 (operator runbook)

Engine generation 7 (the ball-flight step, Release 6b) plays every real park
on its own fence file and fits each park's home runs to Baseball Savant's
factors. Production does not read `data/parks/` from the image
(`.dockerignore` excludes `/data/`): park files are read from the park data
folder of the data root, the bucket root `gs://nexgen-bbpro-data/parks/`
(and a league's own `parks/` folder first, if it has one:
`utils.park_utils._park_data_roots`).

**Do this before any league plays generation 7.** Until then nothing here
is needed: legacy and generations 5 and 6 read the same `ParkConfig.csv`,
`ParkFactors.csv` and `Parks.csv` they read today, and the two new files are
read by generation 7 only. A generation 7 game whose park folder has no
`ParkFences.csv` refuses to start (`physics_sim.ballflight.ParkFencesMissing`)
rather than play the old rows.

## Files

| File | What changes | Read by |
|---|---|---|
| `ParkFences.csv` | new | generation 7 only (the five-point fences and walls) |
| `ParkHRTargets.csv` | new | `scripts/fit_park_hr_factors.py` only (no game reads it) |
| `ParkConfig.csv` | two rows appended (`SAC01` Sutter Health Park, `TAM02` George M. Steinbrenner Field) | every generation (new names only) |
| `Parks.csv` | the same two parks appended (altitude, city) | every generation (new ids only) |

`ParkFactors.csv` is unchanged and stays as it is.

## Steps

1. Pause the scheduler (the usual deploy step), so no game runs while the
   files change.
2. Back up the bucket's park folder:

       gsutil -m cp -r gs://nexgen-bbpro-data/parks gs://nexgen-bbpro-data/backups/parks-$(date +%Y%m%d-%H%M)

3. Check that the bucket's `ParkConfig.csv` and `Parks.csv` are the files
   the repository had before this step (only then may the new files replace
   them whole):

       gsutil cp gs://nexgen-bbpro-data/parks/ParkConfig.csv /tmp/ParkConfig.bucket.csv
       gsutil cp gs://nexgen-bbpro-data/parks/Parks.csv /tmp/Parks.bucket.csv
       git show 55fbb0c2c:data/parks/ParkConfig.csv | diff -q --strip-trailing-cr - /tmp/ParkConfig.bucket.csv
       git show 55fbb0c2c:data/parks/Parks.csv | diff -q --strip-trailing-cr - /tmp/Parks.bucket.csv

   If either differs, do not replace it: append only the two new lines (the
   last two lines of the repository's file) to the bucket's copy and upload
   that instead.
4. Upload the four files from the release's `data/parks/`:

       gsutil cp data/parks/ParkFences.csv data/parks/ParkHRTargets.csv \
           data/parks/ParkConfig.csv data/parks/Parks.csv gs://nexgen-bbpro-data/parks/

5. If any league has its own park folder, it is read before the bucket
   root; give it the same four files (or delete it so the root's are read):

       gsutil ls "gs://nexgen-bbpro-data/**/parks/ParkConfig.csv"

6. Verify on one league (or a scratch copy) with the harness or a game on
   generation 7: no `ParkFencesMissing`, and a real park reads its fence
   from the new file, e.g.

       python -c "from utils.park_utils import park_fence_for_name; print(park_fence_for_name('Comerica Park'))"

   prints `DET05` with a 412 ft centre field (the old row says 420).
7. Resume the scheduler.

## What it does to earlier generations

Nothing: `tests/test_r7_park_data.py` reads every park name of the old
`ParkConfig.csv` through the uploaded set and through the old files and
gets the same stadium, park factor, altitude and foul territory, and plays a
generation 6 game in both to the same digest. The two appended parks are
new names; a club picks them only by choosing them.

## Rollback

Restore the backup of step 2 (`gsutil -m cp -r` back over
`gs://nexgen-bbpro-data/parks`). Earlier generations do not notice either
way; a generation 7 game refuses to start until `ParkFences.csv` is back.
