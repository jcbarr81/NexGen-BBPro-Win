"""A combined no-hitter is one news item naming every pitcher (the
rehearsal saw one item per pitcher, none naming him); each pitcher keeps
his own special event."""

from __future__ import annotations

from services.special_events import _news_items


def _pitcher(pid, name, ip, kind="combined_no_hitter", label="Combined No-Hitter"):
    return {
        "type": kind, "label": label, "category": "pitching", "player_id": pid,
        "player_name": name, "team_id": "HOM", "opponent_id": "AWY",
        "detail": f"{label} vs AWY ({ip} IP, 5 K, 2 BB, 0 HBP)",
        "stat_key": "no_hitter", "value": 1,
    }


def test_a_combined_no_hitter_is_one_item_naming_every_pitcher():
    events = [
        _pitcher("P1", "Ann Arm", "6.0"),
        {"type": "strikeouts", "label": "11 Strikeouts", "player_id": "P1",
         "player_name": "Ann Arm", "team_id": "HOM"},
        _pitcher("P2", "Bo Pen", "2.0"),
        _pitcher("P3", "Cy Close", "1.0"),
    ]
    items = _news_items(events)
    assert items == [
        ("Combined No-Hitter vs AWY: Ann Arm (6.0 IP), Bo Pen (2.0 IP), Cy Close (1.0 IP)",
         "HOM"),
        ("Ann Arm: 11 Strikeouts", "HOM"),
    ]


def test_a_solo_no_hitter_is_its_own_item_as_before():
    solo = {
        "type": "no_hitter", "label": "No-Hitter", "player_id": "P1",
        "player_name": "Ann Arm", "team_id": "HOM", "opponent_id": "AWY",
        "detail": "No-Hitter vs AWY (9.0 IP, 8 K, 1 BB, 0 HBP)",
    }
    assert _news_items([solo]) == [("No-Hitter vs AWY (9.0 IP, 8 K, 1 BB, 0 HBP)", "HOM")]
