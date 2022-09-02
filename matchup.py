from typing import Tuple
from team import Team


class Matchup:
    def __init__(self, team_a: Team, team_b: Team):
        if team_a.division != team_b.division:
            raise Exception(
                "tried to create matchup between two teams of different divisions"
            )
        if team_a.name == team_b.name:
            raise Exception(f"tried to create matchup of {team_a} against itself")

        self.division = team_a.division
        self.team_a = team_a
        self.team_b = team_b

        self.preferred_home_team = None
        self.preferred_locations = "undecided"
        self.preferred_gameslots = "undecided"
        self.backup_gameslots = "undecided"

        self.selected_gameslot = None

    def get_teams_in_home_away_order(self) -> Tuple[Team]:
        location = self.selected_gameslot.location
        if (
            location == self.team_a.home_location
            and location != self.team_b.home_location
        ):
            return self.team_a, self.team_b
        if (
            location == self.team_b.home_location
            and location != self.team_a.home_location
        ):
            return self.team_b, self.team_a

        home_team = self.preferred_home_team
        away_team = self.team_b if self.team_a == home_team else self.team_a
        return home_team, away_team

    def __str__(self):
        return f"< {self.division} - {self.team_a.name} vs {self.team_b.name} >"

    def __eq__(self, other):
        return self.team_a == other.team_a and self.team_b == other.team_b
