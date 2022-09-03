from collections import defaultdict
from datetime import date
from typing import Dict, List
from location import Location
import matchup


class Team:
    def __init__(self, division: str, name: str, home_location: Location):
        self.division: str = division
        self.name: str = name
        self.home_location: Location = home_location

        self.matchups: List[matchup.Matchup] = []
        self.num_games: int = 0
        self.num_preferred_home_games: int = 0
        self.num_games_by_date: Dict[date, int] = defaultdict(int)

    def __str__(self):
        return f"< {self.division} {self.name} >"

    def __hash__(self):
        return hash((self.division, self.name))

    def __eq__(self, other):
        return (
            self.division == other.division
            and self.name == other.name
            and self.home_location == other.home_location
        )
