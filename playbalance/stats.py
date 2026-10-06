from __future__ import annotations

from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .simulation import BatterState, FieldingState, TeamState
    from playbalance.state import PitcherState


# Audit H5: a player's batting, pitching and fielding lines all accumulate into
# one ``season_stats`` dict. These fielding counters share a name with a
# batting counter (cs = caught stealing as a runner, po = picked off,
# ci = reached on interference) or a pitching one (pk = pitcher pickoffs), so
# the two overwrote each other: every caught stealing was stored twice and a
# first baseman's putouts showed up as "picked off". Fielding keeps them under
# an ``f_`` prefix instead. The other fielding counters (a, e, dp, tp, pb, sba)
# have no twin and keep their names. Rows written before the fix carry the
# merged values and no ``f_`` keys; readers treat a missing key as 0.
FIELDING_SEASON_KEYS: Dict[str, str] = {
    "po": "f_po",
    "cs": "f_cs",
    "ci": "f_ci",
    "pk": "f_pk",
}


def fielding_season_key(key: str) -> str:
    """Return the ``season_stats`` key a fielding counter is stored under."""

    return FIELDING_SEASON_KEYS.get(key, key)


def compute_batting_derived(stats: 'BatterState') -> Dict[str, float]:
    """Return derived batting statistics from counting stats.

    Parameters
    ----------
    stats: BatterState
        The batter statistics to derive from.
    """
    tb = stats.b1 + 2 * stats.b2 + 3 * stats.b3 + 4 * stats.hr
    xbh = stats.b2 + stats.b3 + stats.hr
    lob = stats.lob
    p_pa = stats.pitches / stats.pa if stats.pa else 0.0
    return {"tb": tb, "xbh": xbh, "lob": lob, "p_pa": p_pa}


def compute_batting_rates(stats: 'BatterState') -> Dict[str, float]:
    """Return rate-based batting metrics."""
    derived = compute_batting_derived(stats)
    ab = stats.ab
    pa = stats.pa
    h = stats.h
    bb = stats.bb
    hbp = stats.hbp
    sf = stats.sf
    tb = derived["tb"]
    bip_den = stats.gb + stats.ld + stats.fb

    avg = h / ab if ab else 0.0
    obp_den = ab + bb + hbp + sf
    obp = (h + bb + hbp) / obp_den if obp_den else 0.0
    slg = tb / ab if ab else 0.0
    ops = obp + slg
    iso = slg - avg
    babip_den = ab - stats.hr - stats.so + sf
    babip = (h - stats.hr) / babip_den if babip_den else 0.0
    bb_pct = bb / pa if pa else 0.0
    k_pct = stats.so / pa if pa else 0.0
    bb_k = bb / stats.so if stats.so else 0.0
    so_looking_pct = stats.so_looking / stats.so if stats.so else 0.0
    sb_den = stats.sb + stats.cs
    sb_pct = stats.sb / sb_den if sb_den else 0.0
    gb_pct = stats.gb / bip_den if bip_den else 0.0
    ld_pct = stats.ld / bip_den if bip_den else 0.0
    fb_pct = stats.fb / bip_den if bip_den else 0.0
    gb_fb = stats.gb / stats.fb if stats.fb else 0.0
    ld_fb_ratio = stats.ld / stats.fb if stats.fb else 0.0

    return {
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "iso": iso,
        "babip": babip,
        "bb_pct": bb_pct,
        "k_pct": k_pct,
        "bb_k": bb_k,
        "so_looking_pct": so_looking_pct,
        "sb_pct": sb_pct,
        "gb_pct": gb_pct,
        "ld_pct": ld_pct,
        "fb_pct": fb_pct,
        "gb_fb": gb_fb,
        "ld_fb_ratio": ld_fb_ratio,
    }


def compute_pitching_derived(stats: 'PitcherState') -> Dict[str, float]:
    """Return derived pitching statistics from counting stats."""

    ip = stats.outs / 3.0
    cg = 1 if stats.gs and stats.gf and stats.outs >= 27 else 0
    sho = 1 if cg and stats.r == 0 else 0
    qs = 1 if stats.gs and stats.outs >= 18 and stats.er <= 3 else 0
    k_minus_bb = stats.so - stats.bb
    return {
        "ip": ip,
        "cg": cg,
        "sho": sho,
        "qs": qs,
        "k_minus_bb": k_minus_bb,
    }


