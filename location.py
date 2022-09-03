from collections import defaultdict
from datetime import date
from typing import Dict


class Location:
    def __init__(self, name: str):
        self.name: str = name

        self.num_gameslots: int = 0
        self.num_games_by_date: Dict[date, int] = defaultdict(int)

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.name == other.name
