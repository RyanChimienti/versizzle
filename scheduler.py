import calendar
from collections import defaultdict
import csv
from datetime import datetime, timedelta
import os
from typing import Dict, List, Set, Tuple
from blackout import Blackout
from gameslot import Gameslot
from location import Location
from matchup import Matchup
from preassignment import Preassignment
from postprocessor import PostProcessor
from window_constraint import WindowConstraint
from team import Team
import utils
import random


divisions_to_counts: Dict[str, int] = defaultdict(
    int
)  # maps division -> # of teams in division
teams: Dict[Tuple[str, str], Team] = dict()  # maps (division, team name) -> team object
matchups: List[Matchup] = []
gameslots: List[Gameslot] = []
locations: Dict[str, Location] = dict()  # maps location name -> location object
blackouts: List[Blackout] = []
preassignments: List[Preassignment] = []

backup_selection_dead_ends: int
backup_selection_depth: int


def generate_schedule(
    input_dir_path: str,
    output_dir_path: str,
    random_seed: int,
    window_constraints: List[WindowConstraint],
    scarce_location_names: List[str],
    is_test_run_for_seed: bool = False,
):
    clear_globals()

    random.seed(random_seed)

    ingest_files(input_dir_path, scarce_location_names)

    do_preassignments()
    assign_preferred_home_teams_to_matchups()
    assign_candidate_gameslots_to_matchups()

    success = select_gameslots_for_matchups(window_constraints)

    if not success:
        print("Failed to find a schedule. Try relaxing your window constraints.")
        return

    print("A valid schedule was found!")

    PostProcessor(matchups, gameslots, window_constraints).post_process()

    if is_test_run_for_seed:
        log_seed_info_from_test_run(output_dir_path, random_seed)
        return

    # print_master_schedule()
    # print_breakout_schedules()
    create_pasteable_schedule_file(output_dir_path)
    print_non_preferred_gameslot_metrics()
    print_block_size_metrics()
    print_weekday_metrics()
    print_consecutive_game_day_metrics()


def clear_globals():
    global divisions_to_counts
    global teams
    global matchups
    global gameslots
    global locations
    global blackouts
    global preassignments
    global backup_selection_dead_ends
    global backup_selection_depth

    divisions_to_counts = defaultdict(int)
    teams = dict()
    matchups = []
    gameslots = []
    locations = dict()  # maps location name -> location object
    blackouts = []
    preassignments = []

    backup_selection_dead_ends = 0
    backup_selection_depth = 0


def do_preassignments():
    print(f"Performing {len(preassignments)} preassignments")

    for preassignment in preassignments:
        preassignment.assign(matchups, gameslots, blackouts)

    print("Preassignments complete.")
    print()


def select_gameslots_for_matchups(window_constraints: List[WindowConstraint]):
    print("Preferred selection phase started.")

    select_preferred_gameslots(window_constraints)

    print("Preferred selection phase complete.")

    matchups_using_backup_slots = list(
        filter(lambda m: m.selected_gameslot is None, matchups)
    )

    print(
        f"Number of matchups that did not get preferred selection: {len(matchups_using_backup_slots)}"
    )
    print("Block sizes after preferred selection phase:")
    print()
    print_block_size_metrics()

    print("Backup selection phase started.")

    matchups_using_backup_slots.sort(key=lambda m: len(m.backup_gameslots))
    success = select_backup_gameslots(
        matchups_using_backup_slots, 0, window_constraints
    )

    print(f"Backup selection completed with {backup_selection_dead_ends} dead ends.")

    return success


