# Almanac Data Contract

This document defines the initial data contract for the Almanac export
(`services/almanac_exporter.py`).

## Output Structure

Export target root:

- `exports/league_almanac_<timestamp>/almanac/`

Expected files/folders:

- `index.html` (landing page)
- `assets/almanac.css` (shared style)
- `seasons/index.html` (season directory)
- `seasons/<season_id>.html` (per-season pages)
- `teams/index.html` (team directory)
- `teams/<team_id>.html` (franchise pages with year splits)
- `players/index.html` (player directory)
- `players/<player_id>.html` (player career pages with season logs)
- `awards/index.html` (season awards directory)
- `postseason/index.html` (championship/postseason directory)
- `leaders/index.html` (current leaderboards)
- `records/index.html` (record-book view)
- `transactions/index.html` (current + archived transaction history when data exists)
- `finance/index.html` (season finance summaries and current ledger when data exists)

## Source Map

Primary inputs:

- `career_index.json` via `SeasonContext.load()`
- archived season artifacts from season `artifacts` map and
  `data/careers/<season_id>/metadata.json`
- current standings via `load_standings()`
- archived standings via `load_standings(base_path=...)`
- teams via `load_teams()`
- players via `load_players_from_csv("data/players.csv")`
- roster assignment for player->team mapping via `load_roster(...)`
- archived awards via season artifact `awards.json`
- archived champions/playoff results via season artifacts `champions.csv` and
  `playoffs*.json`
- current and archived transactions via `data/transactions.csv` and season
  artifact `transactions.csv`
- current finance sources via `data/team_financials.json`,
  `data/league_financial_settings.json`, and
  `data/financial_transactions.csv`
- archived finance snapshots via `data/finance_snapshots/<league_year>.json`
- records via `league_record_book()`

## Season Entry Schema

Normalized entry fields used during render:

- `season_id: str`
- `league_year: int`
- `sequence: int`
- `status: "archived" | "current"`
- `started_on: str`
- `ended_on: str`
- `archived_on: str`
- `artifacts: dict[str, str]`

## Initial Guarantees

- Export always writes a browsable landing page (`index.html`).
- Season index and per-season pages are generated for all known seasons in
  `career_index.json` plus the current season.
- Team directory and per-team franchise pages are generated from the active
  team list plus any team IDs present in archived/current standings.
- Player directory and per-player career pages are generated from the active
  player pool plus season/career stat ledgers when available.
- Awards, postseason, and leaders sections are generated as dedicated HTML
  pages and season pages surface awards/postseason summaries inline.
- Transactions and finance sections are generated when current or archived
  source files are available, including links back to related player, team, and
  season pages where possible.
- Shared Almanac styling includes responsive table wrappers, numeric alignment,
  and print-friendly defaults through `assets/almanac.css`.
- Validation coverage uses `validate_almanac_export(...)` to check required
  generated pages and local export-link integrity.
- Pages degrade gracefully when optional source files are missing (tables render
  with "No rows available.").
