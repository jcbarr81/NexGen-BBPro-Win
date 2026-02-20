# UBL Simulation

UBL (Ultimate Baseball League) Simulation is a Python project that models a small baseball league with a graphical interface.

## Features
- **PyQt6 interface:** run `main.py` to launch the splash screen, then choose `Load Existing League` or `Create New League` before login.
- **League management:** classes for players, teams, trades and rosters in `models/` with supporting services and UI dialogs.
- **Game simulation:** `playbalance/simulation.py` provides a minimal engine for at-bats, pitching changes and base running.
- **Data files:** example data lives in the `data/` directory including rosters, lineups and configuration values.
- **AI-generated logos:** `utils.logo_generator` can create team logos using OpenAI's image API.
- **Postseason:** MLB-style playoffs with flexible league sizes, round-by-round simulation, bracket viewer, and champions log.
- **Season phases & progress:** dedicated Amateur Draft phase with automatic pause on Draft Day and a "Simulate to Draft" action in the Season Progress window. See `docs/season_progress.md`.

## OpenAI setup

Utilities that generate images (avatars and team logos) require an OpenAI API
key. Set the `OPENAI_API_KEY` environment variable before running the
application:

```bash
export OPENAI_API_KEY=<your API key>
```

For local development you may instead create a `config.ini` file containing a
`[OpenAIkey]` section. This file is ignored by git and serves only as a
fallback when the environment variable is missing:

```
[OpenAIkey]
key=<your API key>
```

The key enables calls to OpenAI's `images.generate` endpoint.

### Play balance configuration

Strategy behaviour in the simulation is driven by values from the
`PlayBalance` section of the historical *PB.INI* file.  The configuration is
loaded into a dedicated :class:`PlayBalanceConfig` dataclass
(`playbalance/playbalance_config.py`) which exposes the entries as attributes with
safe defaults.  The managers and `GameSimulation` consume this object instead
of raw dictionaries.

Pitch accuracy is influenced by control box dimensions configured via
``{pitch}ControlBoxWidth`` and ``{pitch}ControlBoxHeight`` entries (e.g.
``fbControlBoxWidth`` for fastballs).  Each value defaults to ``1`` when not
specified, providing a minimal strike zone around the target.

For tests and experimentation a helper factory is provided in
`tests/util/pbini_factory.py` which can create minimal configurations:

```python
from tests.util.pbini_factory import make_cfg
cfg = make_cfg(offManStealChancePct=50)
```

## Lineup CSV Format
Lineup files live in `data/lineups/` and are named `<TEAM>_vs_lhp.csv` or `<TEAM>_vs_rhp.csv`.
Each file contains the columns:

```csv
order,player_id,position
```

`player_id` uses the internal IDs such as `P1000`.

## Development
Install the dependencies (see `requirements.txt`) then run:

```bash
pip install bcrypt
python main.py
```

On the splash screen, click `Start Game` and choose one of:
- `Load Existing League` to open the login flow for leagues already on disk.
- `Create New League` to run guided league setup first, then proceed to login.


### Running tests
Tests are located in the `tests/` directory and can be executed with:

```bash
pytest
```

To run a single exhibition style scenario you can target an individual test,
for example:

```bash
pytest tests/test_simulation.py::test_run_tracking_and_boxscore -q
```

### Multi-league smoke check

Before release builds, run the automated multi-league isolation smoke matrix:

```bash
python scripts/smoke_multi_league.py
```

### Release validation quick commands

Run the finance release quality gate (targeted finance tests, including ledger/contracts/owner-finance coverage, + multi-league finance smoke + strict stability simulation):

```bash
.\.venv2\Scripts\python.exe scripts/validate_finance_release.py --seasons 8
```

Run the release build with default pre-build validation enabled:

```bash
.\.venv2\Scripts\python.exe scripts/build_release.py --clean
```

Skip pre-build validation only when troubleshooting the build pipeline:

```bash
.\.venv2\Scripts\python.exe scripts/build_release.py --clean --skip-validation
```

### Season simulation script

Run a full 162-game season and print average box score statistics with:

```bash
python scripts/simulate_season_avg.py
```

Or simulate a half 81-game season using:

```bash
python scripts/sim_halfseason_avg.py
```

For lengthy headless simulations consider running under
[PyPy](https://www.pypy.org/) or invoking CPython with
`python -O` to enable optimizations and remove asserts. PyPy's JIT can
significantly speed up the pure Python simulation loop, but some
CPython-specific C extensions such as `PyQt6` may be unavailable. The
season script itself depends only on PyPy-friendly modules (e.g. `bcrypt`
via cffi), so it can be executed without the GUI stack.

### Building an executable
Install PyInstaller and create a standalone binary with:

```bash
pip install -r requirements-dev.txt
python build_exe.py
```

The executable will be written to the `dist/` directory.

### Default Admin Credentials
When a new league is created or user accounts are cleared, the system rewrites
`data/users.txt` to contain a single administrator account. Most passwords are
stored as `bcrypt` hashes, but the default administrator account keeps a
plain-text password so the app can always be accessed. Use these fallback
credentials to log in after a reset:

```
username: admin
password: pass
```

### Postseason

The postseason supports MLB-style seeding and variable league sizes (4, 6, or 8 teams per league).

- Seeding: division winners are prioritized (by default) above wildcards, then ordered by wins and run differential. Leagues are inferred from the first token of a team's `division` (e.g., `AL East` → `AL`); override via `data/playoffs_config.json`.
- Rounds: depending on configured size, the bracket includes Wild Card (BO3), Division Series (BO5), League Championship Series (BO7), and World Series (BO7) with 1‑1‑1, 2‑2‑1, and 2‑3‑2 home/away patterns respectively.
- Running: open Admin → League → Season Progress and click “Simulate Playoffs” to generate and complete the bracket. Progress persists after each game.
- Viewing: open Admin → League → “Open Playoffs Viewer” to see the current bracket and per‑game results. The viewer also offers “Simulate Round” and “Simulate Remaining”.
- Outputs:
  - Bracket: `data/playoffs.json` (atomic writes, `.bak` backup)
  - Box scores: `data/playoff_boxscores/<ROUND>/<SERIES>/<GAME>.html`
  - Champions: `data/champions.csv` with `year,champion,runner_up,series_result`

Configuration file (optional): `data/playoffs_config.json`

```
{
  "num_playoff_teams_per_league": 6,
  "series_lengths": {"wildcard": 3, "ds": 5, "cs": 7, "ws": 7},
  "home_away_patterns": {"3": [1,1,1], "5": [2,2,1], "7": [2,3,2]},
  "division_winners_priority": true,
  "division_to_league": {"AL East": "AL", "NL West": "NL"}
}
```