def select_preferred_gameslots(window_constraints: List[WindowConstraint]):
    # Randomize processing order for matchups. If we don't do this, matchups near the end
    # of matchups.csv get processed later, meaning their preferences are less likely to be
    # satisified.
    unprocessed_matchups = [m for m in matchups if m.selected_gameslot is None]
    random.shuffle(unprocessed_matchups)

    print("Starting step 1 of preferred selection phase (same home matchups)")

    # If both teams in a matchup have the same home location, it would be egregious
    # for them to have to travel elsewhere. So those matchups are processed early to
    # make sure they get their preferred location.
    same_home_matchups = [
        m
        for m in unprocessed_matchups
        if m.team_a.home_location == m.team_b.home_location
    ]
    print(f"{len(same_home_matchups)} same home matchups to process")
    for matchup in same_home_matchups:
        select_preferred_gameslot_for_matchup(matchup, window_constraints)
        unprocessed_matchups.remove(matchup)

    print("Starting step 2 of preferred selection phase (scarce home matchups)")

    # Next we process the matchups with scarce home locations. A location is scarce if it
    # does not have enough gameslots to comfortably give all the teams with that home
    # location the desired number of home games. When a location is scarce, there is a
    # risk that one team with that home location gets many more home games than another.
    # We avoid this by always processing the matchup where the preferred home team has
    # the smallest fraction of home games.
    scarce_home_matchups = [
        m
        for m in unprocessed_matchups
        if m.preferred_home_team is not None
        and m.preferred_home_team.home_location is not None
        and m.preferred_home_team.home_location.is_scarce
    ]
    print(
        f"Scarce location(s): {', '.join([str(l) for l in locations.values() if l.is_scarce])}"
    )
    print(f"{len(scarce_home_matchups)} scarce home matchups to process")
    unprocessed_scarce_home_matchups = scarce_home_matchups.copy()
    while unprocessed_scarce_home_matchups:
        if len(unprocessed_scarce_home_matchups) % 10 == 0:
            print(f"{len(unprocessed_scarce_home_matchups)} remaining")

        smallest_home_percentage = min(
            m.preferred_home_team.get_home_percentage()
            for m in unprocessed_scarce_home_matchups
        )
        matchups_with_smallest_home_percentage = [
            m
            for m in unprocessed_scarce_home_matchups
            if abs(
                m.preferred_home_team.get_home_percentage() - smallest_home_percentage
            )
            < 0.0001
        ]
        matchup_to_process = get_most_constrained_matchup_in_list(
            matchups_with_smallest_home_percentage, window_constraints
        )
        select_preferred_gameslot_for_matchup(matchup_to_process, window_constraints)
        unprocessed_scarce_home_matchups.remove(matchup_to_process)
        unprocessed_matchups.remove(matchup_to_process)

    print("Starting step 3 of preferred selection phase (ordinary matchups)")

    # Finally we process the matchups with no special properties.
    print(f"{len(unprocessed_matchups)} ordinary matchups to process")
    while unprocessed_matchups:
        if len(unprocessed_matchups) % 10 == 0:
            print(f"{len(unprocessed_matchups)} remaining")

        matchup_to_process = get_most_constrained_matchup_in_list(
            unprocessed_matchups, window_constraints
        )
        select_preferred_gameslot_for_matchup(matchup_to_process, window_constraints)
        unprocessed_matchups.remove(matchup_to_process)


def get_most_constrained_matchup_in_list(
    matchup_list: List[Matchup], window_constraints: List[WindowConstraint]
) -> Matchup:
    if not matchup_list:
        raise Exception("Called get_most_constrained_matchup_in_list on empty list")

    most_constrained_matchup = None
    min_slot_availability_score = float("inf")

    for matchup in matchup_list:
        score = get_slot_availability_score(matchup, window_constraints)
        if score < min_slot_availability_score:
            most_constrained_matchup = matchup
            min_slot_availability_score = score

    return most_constrained_matchup


# Returns a score indicating how many preferred gameslots are still available for the given
# matchup.
#
# This score helps us to decide the order in which to process matchups. The idea is that
# if a matchup has many preferred slots, it's unlikely that an earlier matchup will take
# all of them. Therefore it's safe to consider it at the end. On the other hand, if a
# matchup has few preferred slots, then it's in danger of losing its preferred slots, so
# it should be considered early.
def get_slot_availability_score(
    matchup: Matchup, window_constraints: List[WindowConstraint]
) -> float:
    if matchup.selected_gameslot is not None:
        raise Exception(
            "Tried to calculate slot availability score for matchup "
            + "that has already selected a gameslot."
        )

    return len(
        [
            g
            for g in matchup.preferred_gameslots
            if g.selected_matchup is None
            and all(w.is_satisfied_by_selection(matchup, g) for w in window_constraints)
        ]
    )


# If the given matchup has at least one preferred gameslot that can be selected,
# selects the best preferred gameslot. Returns True if a gameslot was selected, False if
# not.
def select_preferred_gameslot_for_matchup(
    matchup: Matchup, window_constraints: List[WindowConstraint]
) -> bool:
    for reuse_location in True, False:
        for use_weekend in True, False:
            for avoid_consecutive_days in True, False:
                for gameslot in matchup.preferred_gameslots:
                    if gameslot.selected_matchup is not None:
                        continue
                    if (
                        reuse_location
                        and gameslot.location.num_games_by_date[gameslot.date] == 0
                    ):
                        continue
                    if (
                        not reuse_location
                        and gameslot.location.num_games_by_date[gameslot.date] != 0
                    ):
                        continue
                    if use_weekend and gameslot.date.weekday() not in [4, 5]:
                        continue
                    if not use_weekend and gameslot.date.weekday() in [4, 5]:
                        continue
                    if (
                        avoid_consecutive_days
                        and selection_will_create_consecutive_game_days(
                            matchup, gameslot
                        )
                    ):
                        continue
                    if (
                        not avoid_consecutive_days
                        and not selection_will_create_consecutive_game_days(
                            matchup, gameslot
                        )
                    ):
                        continue
                    if not all(
                        w.is_satisfied_by_selection(matchup, gameslot)
                        for w in window_constraints
                    ):
                        continue

                    matchup.select_gameslot(gameslot)
                    return True

    return False


