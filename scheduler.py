import calendar
from collections import defaultdict
import csv
from datetime import datetime
from typing import Dict, List, Set, Tuple
from blackout import Blackout
from gameslot import Gameslot
from location import Location
from matchup import Matchup
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

backup_selection_dead_ends: int
backup_selection_depth: int


def generate_schedule(
    input_dir_path: str, random_seed: int, window_constraints: List[WindowConstraint]
):
    random.seed(random_seed)

    ingest_files(input_dir_path)

    assign_preferred_locations_to_matchups()
    assign_candidate_gameslots_to_matchups()

    success = select_gameslots_for_matchups(window_constraints)

    if not success:
        print("Failed to find a schedule. Try relaxing your window constraints.")
        return

    print("A valid schedule was found!")
    print()

    print_non_preferred_gameslot_metrics()
    print_block_size_metrics()
    # print_master_schedule()
    # print_breakout_schedules()


def select_gameslots_for_matchups(window_constraints: List[WindowConstraint]):
    print("Ordering matchups for preferred selection phase.")

    put_matchups_in_preferred_selection_order()

    print("Ordering matchups complete.")
    print("Preferred selection phase started.")

    for matchup in matchups:
        select_preferred_gameslot_for_matchup(matchup, window_constraints)

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


def put_matchups_in_preferred_selection_order():
    # Randomize before sorting so that matchups which are otherwise equal end up in
    # random order. If we don't do this, teams near the end of teams.csv get processed
    # later, meaning their preferences are less likely to be satisified.
    random.shuffle(matchups)

    # Process most constrained first, per https://www.youtube.com/watch?v=dARl_gGrS4o.
    # The idea is that if a matchup has many preferred slots, it's unlikely that an
    # earlier matchup would have taken all of them. Therefore it's safe to consider
    # it at the end. On the other hand, if a matchup has few preferred slots, or if its
    # preferred slots are also preferred by a lot of other matchups, then it's in danger
    # of losing its preferred slots, so it should be considered early.
    matchups.sort(
        key=lambda m: sum(
            1 / float(len(p.matchups_that_prefer_this_slot))
            for p in m.preferred_gameslots
        )
    )

    # If both teams in the matchup have the same home location, it would be egregious
    # for them to have to travel elsewhere. So move those matchups to the start to make
    # sure they get their preferred location.
    matchups.sort(
        key=lambda m: 1 if m.team_a.home_location == m.team_b.home_location else 2
    )


# If the given matchup has at least one preferred gameslot that can be selected,
# selects the best preferred gameslot. Returns True if a gameslot was selected, False if
# not.
#
# TODO: Consider favoring gameslots that avoid consecutive game days. You could do this
# with a "soft" WindowConstraint(2, 1)
def select_preferred_gameslot_for_matchup(
    matchup: Matchup, window_constraints: List[WindowConstraint]
) -> bool:
    for reuse_location in True, False:
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

    if start == len(matchups_using_backup_slots):
        return True

    matchup = matchups_using_backup_slots[start]

    for reuse_single_use_location, reuse_multi_use_location in (
        (True, False),
        (False, True),
        (False, False),
    ):
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

            matchup.deselect_gameslot(gameslot)

    backup_selection_dead_ends += 1
    if backup_selection_dead_ends % 10000 == 0:
        print(f"Backup selection has hit {backup_selection_dead_ends} dead ends")
    return False


def assign_candidate_gameslots_to_matchups():
    for g in gameslots:
        g.matchups_that_prefer_this_slot = set()

    for m in matchups:
        m.preferred_gameslots = []
        m.backup_gameslots = []
        for g in gameslots:
            if any(b.prohibits_matchup_in_slot(m, g) for b in blackouts):
                continue

            if g.location in m.preferred_locations:
                m.preferred_gameslots.append(g)
                g.matchups_that_prefer_this_slot.add(m)
            else:
                m.backup_gameslots.append(g)

        random.shuffle(m.preferred_gameslots)
        random.shuffle(m.backup_gameslots)


