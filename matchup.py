from team import Team


class Matchup:
    def __init__(self, team_a: Team, team_b: Team):
        if team_a.division != team_b.division:
            raise Exception(
                "tried to create matchup between two teams of different divisions"
            )

        self.division = team_a.division
        self.team_a = team_a
        self.team_b = team_b

    def __str__(self):
        return f"< {self.division} - {self.team_a.name} vs {self.team_b.name} >"

    def __eq__(self, other):
        return self.team_a == other.team_a and self.team_b == other.team_b
