from datetime import date, time
import utils


class Gameslot:
    def __init__(self, date: date, time: time, location: str):
        self.date = date
        self.time = time
        self.location = location

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return f"< {pretty_date} {pretty_time} at {self.location} >"