def assign_preferred_locations_to_matchups():
    for d in divisions_to_counts:
        division_matchups = [m for m in matchups if m.division == d]

        team_pairs_to_matchups = defaultdict(list)
        for m in division_matchups:
            team_pair = tuple(sorted([m.team_a.name, m.team_b.name]))
            team_pairs_to_matchups[team_pair].append(m)

        groups_of_identical_matchups = team_pairs_to_matchups.values()
        for group in groups_of_identical_matchups:
            first_team, second_team = group[0].team_a, group[0].team_b

            half_of_num_matchups = len(group) // 2

            # in the first half of matchups, first team gets home games
            for i in range(half_of_num_matchups):
                matchup = group[i]
                matchup.preferred_home_team = first_team
                matchup.preferred_locations = get_locations_for_home_game(first_team)
                first_team.num_preferred_home_games += 1
                matchup.team_a.num_games += 1
                matchup.team_b.num_games += 1

            # in the second half of matchups, second team gets home games
            for i in range(half_of_num_matchups, 2 * half_of_num_matchups):
                matchup = group[i]
                matchup.preferred_home_team = second_team
                matchup.preferred_locations = get_locations_for_home_game(second_team)
                second_team.num_preferred_home_games += 1
                matchup.team_a.num_games += 1
                matchup.team_b.num_games += 1

            # if there's a game left over, either team can be home
            if len(group) % 2 == 1:
                matchup = group[-1]
                home_team = get_fairer_home_team(first_team, second_team)
                matchup.preferred_home_team = home_team
                matchup.preferred_locations = get_locations_for_home_game(home_team)
                home_team.num_preferred_home_games += 1
                matchup.team_a.num_games += 1
                matchup.team_b.num_games += 1


# The fairer home team is whichever has a lower ratio of home to away games. If the
# ratios are equal, we'll choose a team at random. Random is better than saying either
# team can be home, because allowing either will tend to favor the team with more
# gameslots at their home court, leading to systematic bias in favor of certain schools.
def get_fairer_home_team(team_1: Team, team_2: Team):
    team_1_home_ratio = (
        0.5
        if team_1.num_games == 0
        else team_1.num_preferred_home_games / float(team_1.num_games)
    )
    team_2_home_ratio = (
        0.5
        if team_2.num_games == 0
        else team_2.num_preferred_home_games / float(team_2.num_games)
    )
    if abs(team_1_home_ratio - team_2_home_ratio) < 0.0001:
        return random.choice([team_1, team_2])

    return team_1 if team_1_home_ratio < team_2_home_ratio else team_2


# Returns the valid locations for a home game for the given team. In the case of a team
# with no home location, this is all locations.
def get_locations_for_home_game(team: Team) -> Set[Location]:
    if team.home_location is None:
        return locations.values().copy()

    return {team.home_location}


def ingest_files(directory_path):
    ingest_teams_file(directory_path)
    ingest_matchups_file(directory_path)
    ingest_gameslots_file(directory_path)
    ingest_blackouts_file(directory_path)


def ingest_teams_file(directory_path):
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
                home_location_obj = Location(home_location_name)
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


def ingest_gameslots_file(directory_path):
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
                location_obj = Location(location_name)
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

            blackouts.append(
                Blackout(
                    date_obj, start_time_obj, end_time_obj, division_obj, team_name
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
            blackout = "" if i >= len(blackouts_on_day) else blackouts_on_day[i]
            matchup = (
                "Open"
                if gameslot.selected_matchup is None
                else gameslot.selected_matchup
            )

            row = [gameslot, matchup, blackout]

            schedule_table.append(row)

        if len(blackouts_on_day) > len(gameslots_on_day):
            num_unshown_blackouts = len(blackouts_on_day) - len(gameslots_on_day)
            schedule_table[-1][-1] += f" ({num_unshown_blackouts} blackouts not shown)"

        schedule_table.append(["", "", ""])

    utils.pretty_print_table(schedule_table)


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


def print_block_size_metrics():
    table = [
        ["# of Games in Block", "# of Occurrences"],
        ["-------------------", "----------------"],
    ]

    block_sizes_to_counts = defaultdict(int)
    for location in locations.values():
        for num_games in location.num_games_by_date.values():
            if num_games != 0:
                block_sizes_to_counts[num_games] += 1

    for block_size, count in sorted(block_sizes_to_counts.items()):
        table.append([block_size, count])

    total_blocks = sum(block_sizes_to_counts.values())
    table.append(["", ""])
    table.append(["TOTAL BLOCKS", total_blocks])

    utils.pretty_print_table(table)
    print()


generate_schedule(
    input_dir_path="examples/volleyball_2022",
    random_seed=14,
    window_constraints=[WindowConstraint(1, 1), WindowConstraint(5, 2)],
)
