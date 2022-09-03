from datetime import date, time
from typing import List
import utils
import matchup


class Gameslot:
    def __init__(self, date: date, time: time, location: str):
        self.date = date
        self.time = time
        self.location = location

        self.matchups_that_prefer_this_slot: List[matchup.Matchup] = None
        self.selected_matchup: matchup.Matchup = None

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return f"< {pretty_date} {pretty_time} at {self.location} >"
