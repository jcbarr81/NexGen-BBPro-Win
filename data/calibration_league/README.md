# League-like KPI fixture (generated -- do not hand-edit)

Built by `scripts/generate_league_fixture.py` for audit 2026-10-06 finding H3
(Release 2): a second KPI fixture that looks like a league owners play, next
to the hand-tuned `data/calibration` fixture that CI gates on.

How it is built (all product code, run in an isolated temp data root):

- players: `playbalance.league_creator.create_league` (the new-league
  generator), plus the archetype speed tiers owner decision 3 keeps, drawn
  with the generator's own archetype weights and floors (its default bootstrap
  path skips them, so the script applies them; see `_with_speed_tiers`);
- ACT rosters: `services.roster_auto_assign.auto_assign_team` per organisation
  (each club's best 13 hitters / 13 pitchers: the 26-man roster, decision 8);
- pitching staffs: `utils.pitching_autofill.autofill_pitching_staff`, written
  as the Pitching auto-fill does (SP1-5, LR, CL, SU, MR1-MR3; the 12th and
  13th active pitchers stay unlisted);
- lineups: `utils.lineup_autofill.auto_fill_lineup_for_team`;
- parks: generic for every team (`park_id` empty; audit L13).

Not yet reflected (owner decisions still to be implemented, DECISIONS.md):
decision 2 (league-relative ratings) and decision 7 (MLB batting-side mix).
The fixture reflects the CURRENT generator; regenerate it when those land.
Under today's absolute ratings its run level is set by where the generator
puts hitters against pitchers, so it differs from both alpha-test (older
generator) and `data/calibration`.

Parameters: seed 20261006, 30 teams, ages as of 2026-04-01,
ratings source `data/players_normalized.csv`.

Regenerate (byte-identical for the same seed and code):

    PYTHONHASHSEED=0 python scripts/generate_league_fixture.py --seed 20261006 --teams 30

Run the KPI harness on it (report-only; the current engine is expected to
fail gates here -- that is the point of the fixture):

    python scripts/physics_sim_season_kpis.py --base-dir data/calibration_league \
        --players data/calibration_league/players.csv --games 162 --seed 1 \
        --output tmp/league_fixture_kpis.json

Generated profile:

- 1530 players; ACT 390 hitters / 390 pitchers
- lineup regulars (vs RHP) mean CH 51.4 / PH 51.0 / EYE 50.5 / SP 54.7
- ACT pitchers mean arm 59.0 / control 53.9 / movement 56.8 / endurance 41.2
- ACT hitters with SP >= 70: 14.6%; SP >= 85: 3.6%
- ACT hitters batting left: 24.1%
