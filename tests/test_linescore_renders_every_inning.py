"""Audit L11: a box score's line score shows every inning that was played.

The template had nine fixed inning columns and the renderer looped
``range(9)``, so every extra-inning game (77 of 910 in the audit replicate)
printed inning runs that did not add up to the R column.
"""

import re
from pathlib import Path

import pytest

from physics_sim.engine import simulate_matchup_from_files
from playbalance.simulation import render_boxscore_html

CAL = Path("data/calibration")


def _box(away_innings, home_innings):
    return {
        side: {
            "score": sum(runs),
            "inning_runs": list(runs),
            "batting": [],
            "pitching": [],
            "fielding": [],
        }
        for side, runs in (("away", away_innings), ("home", home_innings))
    }


def _line_score(html):
    """Return (inning headers, {abbr: [cell, ...]}) from the first table."""

    table = html.split("<table>", 1)[1].split("</table>", 1)[0]
    head, body = table.split("</thead>", 1)
    headers = re.findall(r"<th>([^<]*)</th>", head)
    rows = {}
    for row in re.findall(r"<tr>(.*?)</tr>", body, re.DOTALL):
        abbr = re.search(r"<th>([^<]*)</th>", row).group(1)
        rows[abbr] = re.findall(r"<td>([^<]*)</td>", row)
    return headers, rows


def _innings(cells):
    """Split a row into inning cells and the trailing R/H/E."""

    return cells[:-3], cells[-3:]


def _render(box):
    return render_boxscore_html(
        box, home_name="Home", away_name="Away", home_abbr="HOM", away_abbr="AWY"
    )


def test_extra_inning_line_score_sums_to_runs():
    away = [0, 1, 0, 0, 2, 0, 0, 0, 0, 0, 1, 0]
    home = [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1]
    headers, rows = _line_score(_render(_box(away, home)))

    assert headers[1:13] == [str(i) for i in range(1, 13)]
    assert headers[13:] == ["R", "H", "E"]
    for abbr, runs in (("AWY", away), ("HOM", home)):
        innings, (r, _h, _e) = _innings(rows[abbr])
        assert len(innings) == 12
        assert [int(c) for c in innings] == runs
        assert sum(int(c) for c in innings) == int(r)


def test_regulation_game_still_has_nine_columns():
    away = [0, 0, 1, 0, 0, 0, 0, 0, 0]
    home = [0, 0, 0, 2, 0, 0, 0, 0, 0]
    headers, rows = _line_score(_render(_box(away, home)))

    assert headers[1:10] == [str(i) for i in range(1, 10)]
    assert len(_innings(rows["AWY"])[0]) == 9
    assert len(_innings(rows["HOM"])[0]) == 9


def test_unplayed_bottom_half_is_marked_x():
    """A home side leading after the top of the 9th never bats; the cell reads
    X (not blank), and the played innings still sum to R."""

    away = [0, 0, 1, 0, 0, 0, 0, 0, 0]
    home = [0, 0, 0, 2, 0, 0, 0, 0]
    _headers, rows = _line_score(_render(_box(away, home)))

    innings, (r, _h, _e) = _innings(rows["HOM"])
    assert innings[-1] == "X"
    assert sum(int(c) for c in innings[:-1]) == int(r) == 2


def test_engine_extra_inning_game_renders_every_inning():
    """End to end on the calibration fixture: the first seed (from 24) that
    goes to extras. A search, not one pinned seed, so an engine change that
    shifts the random stream doesn't break a line-score test."""

    result = None
    for seed in range(24, 124):
        candidate = simulate_matchup_from_files(
            away_team="CAL02",
            home_team="CAL01",
            players_path=CAL / "players.csv",
            base_dir=CAL,
            park_name="Fenway Park",
            seed=seed,
        )
        if len(candidate.metadata["inning_runs"]["away"]) > 9:
            result = candidate
            break
    if result is None:
        pytest.skip("no extra-inning game in 100 fixture seeds")
    inning_runs = result.metadata["inning_runs"]
    score = result.metadata["score"]

    box = _box(inning_runs["away"], inning_runs["home"])
    for side in ("away", "home"):
        box[side]["score"] = score[side]
    _headers, rows = _line_score(_render(box))

    for abbr, side in (("AWY", "away"), ("HOM", "home")):
        innings, (r, _h, _e) = _innings(rows[abbr])
        assert len(innings) == len(inning_runs["away"])
        played = [int(c) for c in innings if c not in ("", "X")]
        assert sum(played) == int(r) == score[side]
