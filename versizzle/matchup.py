from typing import List, Tuple

from versizzle.team import Team
from versizzle.gameslot import Gameslot


class Matchup:
    def __init__(self, team_a: Team, team_b: Team):
        if team_a.division != team_b.division:
            raise Exception(
                "tried to create matchup between two teams of different divisions"
            )
        if team_a.name == team_b.name:
            raise Exception(f"tried to create matchup of {team_a} against itself")

        self.division: str = team_a.division
        self.team_a: Team = team_a
        self.team_b: Team = team_b

        self.is_preassigned = False

        self.preferred_home_team: Team = None

        self.preferred_gameslots: List[Gameslot] = None
        self.backup_gameslots: List[Gameslot] = None

        self.selected_gameslot: Gameslot = None
        self.selected_gameslot_is_preferred: bool = False

    def select_preferred_home_team(self, team: Team):
        if self.preferred_home_team is not None:
            raise Exception(
                "Can't assign a preferred home team to a matchup that already has one"
            )
        if team != self.team_a and team != self.team_b:
            raise Exception(
                "Preferred home team for a matchup must be one of the teams in the matchup"
            )

        self.preferred_home_team = team

        if team == self.team_a:
            self.team_a.num_preferred_home_games += 1
        else:
            self.team_b.num_preferred_home_games += 1

        self.team_a.num_matchups_with_home_preference_chosen += 1
        self.team_b.num_matchups_with_home_preference_chosen += 1

    def select_gameslot(self, gameslot: Gameslot):
        if self.selected_gameslot is not None:
            raise Exception("Must deselect gameslot before selecting a new one")
        if gameslot.selected_matchup is not None:
            raise Exception(
                "Tried to select gameslot that is selected by another matchup"
            )

        self.selected_gameslot = gameslot
        self.selected_gameslot_is_preferred = (
            self in gameslot.matchups_that_prefer_this_slot
        )

        self.team_a.games_by_date[gameslot.date].append(self)
        self.team_b.games_by_date[gameslot.date].append(self)
        gameslot.selected_matchup = self
        gameslot.location.num_games_by_date[gameslot.date] += 1

    def deselect_gameslot(self):
        if self.selected_gameslot is None:
            raise Exception("Tried to deselect gameslot when none is selected")

        prev_gameslot = self.selected_gameslot

        self.selected_gameslot = None
        self.selected_gameslot_is_preferred = False
        self.team_a.games_by_date[prev_gameslot.date].remove(self)
        self.team_b.games_by_date[prev_gameslot.date].remove(self)
        prev_gameslot.selected_matchup = None
        prev_gameslot.location.num_games_by_date[prev_gameslot.date] -= 1

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

    def is_isolated(self):
        """
        A matchup is called isolated if it's the only matchup at its location and on its
        day.
        """

        if self.selected_gameslot is None:
            raise Exception(
                "Can't check whether matchup is isolated without a selected gameslot"
            )

        gameslot = self.selected_gameslot
        return gameslot.location.num_games_by_date[gameslot.date] == 1

    def __str__(self):
        return f"< {self.division} - {self.team_a.name} vs {self.team_b.name} >"

    def __hash__(self):
        return hash((self.division, self.team_a.name, self.team_b.name))

    def __eq__(self, other):
        # It would not be sufficient to check that team_a and team_b match, since there
        # may be multiple distinct matchups which have the same team_a and team_b.
        return self is other
