from datetime import date, time

from versizzle import utils
from versizzle.location import Location


class Gameslot:
    def __init__(self, date: date, time: time, location: Location):
        # Declaring import here to prevent circular import.
        from versizzle.matchup import Matchup

        self.date = date
        self.time = time
        self.location = location

        self.is_preassigned = False

        self.matchups_that_prefer_this_slot: set[Matchup] | None = None
        self.selected_matchup: Matchup | None = None

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return f"< {pretty_date} {pretty_time} at {self.location} >"