def compute_pitching_rates(stats: 'PitcherState') -> Dict[str, float]:
    """Return rate-based pitching metrics."""

    ip = stats.outs / 3.0
    h9 = (stats.h * 9 / ip) if ip else 0.0
    hr9 = (stats.hr * 9 / ip) if ip else 0.0
    k9 = (stats.so * 9 / ip) if ip else 0.0
    bb9 = (stats.bb * 9 / ip) if ip else 0.0
    era = (stats.er * 9 / ip) if ip else 0.0
    whip = ((stats.bb + stats.h) / ip) if ip else 0.0
    k_bb = (stats.so / stats.bb) if stats.bb else 0.0
    fip = (
        ((13 * stats.hr) + 3 * (stats.bb + stats.hbp) - 2 * stats.so) / ip + 3.2
        if ip
        else 0.0
    )
    lob_den = stats.h + stats.bb + stats.hbp - 1.4 * stats.hr
    lob_pct = (
        (stats.h + stats.bb + stats.hbp - stats.r) / lob_den if lob_den else 0.0
    )
    fps_pct = stats.first_pitch_strikes / stats.bf if stats.bf else 0.0
    o_zone_pitches = getattr(
        stats, "o_zone_pitches", getattr(stats, "pitches_thrown", 0) - stats.zone_pitches
    )
    total_pitches = getattr(stats, "pitches_thrown", stats.zone_pitches + o_zone_pitches)
    zone_pct = stats.zone_pitches / total_pitches if total_pitches else 0.0
    z_swing_pct = stats.zone_swings / stats.zone_pitches if stats.zone_pitches else 0.0
    z_contact_pct = (
        stats.zone_contacts / stats.zone_swings if stats.zone_swings else 0.0
    )
    ozone_swing_pct = (
        stats.o_zone_swings / o_zone_pitches if o_zone_pitches else 0.0
    )
    ozone_contact_pct = (
        stats.o_zone_contacts / stats.o_zone_swings if stats.o_zone_swings else 0.0
    )
    ozone_pct = o_zone_pitches / total_pitches if total_pitches else 0.0
    bip_den = stats.gb + stats.ld + stats.fb
    gb_pct = stats.gb / bip_den if bip_den else 0.0
    ld_pct = stats.ld / bip_den if bip_den else 0.0
    fb_pct = stats.fb / bip_den if bip_den else 0.0
    gb_fb = stats.gb / stats.fb if stats.fb else 0.0
    ld_fb_ratio = stats.ld / stats.fb if stats.fb else 0.0
    swings = stats.zone_swings + stats.o_zone_swings
    contacts = stats.zone_contacts + stats.o_zone_contacts
    swstr_pct = (
        (swings - contacts) / stats.pitches_thrown if stats.pitches_thrown else 0.0
    )
    so_looking_pct = stats.so_looking / stats.so if stats.so else 0.0

    return {
        "h9": h9,
        "hr9": hr9,
        "k9": k9,
        "bb9": bb9,
        "era": era,
        "whip": whip,
        "k_bb": k_bb,
        "fip": fip,
        "lob_pct": lob_pct,
        "fps_pct": fps_pct,
        "zone_pct": zone_pct,
        "z_swing_pct": z_swing_pct,
        "z_contact_pct": z_contact_pct,
        "ozone_pct": ozone_pct,
        "ozone_swing_pct": ozone_swing_pct,
        "ozone_contact_pct": ozone_contact_pct,
        "swstr_pct": swstr_pct,
        "so_looking_pct": so_looking_pct,
        "gb_pct": gb_pct,
        "ld_pct": ld_pct,
        "fb_pct": fb_pct,
        "gb_fb": gb_fb,
        "ld_fb_ratio": ld_fb_ratio,
    }


def compute_fielding_derived(stats: 'FieldingState') -> Dict[str, float]:
    """Return derived fielding totals."""

    tc = stats.po + stats.a + stats.e
    of_a = stats.a if stats.player.primary_position in {"LF", "CF", "RF"} else 0
    return {"tc": tc, "of_a": of_a}


def compute_fielding_rates(stats: 'FieldingState') -> Dict[str, float]:
    """Return rate-based fielding metrics."""

    tc = stats.po + stats.a + stats.e
    fpct = (stats.po + stats.a) / tc if tc else 0.0
    total_play = stats.po + stats.a
    rf9 = total_play / stats.g if stats.g else 0.0
    rfg = total_play / stats.g if stats.g else 0.0
    cs_pct = stats.cs / stats.sba if stats.sba else 0.0
    pb_g = stats.pb / stats.g if stats.g else 0.0
    return {
        "fpct": fpct,
        "rf9": rf9,
        "rfg": rfg,
        "cs_pct": cs_pct,
        "pb_g": pb_g,
    }


def compute_team_derived(team: 'TeamState', opponent: 'TeamState') -> Dict[str, float]:
    """Return counting totals needed for team-level metrics.

    Parameters
    ----------
    team: TeamState
        The team to compute derived stats for (used for LOB).
    opponent: TeamState
        The opposing team whose offensive stats are used to compute defensive
        efficiency for ``team``.
    """

    pa = sum(bs.pa for bs in opponent.lineup_stats.values())
    h = sum(bs.h for bs in opponent.lineup_stats.values())
    bb = sum(bs.bb for bs in opponent.lineup_stats.values())
    so = sum(bs.so for bs in opponent.lineup_stats.values())
    hbp = sum(bs.hbp for bs in opponent.lineup_stats.values())
    hr = sum(bs.hr for bs in opponent.lineup_stats.values())
    roe = sum(bs.roe for bs in opponent.lineup_stats.values())
    der_den = pa - bb - so - hbp - hr
    der = 1 - (h + roe) / der_den if der_den else 0.0

    return {
        "opp_pa": pa,
        "opp_h": h,
        "opp_bb": bb,
        "opp_so": so,
        "opp_hbp": hbp,
        "opp_hr": hr,
        "opp_roe": roe,
        "der": der,
    }


def compute_team_rates(stats: Dict[str, float]) -> Dict[str, float]:
    """Return rate-based team metrics from cumulative totals."""

    g = stats.get("g", 0)
    r = stats.get("r", 0)
    ra = stats.get("ra", 0)
    opp_pa = stats.get("opp_pa", 0)
    opp_h = stats.get("opp_h", 0)
    opp_bb = stats.get("opp_bb", 0)
    opp_so = stats.get("opp_so", 0)
    opp_hbp = stats.get("opp_hbp", 0)
    opp_hr = stats.get("opp_hr", 0)
    opp_roe = stats.get("opp_roe", 0)

    der_den = opp_pa - opp_bb - opp_so - opp_hbp - opp_hr
    der = 1 - (opp_h + opp_roe) / der_den if der_den else 0.0
    rpg = r / g if g else 0.0
    rag = ra / g if g else 0.0

    return {"der": der, "rpg": rpg, "rag": rag}