def select_backup_gameslots(
    matchups_using_backup_slots: List[Matchup],
    start: int,
    window_constraints: List[WindowConstraint],
):
    global backup_selection_dead_ends
    global backup_selection_depth
    if start == 0:
        backup_selection_dead_ends = 0
        backup_selection_depth = 0

    if start > backup_selection_depth:
        backup_selection_depth = start
        print(
            f"New depth reached: {backup_selection_depth} / {len(matchups_using_backup_slots)}"
        )

    if backup_selection_dead_ends >= 10000:
        # It's taking too long. We assume it will not complete in a reasonable time.
        return False

    if start == len(matchups_using_backup_slots):
        return True

    matchup = matchups_using_backup_slots[start]

    for reuse_single_use_location, reuse_multi_use_location in (
        (True, False),
        (False, True),
        (False, False),
    ):
        for give_nonpreferred_team_home in True, False:
            for use_weekend in True, False:
                for avoid_consecutive_days in True, False:
                    for gameslot in matchup.backup_gameslots:
                        if gameslot.selected_matchup is not None:
                            continue
                        if (
                            reuse_single_use_location
                            and gameslot.location.num_games_by_date[gameslot.date] != 1
                        ):
                            continue
                        if (
                            not reuse_single_use_location
                            and gameslot.location.num_games_by_date[gameslot.date] == 1
                        ):
                            continue
                        if (
                            reuse_multi_use_location
                            and gameslot.location.num_games_by_date[gameslot.date] <= 1
                        ):
                            continue
                        if (
                            not reuse_multi_use_location
                            and gameslot.location.num_games_by_date[gameslot.date] > 1
                        ):
                            continue
                        if (
                            give_nonpreferred_team_home
                            and not selection_gives_either_team_home(matchup, gameslot)
                        ):
                            continue
                        if (
                            not give_nonpreferred_team_home
                            and selection_gives_either_team_home(matchup, gameslot)
                        ):
                            continue
                        if use_weekend and gameslot.date.weekday() not in [4, 5]:
                            continue
                        if not use_weekend and gameslot.date.weekday() in [4, 5]:
                            continue
                        if (
                            avoid_consecutive_days
                            and selection_will_create_consecutive_game_days(
                                matchup, gameslot
                            )
                        ):
                            continue
                        if (
                            not avoid_consecutive_days
                            and not selection_will_create_consecutive_game_days(
                                matchup, gameslot
                            )
                        ):
                            continue
                        if not all(
                            w.is_satisfied_by_selection(matchup, gameslot)
                            for w in window_constraints
                        ):
                            continue

                        matchup.select_gameslot(gameslot)

                        if select_backup_gameslots(
                            matchups_using_backup_slots, start + 1, window_constraints
                        ):
                            return True

                        matchup.deselect_gameslot()

    backup_selection_dead_ends += 1
    if backup_selection_dead_ends % 1000 == 0:
        print(f"Backup selection has hit {backup_selection_dead_ends} dead ends")

    return False


def selection_gives_either_team_home(matchup: Matchup, gameslot: Gameslot):
    return (
        gameslot.location == matchup.team_a.home_location
        or gameslot.location == matchup.team_b.home_location
    )


def selection_will_create_consecutive_game_days(matchup: Matchup, gameslot: Gameslot):
    team_a, team_b = matchup.team_a, matchup.team_b

    prev_day = gameslot.date - timedelta(days=1)
    next_day = gameslot.date + timedelta(days=1)

    return (
        team_a.games_by_date[prev_day]
        or team_a.games_by_date[next_day]
        or team_b.games_by_date[prev_day]
        or team_b.games_by_date[next_day]
    )


def assign_candidate_gameslots_to_matchups():
    for g in gameslots:
        if g.is_preassigned:
            continue

        g.matchups_that_prefer_this_slot = set()

    for m in matchups:
        if m.is_preassigned:
            continue

        m.preferred_gameslots = []
        m.backup_gameslots = []

        for g in gameslots:
            if g.is_preassigned:
                continue
            if any(b.prohibits_matchup_in_slot(m, g) for b in blackouts):
                continue

            if m.preferred_home_team.home_location == g.location:
                m.preferred_gameslots.append(g)
                g.matchups_that_prefer_this_slot.add(m)
            else:
                m.backup_gameslots.append(g)

        random.shuffle(m.preferred_gameslots)
        random.shuffle(m.backup_gameslots)


