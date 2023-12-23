from typing import List
from datetime import date, time

from versizzle.blackout import Blackout
from versizzle.gameslot import Gameslot
from versizzle.location import Location
from versizzle.matchup import Matchup
from versizzle.team import Team
import versizzle.utils as utils


class Preassignment:
    def __init__(
        self,
        date: date,
        time: time,
        location: Location,
        team_a: Team,
        team_b: Team,
    ):
        self.date = date
        self.time = time
        self.location = location
        self.team_a = team_a
        self.team_b = team_b

    def assign(
        self,
        matchups: List[Matchup],
        gameslots: List[Gameslot],
        blackouts: List[Blackout],
    ):
        matchup_to_use = None
        for matchup in matchups:
            if self.describes_matchup(matchup) and matchup.selected_gameslot is None:
                matchup_to_use = matchup
                break

        if matchup_to_use is None:
            raise Exception(f"Could not find a matchup to use for preassignment {self}")

        gameslot_to_use = None
        for gameslot in gameslots:
            if self.describes_gameslot(gameslot) and gameslot.selected_matchup is None:
                gameslot_to_use = gameslot
                break

        if gameslot_to_use is None:
            raise Exception(
                f"Could not find a gameslot to use for preassignment {self}"
            )

        if any(
            b.prohibits_matchup_in_slot(matchup_to_use, gameslot_to_use)
            for b in blackouts
        ):
            raise Exception(f"Preassignment {self} is prohibited by a blackout")

        matchup_to_use.is_preassigned = True
        matchup_to_use.preferred_gameslots = [gameslot_to_use]
        matchup_to_use.backup_gameslots = []

        gameslot_to_use.is_preassigned = True
        gameslot_to_use.matchups_that_prefer_this_slot = {matchup_to_use}

        matchup_to_use.select_gameslot(gameslot_to_use)

    def describes_matchup(self, matchup: Matchup):
        return (matchup.team_a == self.team_a and matchup.team_b == self.team_b) or (
            matchup.team_a == self.team_b and matchup.team_b == self.team_a
        )

    def describes_gameslot(self, gameslot: Gameslot):
        return (
            gameslot.date == self.date
            and gameslot.time == self.time
            and gameslot.location == self.location
        )

    def __str__(self):
        pretty_date = utils.prettify_date(self.date)
        pretty_time = utils.prettify_time(self.time)

        return (
            f"< {self.team_a.division} - "
            + f"{self.team_a.name} vs {self.team_b.name} - "
            + f"{pretty_date} {pretty_time} at {self.location} >"
        )
