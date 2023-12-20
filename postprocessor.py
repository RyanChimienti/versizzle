from collections import defaultdict
from typing import Dict, List, Tuple
from location import Location
from matchup import Matchup
from gameslot import Gameslot
import datetime
from window_constraint import WindowConstraint
from itertools import permutations
import utils


# Takes an already valid schedule and tries to make it better with small adjustments.
# Post-processing will never make a schedule invalid or worse than before.
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
        print("Post-processing started.")
        self.remove_awkward_gaps()
        print("Post-processing complete.")

    # When multiple games occur at the same location on the same day, there should not be
    # any gaps between those games. This method removes the gaps, making the games
    # consecutive.
    def remove_awkward_gaps(self):
        print("Removing awkward gaps between games.")

        gameslots_by_block: Dict[Tuple[datetime.date, Location], List[Gameslot]]
        gameslots_by_block = defaultdict(list)

        for g in self.gameslots:
            gameslots_by_block[g.date, g.location].append(g)

        failed_blocks: List[Tuple[datetime.date, Location]] = []

        for date, location in sorted(gameslots_by_block.keys()):
            gameslots_in_block = gameslots_by_block[date, location]

            success = self.squeeze_matchups_in_block(gameslots_in_block)
            if not success:
                failed_blocks.append((date, location))

        if failed_blocks:
            print(
                "Removing awkward gaps FAILED in some cases! "
                + "The following blocks require manual adjustment:"
            )
            for date, location in failed_blocks:
                print(f"{utils.prettify_date(date)} at {location}")
        else:
            print(
                "Removing awkward gaps was successful in all cases. "
                + "No manual adjustment required."
            )

    # Takes all gameslots for a particular location and day. Attempts to reassign their
    # matchups among the gameslots such that all of the matchups are scheduled
    # consecutively. Returns True if such an assignment is found and performed.
    # Otherwise returns False and leaves the assignments unchanged.
    def squeeze_matchups_in_block(self, gameslots_in_block: List[Gameslot]) -> bool:
        date, location = gameslots_in_block[0].date, gameslots_in_block[0].location
        pretty_date = utils.prettify_date(date)

        gameslots_in_block.sort(key=lambda g: g.time)

        matchups_in_block: List[Matchup] = []
        for g in gameslots_in_block:
            if g.selected_matchup is not None:
                matchups_in_block.append(g.selected_matchup)

        if not matchups_in_block:
            return True

        attempt_number = 1
        max_starting_slot_index = len(gameslots_in_block) - len(matchups_in_block)
        for s in range(max_starting_slot_index + 1):
            for matchup_permutation in permutations(matchups_in_block):
                if all(
                    g in m.preferred_gameslots or g in m.backup_gameslots
                    for m, g in zip(matchup_permutation, gameslots_in_block[s:])
                ):
                    for matchup in matchup_permutation:
                        matchup.deselect_gameslot()
                    for matchup, gameslot in zip(
                        matchup_permutation, gameslots_in_block[s:]
                    ):
                        matchup.select_gameslot(gameslot)

                    if attempt_number > 1:
                        print(
                            f"Took {attempt_number} tries to squeeze matchups "
                            + f"on {pretty_date} at {location}."
                        )
                    return True

                attempt_number += 1

        print(f"Squeezing matchups FAILED on {pretty_date} at {location}.")
        return False
