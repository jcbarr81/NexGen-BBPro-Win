from dataclasses import dataclass
from typing import ClassVar, List, Optional

@dataclass
class BasePlayer:
    player_id: str
    first_name: str
    last_name: str
    birthdate: str
    height: int
    weight: int
    bats: str
    primary_position: str
    other_positions: List[str]
    gf: int  # Groundball-Flyball ratio

    # Throwing hand ("L"/"R"/"S"). Defaults to empty string for
    # backwards compatibility with pre-existing players.csv files that
    # predate the throws column; the loader fills it in from the bats
    # value when the CSV lacks the column.
    throws: str = ""

    # Appearance attributes
    ethnicity: str = ""
    skin_tone: str = ""
    hair_color: str = ""
    facial_hair: str = ""

    injured: bool = False
    injury_description: Optional[str] = None
    return_date: Optional[str] = None
    injury_list: Optional[str] = None  # e.g. dl15, ir
    injury_start_date: Optional[str] = None
    injury_minimum_days: Optional[int] = None
    injury_eligible_date: Optional[str] = None
    injury_rehab_assignment: Optional[str] = None
    injury_rehab_days: int = 0
    durability: int = 50
    is_pitcher: bool = False
    # Flag indicating if the player is ready after training camp
    ready: bool = False

    _rating_fields: ClassVar[set[str]] = {"gf", "durability"}

    def __setattr__(self, name: str, value) -> None:
        rating_fields = getattr(type(self), "_rating_fields", set())
        if name in rating_fields and isinstance(value, (int, float)):
            value = 99 if value > 99 else int(value)
        super().__setattr__(name, value)
