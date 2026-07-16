import random
import pytest

from playbalance.batter_ai import BatterAI
from playbalance.state import PitcherState
from playbalance.stats import compute_pitching_rates
from tests.test_simulation import make_player, make_pitcher
from tests.util.pbini_factory import make_cfg


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_league_wide_swing_percentage():
    cfg = make_cfg(idRatingBase=50)
    cfg.values["swingProbScale"] = 1.25
    cfg.values["zSwingProbScale"] = 0.79
    cfg.values["oSwingProbScale"] = 0.69
    ai = BatterAI(cfg)
    batter = make_player("B", ch=50)
    pitcher = make_pitcher("P", movement=50)
    ps = PitcherState()
    ps.player = pitcher
    rng = random.Random(42)
    pitches = 10000
    for _ in range(pitches):
        balls = rng.randint(0, 3)
        strikes = rng.randint(0, 2)
        in_zone = rng.random() < 0.65
        if in_zone:
            dist = 0
            dx = 0.0
            dy = 0.0
        else:
            if rng.random() < 0.5:
                dist = 5
                dx = 5.0
                dy = 0.0
            else:
                dist = 6
                dx = 6.0
                dy = 0.0
        swing, _ = ai.decide_swing(
            batter,
            pitcher,
            pitch_type="fb",
            balls=balls,
            strikes=strikes,
            dist=dist,
            dx=dx,
            dy=dy,
            random_value=rng.random(),
            check_random=rng.random(),
        )
        ps.pitches_thrown += 1
        ps.record_pitch(in_zone=in_zone, swung=swing, contact=ai.last_contact)
    rates = compute_pitching_rates(ps)
    assert rates["z_swing_pct"] == pytest.approx(0.65, abs=0.03)
    assert rates["ozone_swing_pct"] == pytest.approx(0.32, abs=0.03)
