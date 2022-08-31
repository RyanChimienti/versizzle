class Team:
    def __init__(self, division: str, name: str, home_location: str):
        self.division = division
        self.name = name
        self.home_location = home_location

    def __str__(self):
        return f"< {self.division} {self.name} >"

    def __eq__(self, other):
        return (
            self.division == other.division
            and self.name == other.name
            and self.home_location == other.home_location
        )