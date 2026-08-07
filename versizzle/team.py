from collections import defaultdict
from datetime import date

from versizzle.location import Location


class Team:
    def __init__(self, division: str, name: str, home_location: Location | None):
        # Declaring import here to prevent circular import.
        from versizzle.matchup import Matchup

        self.division: str = division
        self.name: str = name
        self.home_location: Location | None = home_location

        # All of the matchups (scheduled or not) that include this team
        self.matchups: list[Matchup] = []

        # Number of asymmetric matchups that include this team. A matchup is asymmetric if the teams have different home
        # locations. (In particular, a matchup where both teams lack a home location is symmetric, and a matchup where
        # only one team has a home location is asymmetric.)
        self.num_asymmetric_matchups: int = 0

        # The number of asymmetric matchups that include this team and have chosen a preferred home location.
        self.num_asymmetric_matchups_with_home_preference_chosen: int = 0

        # The number of asymmetric matchups that include this team and have chosen this team as their preferred home
        # team.
        self.num_asymmetric_matchups_preferring_this_team_as_home: int = 0

        # A map from dates to all of the games (AKA *scheduled* matchups) that this team is playing on that date
        self.games_by_date: dict[date, list[Matchup]] = defaultdict(list)

    def get_home_percentage(self) -> float:
        """
        Returns the ratio of currently scheduled home games to total games in season.
        """

        num_scheduled_home_games = len(
            list(
                filter(
                    lambda m: m.selected_gameslot is not None and m.selected_gameslot.location == self.home_location,
                    self.matchups,
                )
            )
        )

        return num_scheduled_home_games / len(self.matchups)

    def __str__(self):
        return f"< {self.division} {self.name} >"

    def __hash__(self):
        return hash((self.division, self.name))

    def __eq__(self, other):
        return self.division == other.division and self.name == other.name
