from collections import defaultdict
import csv
from datetime import datetime
from typing import Set
from blackout import Blackout
from gameslot import Gameslot
from matchup import Matchup

from team import Team


divisions_to_counts = defaultdict(int)  # maps division -> # of teams in division
teams = dict()  # maps (division, name) -> team object
matchups = []
gameslots = []
locations_to_counts = defaultdict(int)  # maps location -> # of gameslots in location
blackouts = []


def generate_schedule(input_dir_path):
    ingest_files(input_dir_path)
    assign_candidate_locations_to_matchups()


def assign_candidate_locations_to_matchups():
    for d in divisions_to_counts:
        division_matchups = [m for m in matchups if m.division == d]

        team_pairs_to_matchups = dict()
        for m in division_matchups:
            team_pair = tuple(sorted([m.team_a.name, m.team_b.name]))
            if team_pair not in team_pairs_to_matchups:
                team_pairs_to_matchups[team_pair] = [m]
            else:
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
            matchups.append(Matchup(team_a, team_b))


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


generate_schedule("examples/volleyball_2022")
print("======================== ingested divisions: ========================")
for d, count in divisions_to_counts.items():
    print(f"{d} ({count} teams)")
print("======================== ingested teams: ========================")
for t in teams.values():
    print(t)
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
print("======================== ingested locations: ========================")
for l, count in locations_to_counts.items():
    print(f"{l} ({count} gameslots)")
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
