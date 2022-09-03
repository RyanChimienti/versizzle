from typing import List
from matchup import Matchup
from gameslot import Gameslot
from window_constraint import WindowConstraint


# Takes an already valid schedule and tries to make it better with small adjustments
class PostProcessor:
    def __init__(
        self,
        matchups: List[Matchup],
        gameslots: List[Gameslot],
        window_constraints: List[WindowConstraint],
    ):
        self.matchups: List[Matchup] = matchups
        self.gameslots: List[Gameslot] = gameslots
        self.window_constraints: List[WindowConstraint] = window_constraints

    def post_process(self):
        pass  # todo

    # The goal is to eliminate isolated matchups (AKA no other matchup is assigned to a
    # slot at the same location on the same date) because they are inconvenient for refs.
    # We prefer to do this by moving the isolated matchups to an existing block of games
    # ("pushing"), since that reduces the total block count by 1. However, if we cannot
    # push the isolated matchup to an existing block, we resort to pulling games from other
    # blocks of size 3 or greater. We alternate between these push and pull phases, pulling
    # only when we cannot push, and stopping when we can neither pull nor push.
    def try_to_fix_isolated_matchups(self):
        pass  # todo

    # Scans through every matchup once, attempting to push the isolated ones to an existing
    # block of games. Returns True if any matchups were successfully pushed
    def try_to_push_isolated_matchups(self, matchup: Matchup) -> bool:
        pass  # todo

    def try_to_pull_isolated_matchups(self, matchup: Matchup) -> bool:
        pass  # todo
