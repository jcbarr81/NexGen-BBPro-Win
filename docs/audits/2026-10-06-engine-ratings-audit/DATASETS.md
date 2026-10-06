# Alpha-test audit datasets (read-only copies; NEVER write to GCS / live league)

All JSON files map player_id -> {name, team, level_now, pos, is_pitcher, bats, throws, age,
preferred_pitching_role, hitter_archetype, pitcher_archetype, ratings{...}, stats{...}, line_type}.
`stats` holds COUNTING stats only (rate fields removed; recompute them). Hitting and pitching
share key names (h, hr, bb, so, ...): use `line_type` ("hitting" | "pitching") -- no player has both.
Pitching: outs (IP = outs/3), bf, er, r, h, hr, bb, so, hbp, w, l, sv, gs, g, pitches_thrown, ...
Hitting: pa, ab, h, b1, b2, b3, hr, bb, ibb, hbp, so, sf, sh, sb, cs, gidp, roe, gb, fb, ld, ...
Fielding keys (po, a, e, dp, ...) ride along in the same dict.

- current_engine_players.json -- 910 games (2026-08-01..12-30) simulated LOCALLY with the CURRENT
  code (7.45.8: power fix, pinch-run fix, active-roster-only games). Best view of the engine today.
- live_season_players.json -- the live league's 710 games (04-01..07-31) as owners see them.
  CONTAMINATED: 04-01..07-20 ran on the pre-7.45.0 engine (Contact drove HRs, pinch runners overused)
  and ALL of it let AAA/LOW/DL players play MLB games (fixed 7.45.6).
- window_0721_0731_players.json -- live 07-21..07-31 = live minus the 07-08 snapshot (snapshots are written AFTER the run named by their date): 7 games per team, post power fix, pre active-roster fix, for the
  SUBSET of players present in the 07-08 snapshot only (snapshots are partial, ~300 players).
- teams.json -- per team: current_engine (910-game diff) and live_season counting stats.

League copies: ../live/leagues/alpha-test/data (as downloaded), ../resim/leagues/alpha-test/data
(after the local re-sim). Ratings note: alpha-test ratings are COMPRESSED (an old normalize bug:
pitcher endurance 20-54, movement floor 52, control floor 50) -- correlations shrink with narrow
spreads; compare against the calibration fixture (data/calibration, wide ratings).
