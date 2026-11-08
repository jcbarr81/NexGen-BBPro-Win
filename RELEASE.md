# Release Checklist

NexGen-BBPro ships as a cloud web app: the FastAPI backend on Cloud Run
(service `nexgen-bbpro-api`, region `us-central1`, project `nexgen-bbpro`) and
the React client on Firebase Hosting (site `nexgen-bbpro`). The Windows
EXE/installer and the Electron desktop build are retired; `scripts\build_release.py`
and `docs/post_installer_ui_checklist.md` are not part of a release any more.
Live leagues with human owners run on this service, so confirm with the owner
before deploying.

## 1. Prepare the version

1. Bump `VERSION` (SemVer rules in `AGENTS.md`) and set the same number as
   `AppVersion` in `packaging/NexGen-BBPro.iss` (still kept in step).
2. Add the version's entry to `release_notes_draft.md` (one bullet per
   version, owner-facing wording; `scripts\add_release_note.py "..."` appends a
   plain bullet). `release_notes.md` is no longer updated.
3. If the release adds a feature, add or update its tutorial
   (`services/tutorials.py`) and the guides (`docs/owner_admin_guide.md`,
   `docs/manuals/`).
4. Record backlog status in `docs/future_work.md` (mark the item SHIPPED x.y.z).

## 2. Validate

```powershell
# Full suite, 12 files at a time (~3.5 min). Known failures in every run:
# test_league_command_center, test_openai_client, test_payroll_policy,
# test_phase5_path_isolation, test_team_loader.
$env:PYTHONHASHSEED = "0"
python scripts\run_tests_isolated.py -j 12

# Client type check: compare against main (main is not clean, see
# docs/CODEX_HANDOFF.md section 5) and add no new errors.
cd desktop; npm run typecheck; cd ..
```

For a small contained change, the area's test files plus
`tests\test_rating_scale_display.py` and `tests\test_team_scoped_write_ownership.py`
and the type check are enough (`AGENTS.md`).

Engine or calibration changes: the KPI harness must be green on seeds 1 and 2,
run on the calibration fixture the way CI runs it
(`.github/workflows/physics_sim_kpi.yml`). Without `--base-dir`/`--players`
the script falls back to the repo's sample `data/players.csv`, which has no
pitch-rating columns and stops with "Missing required field: cu".

```powershell
$cal = "--games 162 --base-dir data\calibration --players data\calibration\players.csv --strict"
python scripts\physics_sim_season_kpis.py $cal.Split() --seed 1
python scripts\physics_sim_season_kpis.py $cal.Split() --seed 2
python scripts\physics_sim_season_kpis.py $cal.Split() --seed 1 --engine 6
```

CI also runs `--engine 5` and `--engine 7`, and the running gate on
`data\calibration_league` (`--gate-set running`).

Finance changes: the finance release gate (finance tests + multi-league
smoke + stability sim):

```powershell
python scripts\validate_finance_release.py --seasons 8
python scripts\smoke_multi_league.py
```

## 3. Commit and push

Commit the code with `VERSION`, `packaging/NexGen-BBPro.iss`,
`release_notes_draft.md` and any docs, then `git push origin main`.

## 4. Deploy the backend (Cloud Run)

```powershell
gcloud run deploy nexgen-bbpro-api --source . --project nexgen-bbpro --region us-central1 --quiet
```

This uploads the repo (filtered by `.gcloudignore`, which mirrors
`.dockerignore`) to Cloud Build, builds the `Dockerfile` (Node stage runs
`npm run build:renderer`, then a Python 3.12 image installs
`requirements-server.txt`) and rolls a new revision. Environment variables and
Secret Manager references (`SENDGRID_API_KEY`, `NEXGEN_SCHEDULER_TOKEN`,
`NEXGEN_DISCORD_WEBHOOK_URL`) carry over from the current revision; change them
only with `gcloud run services update ... --update-env-vars / --update-secrets`.
The service runs at most one instance: the new instance pulls league data from
the bucket at start, and the old one flushes its changes when it shuts down.

A Cloud Build failure in `npm ci` that times out fetching Electron from GitHub
is transient; run the deploy again.

## 5. Deploy the client (Firebase Hosting)

```powershell
cd desktop; npm run build:renderer; cd ..
npx firebase-tools deploy --only hosting --project nexgen-bbpro
```

Run the Firebase deploy from the repo root (`firebase.json` publishes
`desktop/dist` and rewrites every non-file path to the Cloud Run service).

## 6. Verify

```powershell
curl https://nexgen-bbpro.web.app/meta/app-status
```

The `version` field must match `VERSION`. Then load the app in a browser and
check the pages the release touched.

## 7. Announce

The last step of every deploy: post the release to Discord.

```powershell
python scripts\announce_release.py --message "- first highlight`n- second highlight"
```

The webhook comes from `--webhook`, the `NEXGEN_DISCORD_WEBHOOK_URL`
environment variable, or the git-ignored `scripts/.discord_webhook` file; never
commit it. `--dry-run` prints the message without posting.

## Operations switches and runbooks

- Engine generation 6 + rating scale 2 (`NEXGEN_GENERATION6_SCALE2`, on):
  `docs/rating_scale_switch_runbook.md`. Never turn it off once a league plays
  generation 6; hold new moves with `NEXGEN_NEW_SEASON_ENGINE=5`.
- Engine generation 7, ball flight (`NEXGEN_GENERATION7`, off):
  `docs/generation7_switch_runbook.md`, park data first
  (`docs/park_data_generation7_runbook.md`).

## Legacy: desktop migration rollback (retired installs only)

For an old desktop install migrated to the multi-league layout (5.0), the
pre-5.0 layout can be restored from its backup:

```powershell
.\.venv\Scripts\python.exe scripts\check_league_layout.py --restore --force
.\.venv\Scripts\python.exe scripts\check_league_layout.py --restore --backup-path "C:\path\to\pre_multi_league_v1_YYYYMMDD_HHMMSS.zip" --force
```
