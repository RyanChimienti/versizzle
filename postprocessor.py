from collections import defaultdict
from typing import Dict, List, Tuple
from location import Location
from matchup import Matchup
from gameslot import Gameslot
import datetime
from window_constraint import WindowConstraint
from itertools import permutations
from more_itertools import first_true
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
        self.minimize_isolated_matchups()
        self.remove_awkward_gaps()
        print("Post-processing complete.")

    def minimize_isolated_matchups(self):
        """
        This method attempts to rearrange the matchups to reduce the number of isolated
        matchups, subject to some constraints:

        1. If a matchup got its preferred location, we won't move it to a different
        location.

        2. We won't introduce any window constraint violations.

        3. We will respect preassignments.

        A matchup is called isolated if it's the only matchup at its location and on its
        day.
        """

        print("Minimizing isolated matchups.")

        initially_isolated_matchups = [m for m in self.matchups if m.is_isolated()]
        initial_num_isolated = len(initially_isolated_matchups)

        for matchup in initially_isolated_matchups:
            if not matchup.is_isolated():
                # The matchup may have become nonisolated during the processing of an
                # earlier isolated matchup. In that case, our work has been done for us.
                continue

            self.try_push_matchup(matchup) or self.try_pull_to_matchup(matchup)

        final_num_isolated = len([m for m in self.matchups if m.is_isolated()])

        print(
            f"Minimized isolated matchups: {initial_num_isolated} -> {final_num_isolated}"
        )

    def try_push_matchup(self, matchup: Matchup):
        """
        Takes an isolated matchup and attempts to unisolate it by assigning it to a
        different gameslot ("pushing" it). Returns a boolean for whether this was
        successful.
        """

        if not matchup.is_isolated():
            raise Exception("This method expects an isolated matchup")

        if matchup.is_preassigned:
            # A preassigned matchup cannot be moved
            return False

        original_slot = matchup.selected_gameslot

        if matchup.selected_gameslot_is_preferred:
            candidate_slots = matchup.preferred_gameslots
        else:
            candidate_slots = matchup.preferred_gameslots + matchup.backup_gameslots

        matchup.deselect_gameslot()

        for slot in candidate_slots:
            if slot.selected_matchup is not None:
                continue

            num_games_on_date = slot.location.num_games_by_date[slot.date]
            if num_games_on_date == 0:
                # Our matchup would still be isolated in this slot
                continue

            if not all(
                wc.is_satisfied_by_selection(matchup, slot)
                for wc in self.window_constraints
            ):
                # Moving the matchup here would cause a window constraint violation
                continue

            matchup.select_gameslot(slot)
            return True

        matchup.select_gameslot(original_slot)
        return False

    def try_pull_to_matchup(self, matchup: Matchup):
        """
        Takes an isolated matchup and attempts to unisolate it by moving another
        matchup to the same location and day. Returns a boolean for whether this was
        successful.
        """

        if not matchup.is_isolated():
            raise Exception("This method expects an isolated matchup")

        for candidate_matchup in self.matchups:
            if candidate_matchup == matchup:
                continue

            if candidate_matchup.is_preassigned:
                # A preassigned matchup cannot be moved
                continue

            original_slot = candidate_matchup.selected_gameslot
            if original_slot.location.num_games_by_date[original_slot.date] == 2:
                # Pulling this candidate would create another isolated matchup
                continue

            if candidate_matchup.selected_gameslot_is_preferred:
                candidate_slots = candidate_matchup.preferred_gameslots
            else:
                candidate_slots = (
                    candidate_matchup.preferred_gameslots
                    + candidate_matchup.backup_gameslots
                )

            candidate_slot = first_true(
                candidate_slots,
                pred=lambda s: (
                    s.selected_matchup is None
                    and s.location == matchup.selected_gameslot.location
                    and s.date == matchup.selected_gameslot.date
                ),
            )

            if candidate_slot is None:
                continue

            candidate_matchup.deselect_gameslot()

            if not all(
                wc.is_satisfied_by_selection(candidate_matchup, candidate_slot)
                for wc in self.window_constraints
            ):
                # Moving the matchup here would cause a window constraint violation
                candidate_matchup.select_gameslot(original_slot)
                continue

            candidate_matchup.select_gameslot(candidate_slot)
            return True

        return False

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
