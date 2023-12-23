from datetime import date, time

from versizzle.gameslot import Gameslot
from versizzle.matchup import Matchup
from versizzle.team import Team
import versizzle.utils as utils


class Blackout:
    def __init__(
        self, date: date, start: time, end: time, division: str, team_name: str
    ):
        if start is not None and end is not None and start > end:
            raise Exception("Tried to create blackout with start time after end time")

        self.date = date
        self.start = start
        self.end = end
        self.division = division
        self.team_name = team_name

    def prohibits_matchup_in_slot(self, matchup: Matchup, gameslot: Gameslot) -> bool:
        return self.prohibits_team_in_slot(
            matchup.team_a, gameslot
        ) or self.prohibits_team_in_slot(matchup.team_b, gameslot)

    def prohibits_team_in_slot(self, team: Team, gameslot: Gameslot) -> bool:
        return (
            (team.name == self.team_name or self.team_name is None)
            and (team.division == self.division or self.division is None)
            and gameslot.date == self.date
            and self._is_time_within_range(gameslot.time)
        )

    def _is_time_within_range(self, time: time):
        if self.start is None and self.end is None:
            return True
        if self.start is None:
            return time <= self.end
        if self.end is None:
            return time >= self.start
        return self.start <= time <= self.end

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)

        if self.start is None and self.end is None:
            time_string = "all day"
        else:
            start_string = (
                "start of day"
                if self.start is None
                else utils.prettify_time(self.start)
            )
            end_string = (
                "end of day" if self.end is None else utils.prettify_time(self.end)
            )
            time_string = f"from {start_string} to {end_string}"

        division_string = "ALL DIVISIONS" if self.division is None else self.division
        team_string = "ALL TEAMS" if self.team_name is None else self.team_name

        return f"< {pretty_date} {time_string} for {division_string} {team_string} >"
