from datetime import date, time
from typing import List, Set
import utils
import location


class Gameslot:
    def __init__(self, date: date, time: time, location: location.Location):
        # Declaring import here to prevent Python from complaining about circular
        # import. In future think about combining classes into one file to solve this.
        from matchup import Matchup

        self.date = date
        self.time = time
        self.location = location

        self.matchups_that_prefer_this_slot: Set[Matchup] = None
        self.selected_matchup: Matchup = None

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return f"< {pretty_date} {pretty_time} at {self.location} >"
