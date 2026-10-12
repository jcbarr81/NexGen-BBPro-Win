# Product-created KPI fixture (captured -- do not hand-edit)

A third KPI fixture, next to `data/calibration` (hand-tuned, real parks; CI's
strict gates) and `data/calibration_league` (generator-built by
`scripts/generate_league_fixture.py`).

This one is a league exactly as the product makes it: a 30-team league created
through the create-league path (the same code the wizard runs), with three
owner clubs given varied Game Day settings, spring training run and the
Preseason -> Regular Season advance done (CPU Opening Day upkeep), captured on
2026-10-12 before any regular-season game. Only what the KPI harness reads is
kept: `players.csv`, `teams.csv`, `rosters/` (rosters and pitching staffs) and
`lineups/`.

Why it exists: Release 5's league-relative ratings were tuned against it. It
is the fixture closest to a live league, and it differs from the other two in
ways that matter: its lineup regulars sit about level with its bench (the
calibration fixture's are 1.5 to 2 points above), its pitchers' arm ratings
average 50 (55.8 and 59.7 on the other two), its relievers are not rated above
its starters, and its hitters' pull and ground-ball tendencies are bunched.

Run it like the league fixture (its offence gates are report-only):

    python scripts/physics_sim_season_kpis.py --base-dir data/calibration_product \
        --players data/calibration_product/players.csv --games 162 --seed 1 \
        --engine 5 --gate-set running --strict --output tmp/product.json

Engine generation 5, six seasons (2026-10-12): 4.52 runs per team-game,
strikeouts 21.8%, walks 8.3%, home runs 1.00 per team-game, home teams win
.536.
