import csv
from datetime import date, time, datetime


teams = []  # team = (division, team, home location)
divisions = []
matchups = []  # matchup = (division, team a, team b)
gameslots = []  # gameslot = (date, time, location)
blackouts = []  # blackout = (date, start, end, division, team)


def ingest(directory_path):
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
            teams.append(tuple(row))

    teams.sort()

    for team in teams:
        division = team[0]
        if division not in divisions:
            divisions.append(division)


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
            division, team_a, team_b = row
            matchups.append((division, team_a, team_b))


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

            gameslots.append((datetime_obj.date(), datetime_obj.time(), location))


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
            date_string, start_time_string, end_time_string, division, team = row

            date_obj = datetime.strptime(date_string, "%m/%d/%Y").date()

            if start_time_string == "-":
                start_time_obj = None
            else:
                start_time_obj = datetime.strptime(start_time_string, "%I:%M%p").time()

            if end_time_string == "-":
                end_time_obj = None
            else:
                end_time_obj = datetime.strptime(end_time_string, "%I:%M%p").time()

            blackouts.append((date_obj, start_time_obj, end_time_obj, division, team))


ingest("examples/volleyball_2022")
print("======================== ingested divisions: ========================")
for d in divisions:
    print(d)
print("======================== ingested teams: ========================")
for t in teams:
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