def assign_preferred_home_teams_to_matchups():
    for d in divisions_to_counts:
        division_matchups = [m for m in matchups if m.division == d]

        team_pairs_to_matchups = defaultdict(list)
        for m in division_matchups:
            team_pair = tuple(sorted([m.team_a.name, m.team_b.name]))
            team_pairs_to_matchups[team_pair].append(m)

        groups_of_identical_matchups = team_pairs_to_matchups.values()

        for group in groups_of_identical_matchups:
            first_team, second_team = group[0].team_a, group[0].team_b

            num_preassigned_home_games_for_first_team = 0
            num_preassigned_home_games_for_second_team = 0

            for matchup in group:
                if matchup.is_preassigned:
                    if matchup.selected_gameslot.location == first_team.home_location:
                        matchup.select_preferred_home_team(first_team)
                        num_preassigned_home_games_for_first_team += 1
                    elif (
                        matchup.selected_gameslot.location == second_team.home_location
                    ):
                        matchup.select_preferred_home_team(second_team)
                        num_preassigned_home_games_for_second_team += 1

            team_with_fewer_preassigned_home_games = (
                first_team
                if num_preassigned_home_games_for_first_team
                < num_preassigned_home_games_for_second_team
                else second_team
            )
            difference_in_preassigned_home = abs(
                num_preassigned_home_games_for_first_team
                - num_preassigned_home_games_for_second_team
            )

            remaining_nonpreassigned_matchups = [
                m for m in group if not m.is_preassigned
            ]
            while remaining_nonpreassigned_matchups and difference_in_preassigned_home:
                matchup = remaining_nonpreassigned_matchups.pop()
                matchup.select_preferred_home_team(
                    team_with_fewer_preassigned_home_games
                )
                difference_in_preassigned_home -= 1

            for _ in range(len(remaining_nonpreassigned_matchups) // 2):
                matchup_1 = remaining_nonpreassigned_matchups.pop()
                matchup_1.select_preferred_home_team(first_team)

                matchup_2 = remaining_nonpreassigned_matchups.pop()
                matchup_2.select_preferred_home_team(second_team)

        # In each matchup group, there may be 1 nonpreassigned matchup that hasn't
        # received a home team. These matchups are special because, unlike the matchups
        # processed so far, they have no natural home team. Therefore we can assign them
        # home teams in whatever way best balances the number of home games for each team.
        for group in groups_of_identical_matchups:
            for matchup in group:
                if not matchup.is_preassigned and matchup.preferred_home_team is None:
                    home_team = get_team_with_lower_preferred_home_ratio(
                        matchup.team_a, matchup.team_b
                    )
                    matchup.select_preferred_home_team(home_team)
                    break

        # Finally, we address the matchups that are preassigned, but to a location that
        # is neither team's home. We give them preferred home teams so that all matchups
        # have preferred home teams, but really it's futile because they have already been
        # preassigned to a different location.
        for group in groups_of_identical_matchups:
            for matchup in group:
                if (
                    matchup.is_preassigned
                    and matchup.selected_gameslot.location
                    != matchup.team_a.home_location
                    and matchup.selected_gameslot.location
                    != matchup.team_b.home_location
                ):
                    home_team = get_team_with_lower_preferred_home_ratio(
                        matchup.team_a, matchup.team_b
                    )
                    matchup.select_preferred_home_team(home_team)

    print_home_preference_metrics()


def get_team_with_lower_preferred_home_ratio(team_1: Team, team_2: Team):
    team_1_home_ratio = (
        0.5
        if team_1.num_matchups_with_home_preference_chosen == 0
        else team_1.num_preferred_home_games
        / float(team_1.num_matchups_with_home_preference_chosen)
    )
    team_2_home_ratio = (
        0.5
        if team_2.num_matchups_with_home_preference_chosen == 0
        else team_2.num_preferred_home_games
        / float(team_2.num_matchups_with_home_preference_chosen)
    )
    if abs(team_1_home_ratio - team_2_home_ratio) < 0.0001:
        return random.choice([team_1, team_2])

    return team_1 if team_1_home_ratio < team_2_home_ratio else team_2


def print_home_preference_metrics():
    table = [
        ["# of Preferred Home Games", "# of Teams With That Many"],
        ["-------------------------", "-------------------------"],
    ]

    num_preferred_home_games_to_num_teams = defaultdict(int)

    for t in teams.values():
        num_preferred_home_games_to_num_teams[t.num_preferred_home_games] += 1

    for num_games, num_teams in sorted(num_preferred_home_games_to_num_teams.items()):
        table.append([num_games, num_teams])

    utils.pretty_print_table(table)
    print()


def ingest_files(
    directory_path: str,
    scarce_location_names: List[str],
):
    ingest_teams_file(directory_path, scarce_location_names)
    ingest_matchups_file(directory_path)
    ingest_gameslots_file(directory_path, scarce_location_names)
    ingest_blackouts_file(directory_path)
    ingest_preassignments_file(directory_path)


def ingest_teams_file(
    directory_path: str,
    scarce_location_names: List[str],
):
    file_path = "{}/teams.csv".format(directory_path)
    with open(file_path, "r") as file:
        lines = list(csv.reader(file))
        if len(lines) == 0:
            raise Exception("teams.csv must contain at least 1 line (a header)")

        first_row = lines[0]
        if not (
            len(first_row) == 3
            and first_row[0] == "division"
            and first_row[1] == "team"
            and first_row[2] == "home location"
        ):
            raise Exception(
                "teams.csv should have 3 columns: 'division', 'team', and 'home location'"
            )
        for row in lines[1:]:
            division, name, home_location_name = row
            if home_location_name == "NONE":
                home_location_obj = None
            elif home_location_name in locations:
                home_location_obj = locations[home_location_name]
            else:
                home_location_is_scarce = home_location_name in scarce_location_names
                home_location_obj = Location(
                    home_location_name, home_location_is_scarce
                )
                locations[home_location_name] = home_location_obj

            teams[(division, name)] = Team(division, name, home_location_obj)
            divisions_to_counts[division] += 1

    print("======================== ingested divisions: ========================")
    for d, count in divisions_to_counts.items():
        print(f"{d} ({count} teams)")
    print()
    print("======================== ingested teams: ========================")
    for t in teams.values():
        print(t)
    print()


def ingest_matchups_file(directory_path):
    file_path = "{}/matchups.csv".format(directory_path)
    with open(file_path, "r") as file:
        lines = list(csv.reader(file))
        if len(lines) == 0:
            raise Exception("matchups.csv must contain at least 1 line (a header)")

        first_row = lines[0]
        if not (
            len(first_row) == 3
            and first_row[0] == "division"
            and first_row[1] == "team a"
            and first_row[2] == "team b"
        ):
            raise Exception(
                "matchups.csv should have 3 columns: 'division', 'team a', and 'team b'"
            )
        for row in lines[1:]:
            division, team_a_name, team_b_name = row
            team_a = teams[(division, team_a_name)]
            team_b = teams[(division, team_b_name)]

            matchup = Matchup(team_a, team_b)

            matchups.append(matchup)

            team_a.matchups.append(matchup)
            team_b.matchups.append(matchup)

    print("======================== ingested matchups: ========================")
    if len(matchups) <= 20:
        for m in matchups:
            print(m)
    else:
        for m in matchups[:10]:
            print(m)
        print("...{} more...".format(len(matchups) - 20))
        for m in matchups[-10:]:
            print(m)
    print()


def ingest_gameslots_file(directory_path: str, scarce_location_names: List[str]):
    file_path = "{}/gameslots.csv".format(directory_path)
    with open(file_path, "r") as file:
        lines = list(csv.reader(file))
        if len(lines) == 0:
            raise Exception("gameslots.csv must contain at least 1 lines (a header)")

        first_row = lines[0]
        if not (
            len(first_row) == 3
            and first_row[0] == "date"
            and first_row[1] == "time"
            and first_row[2] == "location"
        ):
            raise Exception(
                "gameslots.csv should have 3 columns: 'date', 'time', and 'location'"
            )
        for row in lines[1:]:
            date_string, time_string, location_name = row

            if location_name in locations:
                location_obj = locations[location_name]
            else:
                location_is_scarce = location_name in scarce_location_names
                location_obj = Location(location_name, location_is_scarce)
                locations[location_name] = location_obj

            datetime_string = date_string + " " + time_string
            datetime_obj = datetime.strptime(datetime_string, "%m/%d/%Y %I:%M%p")

            gameslots.append(
                Gameslot(datetime_obj.date(), datetime_obj.time(), location_obj)
            )
            location_obj.num_gameslots += 1

    print("======================== ingested gameslots: ========================")
    if len(gameslots) <= 20:
        for g in gameslots:
            print(g)
    else:
        for g in gameslots[:10]:
            print(g)
        print("...{} more...".format(len(gameslots) - 20))
        for g in gameslots[-10:]:
            print(g)
    print()
    print("======================== ingested locations: ========================")
    for l in locations.values():
        print(f"{l} ({l.num_gameslots} gameslots)")
    print()


def ingest_blackouts_file(directory_path):
    file_path = "{}/blackouts.csv".format(directory_path)
    with open(file_path, "r") as file:
        lines = list(csv.reader(file))
        if len(lines) == 0:
            raise Exception("blackouts.csv must contain at least 1 line (a header)")

        first_row = lines[0]
        if not (
            len(first_row) == 5
            and first_row[0] == "date"
            and first_row[1] == "start time"
            and first_row[2] == "end time"
            and first_row[3] == "division"
            and first_row[4] == "team"
        ):
            raise Exception(
                "blackouts.csv should have 5 columns: 'date', 'start time', 'end time', 'division', and 'team'"
            )
        for row in lines[1:]:
            date_string, start_time_string, end_time_string, division, team_name = row

            date_obj = datetime.strptime(date_string, "%m/%d/%Y").date()

            if start_time_string == "-":
                start_time_obj = None
            else:
                start_time_obj = datetime.strptime(start_time_string, "%I:%M%p").time()

            if end_time_string == "-":
                end_time_obj = None
            else:
                end_time_obj = datetime.strptime(end_time_string, "%I:%M%p").time()

            division_obj = None if division == "ALL" else division

            team_name_obj = None if team_name == "ALL" else team_name

            blackouts.append(
                Blackout(
                    date_obj, start_time_obj, end_time_obj, division_obj, team_name_obj
                )
            )

    print("======================== ingested blackouts: ========================")
    if len(blackouts) <= 20:
        for b in blackouts:
            print(b)
    else:
        for b in blackouts[:10]:
            print(b)
        print("...{} more...".format(len(blackouts) - 20))
        for b in blackouts[-10:]:
            print(b)
    print()


def ingest_preassignments_file(directory_path):
    file_path = "{}/preassignments.csv".format(directory_path)
    with open(file_path, "r") as file:
        lines = list(csv.reader(file))
        if len(lines) == 0:
            raise Exception(
                "preassignments.csv must contain at least 1 line (a header)"
            )

        first_row = lines[0]
        if not (
            len(first_row) == 6
            and first_row[0] == "date"
            and first_row[1] == "time"
            and first_row[2] == "location"
            and first_row[3] == "division"
            and first_row[4] == "team a"
            and first_row[5] == "team b"
        ):
            raise Exception(
                "preassignments.csv should have 6 columns: 'date', 'time',"
                + " 'location', 'division', 'team a', and 'team b'"
            )

        for row in lines[1:]:
            date_str, time_str, location_str, division, team_a_name, team_b_name = row

            date_obj = datetime.strptime(date_str, "%m/%d/%Y").date()
            time_obj = datetime.strptime(time_str, "%I:%M%p").time()
            location = locations[location_str]
            team_a = teams[(division, team_a_name)]
            team_b = teams[(division, team_b_name)]

            preassignments.append(
                Preassignment(date_obj, time_obj, location, team_a, team_b)
            )


def print_master_schedule():
    gameslots_by_day = defaultdict(list)
    blackouts_by_day = defaultdict(list)

    for g in gameslots:
        gameslots_by_day[g.date].append(g)
    for b in blackouts:
        blackouts_by_day[b.date].append(b)

    schedule_table = [
        ["Schedule Slot", "Scheduled Matchup", "Blackouts"],
        ["-------------", "-----------------", "---------"],
    ]

    for day in sorted(gameslots_by_day.keys()):
        gameslots_on_day = gameslots_by_day[day]
        blackouts_on_day = blackouts_by_day[day]

        for i, gameslot in enumerate(gameslots_on_day):
            blackout_str = (
                "" if i >= len(blackouts_on_day) else str(blackouts_on_day[i])
            )
            matchup_str = (
                "Open"
                if gameslot.selected_matchup is None
                else str(gameslot.selected_matchup)
            )

            row = [str(gameslot), matchup_str, blackout_str]

            schedule_table.append(row)

        if len(blackouts_on_day) > len(gameslots_on_day):
            num_unshown_blackouts = len(blackouts_on_day) - len(gameslots_on_day)
            schedule_table[-1][-1] += f" ({num_unshown_blackouts} blackouts not shown)"

        schedule_table.append(["", "", ""])

    utils.pretty_print_table(schedule_table)


def create_pasteable_schedule_file(output_dir_path: str):

    gameslots_by_day = defaultdict(list)

    for g in gameslots:
        gameslots_by_day[g.date].append(g)

    pasteable_file_path = output_dir_path + "/pasteable.txt"
    with open(pasteable_file_path, "w") as f:

        for day in sorted(gameslots_by_day.keys()):
            gameslots_on_day = gameslots_by_day[day]

            for gameslot in gameslots_on_day:
                if gameslot.selected_matchup is None:
                    matchup_str = "\t\tOPEN"
                else:
                    matchup = gameslot.selected_matchup
                    division = matchup.division
                    division_str = (
                        "7/8B" if division in ["7/8B South", "7/8B North"] else division
                    )
                    home_team, away_team = matchup.get_teams_in_home_away_order()

                    matchup_str = f"{division_str}\t{home_team.name}\t{away_team.name}"

                print(matchup_str, file=f)

            print(file=f)


def print_breakout_schedules():
    for team in teams.values():
        table = []
        table.append(["", "Date", "Day", "Time", "Home Team", "Away Team", "Location"])
        table.append(["", "----", "---", "----", "---------", "---------", "--------"])

        team.matchups.sort(key=lambda m: m.selected_gameslot.date)

        for i, matchup in enumerate(team.matchups):
            game_num = i + 1
            date_str = utils.prettify_date(matchup.selected_gameslot.date)
            day = calendar.day_name[matchup.selected_gameslot.date.weekday()]
            time_str = utils.prettify_time(matchup.selected_gameslot.time)
            home_team, away_team = matchup.get_teams_in_home_away_order()
            location = matchup.selected_gameslot.location

            table.append(
                [
                    game_num,
                    date_str,
                    day,
                    time_str,
                    home_team.name,
                    away_team.name,
                    location,
                ]
            )

        print(str(team))
        print("-" * len(str(team)))
        utils.pretty_print_table(table)
        print()


def print_consecutive_game_day_metrics():
    table = [
        ["# of Consecutive Game Day Pairs", "# of Teams With That Many Pairs"],
        ["-------------------------------", "-------------------------------"],
    ]

    num_pairs_to_num_teams = get_num_consecutive_pairs_to_num_teams()

    for num_pairs, num_teams in sorted(num_pairs_to_num_teams.items()):
        table.append([num_pairs, num_teams])

    table.append(["", ""])

    total_pairs = sum(p * t for p, t in num_pairs_to_num_teams.items())
    table.append(["TOTAL PAIRS", total_pairs])

    utils.pretty_print_table(table)
    print()


def get_num_consecutive_pairs_to_num_teams():
    num_pairs_to_num_teams = defaultdict(int)

    for team in teams.values():
        num_pairs_for_team = 0
        for date in list(team.games_by_date.keys()):
            next_day = date + timedelta(days=1)
            if team.games_by_date[date] and team.games_by_date[next_day]:
                num_pairs_for_team += 1

        num_pairs_to_num_teams[num_pairs_for_team] += 1

    return num_pairs_to_num_teams


def print_non_preferred_gameslot_metrics():
    non_preferred_matchups = list(
        filter(lambda m: not m.selected_gameslot_is_preferred, matchups)
    )
    non_preferred_matchups.sort(key=lambda m: m.preferred_home_team.name)
    non_preferred_matchups.sort(key=lambda m: m.preferred_home_team.division)

    print(
        f"{len(non_preferred_matchups)} out of {len(matchups)} matchups received "
        + "non-preferred locations. Non-preferred assignments (if any) are listed below."
    )
    print()
    if non_preferred_matchups:
        table = [
            ["", "Matchup", "Preferred Home Team", "Assigned Location"],
            ["", "-------", "-------------------", "-----------------"],
        ]
        for i, matchup in enumerate(non_preferred_matchups):
            if i > 0 and matchup.division != non_preferred_matchups[i - 1].division:
                table.append(["", "", "", ""])
            table.append(
                [
                    str(i + 1),
                    matchup,
                    matchup.preferred_home_team.name,
                    matchup.selected_gameslot.location,
                ]
            )
        utils.pretty_print_table(table)
        print()

    num_games_at_neither_home = 0
    for m in matchups:
        if (
            m.selected_gameslot.location != m.team_a.home_location
            and m.selected_gameslot.location != m.team_b.home_location
        ):
            num_games_at_neither_home += 1
    print(
        f"{num_games_at_neither_home} games were at *neither* team's home location "
        + "(you can find them in the table above)."
    )
    print()


def print_block_size_metrics():
    table = [
        ["# of Games in Block", "# of Occurrences"],
        ["-------------------", "----------------"],
    ]

    block_sizes_to_counts = get_block_sizes_to_counts()

    for block_size, count in sorted(block_sizes_to_counts.items()):
        table.append([block_size, count])

    total_blocks = sum(block_sizes_to_counts.values())
    table.append(["", ""])
    table.append(["TOTAL BLOCKS", total_blocks])

    utils.pretty_print_table(table)
    print()


def get_block_sizes_to_counts() -> Dict[int, int]:
    block_sizes_to_counts = defaultdict(int)
    for location in locations.values():
        for num_games in location.num_games_by_date.values():
            if num_games != 0:
                block_sizes_to_counts[num_games] += 1

    return block_sizes_to_counts


def print_weekday_metrics():
    table = [
        ["# of Weekday Games", "# of Teams With That Many Weekday Games"],
        ["------------------", "---------------------------------------"],
    ]

    num_weekday_games_to_num_teams = get_num_weekday_games_to_num_teams()

    for num_games, num_teams in sorted(num_weekday_games_to_num_teams.items()):
        table.append([num_games, num_teams])
    table.append(["", ""])
    table.append(
        [
            "TOTAL WEEKDAY GAMES",
            sum(g * t for g, t in num_weekday_games_to_num_teams.items()),
        ]
    )

    print("In the next table, weekdays are any day other than Friday or Saturday.")
    print("(We try to avoid weekday games.)")
    print()
    utils.pretty_print_table(table)
    print()


def get_num_weekday_games_to_num_teams():
    num_weekday_games_to_num_teams = defaultdict(int)

    for team in teams.values():
        num_weekday_games = 0

        for matchup in team.matchups:
            game_is_weekend = matchup.selected_gameslot.date.weekday() in [4, 5]
            if not game_is_weekend:
                num_weekday_games += 1

        num_weekday_games_to_num_teams[num_weekday_games] += 1

    return num_weekday_games_to_num_teams


def get_longest_gap_between_games():
    longest_gap_in_days = 0
    for team in teams.values():
        ordered_matchups = sorted(team.matchups, key=lambda m: m.selected_gameslot.date)
        for i in range(len(ordered_matchups) - 1):
            first_game_date = ordered_matchups[i].selected_gameslot.date
            second_game_date = ordered_matchups[i + 1].selected_gameslot.date
            gap_in_days = (second_game_date - first_game_date).days
            longest_gap_in_days = max(gap_in_days, longest_gap_in_days)

    return longest_gap_in_days


def do_test_run_for_seeds(
    start_seed,
    end_seed,
    input_dir_path,
    output_dir_path,
    window_constraints,
    scarce_location_names,
):
    seed_file_path = output_dir_path + "/seeds.txt"

    cols = [
        "seed",
        "num weekday games",
        "non preferred locs",
        "smallest block size",
        "num smallest blocks",
        "most consec pairs",
        "teams with most consec",
        "longest gap between games",
    ]
    with open(seed_file_path, "w") as f:
        f.write(",".join(cols) + "\n")

    for i in range(start_seed, end_seed + 1):
        generate_schedule(
            input_dir_path=input_dir_path,
            output_dir_path=output_dir_path,
            random_seed=i,
            window_constraints=window_constraints,
            scarce_location_names=scarce_location_names,
            is_test_run_for_seed=True,
        )


def log_seed_info_from_test_run(output_dir_path: str, random_seed: int):
    seed_file_path = output_dir_path + "/seeds.txt"

    with open(seed_file_path, "a") as f:
        num_weekday_games_to_num_teams = get_num_weekday_games_to_num_teams()
        total_weekday_games = sum(
            g * t for g, t in num_weekday_games_to_num_teams.items()
        )

        num_non_preferred_locs = len(
            list(filter(lambda m: not m.selected_gameslot_is_preferred, matchups))
        )

        block_sizes_to_counts = get_block_sizes_to_counts()
        smallest_block_size_to_count = sorted(block_sizes_to_counts.items())[0]
        smallest_block_size, num_smallest_blocks = smallest_block_size_to_count

        num_consec_pairs_to_num_teams = get_num_consecutive_pairs_to_num_teams()
        largest_consec_pairs_to_num_teams = sorted(
            num_consec_pairs_to_num_teams.items()
        )[-1]
        most_consec_pairs, teams_with_most_consec = largest_consec_pairs_to_num_teams

        file_line = (
            f"{random_seed}"
            + f" - {total_weekday_games} - {num_non_preferred_locs}"
            + f" - {smallest_block_size} {num_smallest_blocks}"
            + f" - {most_consec_pairs} {teams_with_most_consec}"
            + f" - {get_longest_gap_between_games()}"
        )
        f.write(file_line + "\n")


generate_schedule(
    input_dir_path="in",
    output_dir_path="out",
    random_seed=103,
    window_constraints=[WindowConstraint(1, 1), WindowConstraint(5, 2)],
    scarce_location_names=["SJE", "Queen of the Rosary", "St. Walter", "St. Philip"],
)

# do_test_run_for_seeds(
#     1,
#     1000,
#     input_dir_path="in",
#     output_dir_path="out",
#     window_constraints=[WindowConstraint(1, 1), WindowConstraint(5, 2)],
#     scarce_location_names=["SJE", "Queen of the Rosary", "St. Walter", "St. Philip"],
# )
