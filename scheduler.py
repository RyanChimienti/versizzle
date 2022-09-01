import calendar
from collections import defaultdict
import csv
from datetime import date, datetime, timedelta
from typing import Dict, Set
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


def generate_schedule(input_dir_path, random_seed, min_days_between_games):
    random.seed(random_seed)

    ingest_files(input_dir_path)

    assign_candidate_locations_to_matchups()
    assign_candidate_gameslots_to_matchups()

    matchups.sort(key=lambda m: len(m.candidate_gameslots))

    success = select_gameslots_for_matchups(0, set(), min_days_between_games)

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
    min_days_between_games: int,
):
    if start == len(matchups):
        # now that the selections are finalized, record them in the gameslots too
        for matchup in matchups:
            selected_gameslot = matchup.selected_gameslot
            selected_gameslot.selected_matchup = matchup

        return True

    matchup = matchups[start]
    num_gameslots = len(matchup.candidate_gameslots)
    first_gameslot_index = random.randrange(num_gameslots)

    for i in range(num_gameslots):
        gameslot_index = (first_gameslot_index + i) % num_gameslots
        gameslot = matchup.candidate_gameslots[gameslot_index]

        if gameslot in reserved_gameslots:
            continue
        if team_has_game_too_close(matchup, gameslot, min_days_between_games):
            continue

        reserved_gameslots.add(gameslot)
        matchup.team_a.selected_dates.add(gameslot.date)
        matchup.team_b.selected_dates.add(gameslot.date)
        matchup.selected_gameslot = gameslot

        if select_gameslots_for_matchups(
            start + 1, reserved_gameslots, min_days_between_games
        ):
            return True

        reserved_gameslots.remove(gameslot)
        matchup.team_a.selected_dates.remove(gameslot.date)
        matchup.team_b.selected_dates.remove(gameslot.date)
        matchup.selected_gameslot = None

    return False


# Returns true if the given matchup is prohibited from selecting the given slot due to
# one of the teams having a scheduled game too close by.
def team_has_game_too_close(
    matchup: Matchup,
    gameslot: Gameslot,
    min_days_between_games: int,
):
    danger_zone_radius = min_days_between_games - 1
    for day_offset in range(-(danger_zone_radius), danger_zone_radius + 1):
        danger_date = gameslot.date + timedelta(days=day_offset)
        if (
            danger_date in matchup.team_a.selected_dates
            or danger_date in matchup.team_b.selected_dates
        ):
            return True

    return False


def assign_candidate_gameslots_to_matchups():
    for m in matchups:
        candidate_gameslots = []
        for g in gameslots:
            if g.location not in m.candidate_locations:
                continue
            if any(b.prohibits_matchup_in_slot(m, g) for b in blackouts):
                continue

            candidate_gameslots.append(g)

        m.candidate_gameslots = candidate_gameslots


def assign_candidate_locations_to_matchups():
    for d in divisions_to_counts:
        division_matchups = [m for m in matchups if m.division == d]

        team_pairs_to_matchups = defaultdict(list)
        for m in division_matchups:
            team_pair = tuple(sorted([m.team_a.name, m.team_b.name]))
            team_pairs_to_matchups[team_pair].append(m)

        groups_of_identical_matchups = team_pairs_to_matchups.values()
        for group in groups_of_identical_matchups:
            half_of_num_matchups = len(group) // 2

            # in the first half of matchups, team A gets home games
            for i in range(half_of_num_matchups):
                matchup = group[i]
                matchup.candidate_locations = get_locations_for_home_game(
                    matchup.team_a
                )

            # in the second half of matchups, team B gets home games
            for i in range(half_of_num_matchups, 2 * half_of_num_matchups):
                matchup = group[i]
                matchup.candidate_locations = get_locations_for_home_game(
                    matchup.team_b
                )

            # if there's a game left over, either team can be home
            if len(group) % 2 == 1:
                matchup = group[-1]
                matchup.candidate_locations = get_locations_for_home_game(
                    matchup.team_a
                ).union(get_locations_for_home_game(matchup.team_b))


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
        table.append(["", "Date", "Day", "Time", "Team A", "Team B", "Location"])
        table.append(["", "----", "---", "----", "------", "------", "--------"])

        team.matchups.sort(key=lambda m: m.selected_gameslot.date)

        for i, matchup in enumerate(team.matchups):
            game_num = i + 1
            date_str = utils.prettify_date(matchup.selected_gameslot.date)
            day = calendar.day_name[matchup.selected_gameslot.date.weekday()]
            time_str = utils.prettify_time(matchup.selected_gameslot.time)
            team_a = matchup.team_a.name
            team_b = matchup.team_b.name
            location = matchup.selected_gameslot.location

            table.append([game_num, date_str, day, time_str, team_a, team_b, location])

        print(str(team))
        print("-" * len(str(team)))
        utils.pretty_print_table(table)
        print()


generate_schedule(
    input_dir_path="examples/volleyball_2022", random_seed=14, min_days_between_games=1
)
