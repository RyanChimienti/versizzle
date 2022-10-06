from typing import List
from gameslot import Gameslot
from location import Location
from matchup import Matchup
from datetime import date, time

from team import Team


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

    def assign(self, matchups: List[Matchup]):
        candidate_matchups: List[Matchup] = []
        for matchup in matchups:
            matchup_has_these_teams = (
                matchup.team_a == self.team_a and matchup.team_b == self.team_b
            ) or (matchup.team_a == self.team_b and matchup.team_b == self.team_a)

            if matchup_has_these_teams and matchup.selected_gameslot is None:
                candidate_matchups.append(matchup)

        for cand_matchup in candidate_matchups:
            for gameslot in cand_matchup.preferred_gameslots:
                if (
                    gameslot.selected_matchup is None
                    and gameslot.location == self.location
                    and gameslot.time == self.time
                    and gameslot.date == self.date
                ):
                    cand_matchup.select_gameslot(gameslot)
                    return

        for cand_matchup in candidate_matchups:
            for gameslot in cand_matchup.backup_gameslots:
                if (
                    gameslot.selected_matchup is None
                    and gameslot.location == self.location
                    and gameslot.time == self.time
                    and gameslot.date == self.date
                ):
                    cand_matchup.select_gameslot(gameslot)
                    return

        raise Exception("Error: unable to perform preassignment")
