# Park data for engine generation 7 (operator runbook)

Engine generation 7 (the ball-flight step, Release 6b) plays every real park
on its own fence file and fits each park's home runs to Baseball Savant's
factors. Production does not read `data/parks/` from the image
(`.dockerignore` excludes `/data/`): park files are read from the park data
folder of the data root, the bucket root `gs://nexgen-bbpro-data/parks/`
(and a league's own `parks/` folder first, if it has one:
`utils.park_utils._park_data_roots`).

**Do this before any league plays generation 7: it is step 1 of the
generation 7 switch-on (`docs/generation7_switch_runbook.md`, section 3),
done before `NEXGEN_GENERATION7` is set.** It is safe at any time with the
switch off: no earlier generation reads the two files
(`tests/test_r7_park_data.py::test_the_bucket_upload_leaves_earlier_generations_identical`
plays legacy, generation 5 and generation 6 games in Comerica, Fenway,
Coors and Oakland on the bucket's folder before and after the upload, to
the same digest). A generation 7 game whose park folder has no `ParkFences.csv`
refuses to start (`physics_sim.ballflight.ParkFencesMissing`) rather than
play the ParkConfig rows an earlier engine reads.

## Files

| File | Change | Read by |
|---|---|---|
| `ParkFences.csv` | new | generation 7 only: the five-point fences and walls of the 30 home parks of 2026, the Athletics' and Rays' former and temporary homes and the one-off venues. Sutter Health Park (`SAC01`) and George M. Steinbrenner Field (`TAM02`) are named here and nowhere else |
| `ParkHRTargets.csv` | new | `scripts/fit_park_hr_factors.py` only (no game reads it) |
| `ParkConfig.csv`, `Parks.csv`, `ParkFactors.csv` | **none** | every generation, exactly as today |

Only the two new files are uploaded. `ParkConfig.csv` and `Parks.csv` are
not touched: an earlier version of this step appended the two temporary
parks to them, and the review of f6b7b0d2b found that the park lookup's
substring fallback then sent names such as "Steinbrenner" or "Health Park"
to the new rows on every engine. Generation 7 finds the two parks by exact
name in `ParkFences.csv` instead.

## Steps

1. Pause the scheduler (the usual deploy step), so no game runs while the
   files change.
2. Back up the bucket's park folder:

       gsutil -m cp -r gs://nexgen-bbpro-data/parks gs://nexgen-bbpro-data/backups/parks-$(date +%Y%m%d-%H%M)

3. Upload the two new files from the release's `data/parks/`:

       gsutil cp data/parks/ParkFences.csv data/parks/ParkHRTargets.csv gs://nexgen-bbpro-data/parks/

4. If any league has its own park folder, it is read before the bucket
   root; give it the same two files (or delete the folder so the root's are
   read):

       gsutil ls "gs://nexgen-bbpro-data/**/parks/ParkConfig.csv"

5. Check that nothing else changed in the bucket's park folder:

       gsutil ls -l gs://nexgen-bbpro-data/parks/

   lists `ParkConfig.csv`, `ParkFactors.csv` and `Parks.csv` with the sizes
   and dates of the backup in step 2, and the two new files.
6. Verify on one league (or a scratch copy) with the harness or a game on
   generation 7: no `ParkFencesMissing`, and a real park reads its fence
   from the new file, e.g.

       python -c "from utils.park_utils import park_fence_for_name; print(park_fence_for_name('Comerica Park'))"

   prints `DET05` with a 412 ft centre field (ParkConfig's row says 420).
7. Resume the scheduler.

## What it does to earlier generations

Nothing. `tests/test_r7_park_data.py` reads every park name and every park
id of `ParkConfig.csv` with and without the two new files beside it and gets
the same stadium, park factor, altitude, foul territory and park; the two
temporary parks are found by no earlier lookup; the release's `data/parks/`
is exactly the three files the bucket holds plus the two new ones; and a
legacy, generation 5 and generation 6 game in four parks (a real park, a
tall wall, altitude, a former home) plays to the same digest on the
bucket's folder before and after only the two files are added.

## Rollback

Delete the two new files (or restore the backup of step 2). Earlier
generations do not notice either way; a generation 7 game refuses to start
until `ParkFences.csv` is back.
