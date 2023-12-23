from datetime import date, time
from typing import Set

import versizzle.utils as utils
from versizzle.location import Location


class Gameslot:
    def __init__(self, date: date, time: time, location: Location):
        # Declaring import here to prevent circular import.
        from versizzle.matchup import Matchup

        self.date = date
        self.time = time
        self.location = location

        self.is_preassigned = False

        self.matchups_that_prefer_this_slot: Set[Matchup] = None
        self.selected_matchup: Matchup = None

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return f"< {pretty_date} {pretty_time} at {self.location} >"
