import calendar
from collections import defaultdict
import csv
from datetime import datetime, timedelta
from typing import List, Set, Tuple
from blackout import Blackout
from gameslot import Gameslot
from matchup import Matchup
from team import Team
import utils
import random


divisions_to_counts = defaultdict(int)  # maps division -> # of teams in division
teams = dict()  # maps (division, name) -> team object
matchups = []
gameslots = []
locations_to_counts = defaultdict(int)  # maps location -> # of gameslots in location
blackouts = []

search_dead_ends: int


def generate_schedule(
    input_dir_path: str, random_seed: int, window_constraints: List[Tuple[int, int]]
):
    random.seed(random_seed)

    ingest_files(input_dir_path)

    assign_preferred_locations_to_matchups()
    assign_candidate_gameslots_to_matchups()

    # Randomize before sorting so that matchups with equal number of preferred
    # gameslots end up in random order. If we don't do this, teams near the end of
    # teams.csv get processed last, meaning their preferences are less likely to be
    # satisified.
    random.shuffle(matchups)

    # Process most constrained first, per https://www.youtube.com/watch?v=dARl_gGrS4o.
    # The idea is that if a matchup has many preferred slots, it's unlikely that an
    # earlier matchup would have taken all of them. Therefore it's safe to consider
    # it at the end.
    matchups.sort(key=lambda m: len(m.preferred_gameslots))

    success = select_gameslots_for_matchups(0, set(), window_constraints)

    print(f"Search completed after {search_dead_ends} dead ends.")

    if success:
        print("Success! A valid schedule was found.")
        print()
        print_master_schedule()
        print_breakout_schedules()
    else:
        print("There is no schedule that satisfies the constraints.")


def select_gameslots_for_matchups(
    start: int,
    reserved_gameslots: Set[Gameslot],
    window_constraints: List[Tuple[int, int]],
):
    global search_dead_ends
    if start == 0:
        search_dead_ends = 0

    if start == len(matchups):
        # now that the selections are finalized, record them in the gameslots too
        for matchup in matchups:
            selected_gameslot = matchup.selected_gameslot
            selected_gameslot.selected_matchup = matchup

        return True

    matchup = matchups[start]

    for candidate_gameslots in (matchup.preferred_gameslots, matchup.backup_gameslots):
        num_gameslots = len(candidate_gameslots)
        first_gameslot_index = random.randrange(num_gameslots)

        for i in range(num_gameslots):
            gameslot_index = (first_gameslot_index + i) % num_gameslots
            gameslot = candidate_gameslots[gameslot_index]

            if gameslot in reserved_gameslots:
                continue
            if selection_violates_window_constraints(
                matchup, gameslot, window_constraints
            ):
                continue

            reserved_gameslots.add(gameslot)
            matchup.team_a.num_games_by_date[gameslot.date] += 1
            matchup.team_b.num_games_by_date[gameslot.date] += 1
            matchup.selected_gameslot = gameslot

            if select_gameslots_for_matchups(
                start + 1, reserved_gameslots, window_constraints
            ):
                return True

            reserved_gameslots.remove(gameslot)
            matchup.team_a.num_games_by_date[gameslot.date] -= 1
            matchup.team_b.num_games_by_date[gameslot.date] -= 1
            matchup.selected_gameslot = None

    search_dead_ends += 1
    if search_dead_ends % 100000 == 0:
        print(f"Search has hit {search_dead_ends} dead ends")
    return False


# Returns true if the given matchup is prohibited from selecting the given slot because
# one of the teams will have too many games in a window
def selection_violates_window_constraints(
    matchup: Matchup, gameslot: Gameslot, window_constraints: List[Tuple[int, int]]
):
    candidate_date = gameslot.date

    for team in matchup.team_a, matchup.team_b:
        for window_constraint in window_constraints:
            window_size, max_in_window = window_constraint

            num_selected_dates_in_window = 0

            left = candidate_date - timedelta(days=window_size - 1)
            right = left - timedelta(days=1)

            for _ in range(window_size):
                right += timedelta(days=1)
                num_selected_dates_in_window += team.num_games_by_date[right]

            if num_selected_dates_in_window >= max_in_window:
                # Equality will lead to a violation because the candidate will push
                # num_selected_dates_in_window above the max.
                return True

            for _ in range(window_size - 1):
                num_selected_dates_in_window -= team.num_games_by_date[left]
                left += timedelta(days=1)
                right += timedelta(days=1)
                num_selected_dates_in_window += team.num_games_by_date[right]

                if num_selected_dates_in_window >= max_in_window:
                    return True

    return False


def assign_candidate_gameslots_to_matchups():
    for m in matchups:
        m.preferred_gameslots = []
        m.backup_gameslots = []
        for g in gameslots:
            if any(b.prohibits_matchup_in_slot(m, g) for b in blackouts):
                continue

            if g.location in m.preferred_locations:
                m.preferred_gameslots.append(g)
            else:
                m.backup_gameslots.append(g)


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
def get_locations_for_home_game(team: Team) -> Set[str]:
    if team.home_location is None:
        return {loc for loc in locations_to_counts}

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
            division, name, home_location = row
            home_location_obj = None if home_location == "NONE" else home_location
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
            date_string, time_string, location = row

            datetime_string = date_string + " " + time_string
            datetime_obj = datetime.strptime(datetime_string, "%m/%d/%Y %I:%M%p")

            gameslots.append(
                Gameslot(datetime_obj.date(), datetime_obj.time(), location)
            )
            locations_to_counts[location] += 1

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
    for l, count in locations_to_counts.items():
        print(f"{l} ({count} gameslots)")
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


generate_schedule(
    input_dir_path="examples/volleyball_2022",
    random_seed=14,
    window_constraints=[(1, 1), (5, 2)],
)
