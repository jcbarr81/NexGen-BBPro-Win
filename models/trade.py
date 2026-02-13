from dataclasses import dataclass, field
from typing import List

@dataclass
class Trade:
    trade_id: str
    from_team: str
    to_team: str
    give_player_ids: List[str]
    receive_player_ids: List[str]
    status: str = "pending"  # pending, owner_accepted, accepted, rejected
    give_pick_ids: List[str] = field(default_factory=list)
    receive_pick_ids: List[str] = field(default_factory=list)
