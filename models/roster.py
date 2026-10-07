from dataclasses import dataclass, field
from typing import Dict, List

from utils.roster_rules import ACTIVE_ROSTER_SIZE

@dataclass
class Roster:
    team_id: str
    act: List[str] = field(default_factory=list)
    aaa: List[str] = field(default_factory=list)
    low: List[str] = field(default_factory=list)
    dl: List[str] = field(default_factory=list)
    ir: List[str] = field(default_factory=list)
    dl_tiers: Dict[str, str] = field(default_factory=dict)

    def move_player(self, player_id: str, from_level: str, to_level: str):
        source = getattr(self, from_level)
        if player_id not in source:
            raise ValueError(f"{player_id} not on {from_level}")
        source.remove(player_id)
        if from_level == "dl":
            self.dl_tiers.pop(player_id, None)

        target = getattr(self, to_level)
        target.append(player_id)
        if to_level == "dl":
            # Default manual moves to the 15-day list unless overwritten elsewhere.
            self.dl_tiers[player_id] = self.dl_tiers.get(player_id, "dl15")

    def promote_replacements(self, target_size: int = ACTIVE_ROSTER_SIZE) -> None:
        """Promote players from the minors to fill active roster vacancies.

        Parameters
        ----------
        target_size:
            Desired size of the active roster. Players are promoted from
            ``aaa`` first and then ``low`` until this size is met or no more
            players are available.
        """

        while len(self.act) < target_size and (self.aaa or self.low):
            if self.aaa:
                self.act.append(self.aaa.pop(0))
            else:
                self.act.append(self.low.pop(0))
