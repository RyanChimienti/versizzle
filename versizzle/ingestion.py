import csv
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from versizzle.blackout import Blackout
from versizzle.gameslot import Gameslot
from versizzle.location import Location
from versizzle.matchup import Matchup
from versizzle.preassignment import Preassignment
from versizzle.team import Team


@dataclass
class IngestionResult:
    divisions_to_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    teams: dict[tuple[str, str], Team] = field(default_factory=dict)
    matchups: Sequence[Matchup] = field(default_factory=list)
    gameslots: list[Gameslot] = field(default_factory=list)
    locations: dict[str, Location] = field(default_factory=dict)
    blackouts: Sequence[Blackout] = field(default_factory=list)
    preassignments: list[Preassignment] = field(default_factory=list)


def ingest_files(
    directory_path: str,
    scarce_location_names: list[str],
) -> IngestionResult:
    result = IngestionResult()
    scarce_locations = set(scarce_location_names)

    ingest_teams_file(directory_path, scarce_locations, result)
    ingest_matchups_file(directory_path, result)
    ingest_gameslots_file(directory_path, scarce_locations, result)
    ingest_blackouts_file(directory_path, result)
    ingest_preassignments_file(directory_path, result)

    return result


def ingest_teams_file(
    directory_path: str,
    scarce_location_names: set[str],
    result: IngestionResult,
) -> None:
    file_path = f"{directory_path}/teams.csv"

    with open(file_path, newline="") as file:
        lines = list(csv.reader(file))

    if not lines:
        raise Exception("teams.csv must contain at least 1 line (a header)")

    if lines[0] != ["division", "team", "home location"]:
        raise Exception("teams.csv should have 3 columns: 'division', 'team', and 'home location'")

    for division, name, home_location_name in lines[1:]:
        if home_location_name == "NONE":
            home_location = None
        else:
            home_location = result.locations.get(home_location_name)

            if home_location is None:
                home_location = Location(
                    home_location_name,
                    home_location_name in scarce_location_names,
                )
                result.locations[home_location_name] = home_location

        result.teams[(division, name)] = Team(
            division,
            name,
            home_location,
        )
        result.divisions_to_counts[division] += 1

    print("======================== ingested divisions: ========================")
    for division, count in result.divisions_to_counts.items():
        print(f"{division} ({count} teams)")

    print()
    print("======================== ingested teams: ========================")
    for team in result.teams.values():
        print(team)
    print()


def ingest_matchups_file(
    directory_path: str,
    result: IngestionResult,
) -> None:
    file_path = f"{directory_path}/matchups.csv"

    with open(file_path, newline="") as file:
        lines = list(csv.reader(file))

    if not lines:
        raise Exception("matchups.csv must contain at least 1 line (a header)")

    if lines[0] != ["division", "team a", "team b"]:
        raise Exception("matchups.csv should have 3 columns: 'division', 'team a', and 'team b'")

    matchups: list[Matchup] = []

    for division, team_a_name, team_b_name in lines[1:]:
        team_a = result.teams[(division, team_a_name)]
        team_b = result.teams[(division, team_b_name)]

        matchup = Matchup(team_a, team_b)
        matchups.append(matchup)

    result.matchups = matchups

    print("======================== ingested matchups: ========================")
    print_collection(result.matchups)
    print()


def ingest_gameslots_file(
    directory_path: str,
    scarce_location_names: set[str],
    result: IngestionResult,
) -> None:
    file_path = f"{directory_path}/gameslots.csv"

    with open(file_path, newline="") as file:
        lines = list(csv.reader(file))

    if not lines:
        raise Exception("gameslots.csv must contain at least 1 line (a header)")

    if lines[0] != ["date", "time", "location"]:
        raise Exception("gameslots.csv should have 3 columns: 'date', 'time', and 'location'")

    for date_string, time_string, location_name in lines[1:]:
        location = result.locations.get(location_name)

        if location is None:
            location = Location(
                location_name,
                location_name in scarce_location_names,
            )
            result.locations[location_name] = location

        date_and_time = datetime.strptime(
            f"{date_string} {time_string}",
            "%m/%d/%Y %I:%M%p",
        )

        result.gameslots.append(
            Gameslot(
                date_and_time.date(),
                date_and_time.time(),
                location,
            )
        )
        location.num_gameslots += 1

    print("======================== ingested gameslots: ========================")
    print_collection(result.gameslots)
    print()

    print("======================== ingested locations: ========================")
    for location in result.locations.values():
        print(f"{location} ({location.num_gameslots} gameslots)")
    print()


def ingest_blackouts_file(
    directory_path: str,
    result: IngestionResult,
) -> None:
    file_path = f"{directory_path}/blackouts.csv"

    with open(file_path, newline="") as file:
        lines = list(csv.reader(file))

    if not lines:
        raise Exception("blackouts.csv must contain at least 1 line (a header)")

    if lines[0] != [
        "date",
        "start time",
        "end time",
        "division",
        "team",
    ]:
        raise Exception("blackouts.csv should have 5 columns: 'date', 'start time', 'end time', 'division', and 'team'")

    blackouts: list[Blackout] = []

    for (
        date_string,
        start_time_string,
        end_time_string,
        division,
        team_name,
    ) in lines[1:]:
        date = datetime.strptime(date_string, "%m/%d/%Y").date()

        start_time = None if start_time_string == "-" else datetime.strptime(start_time_string, "%I:%M%p").time()
        end_time = None if end_time_string == "-" else datetime.strptime(end_time_string, "%I:%M%p").time()

        blackout_division = None if division == "ALL" else division
        blackout_team = None if team_name == "ALL" else team_name

        blackouts.append(
            Blackout(
                date,
                start_time,
                end_time,
                blackout_division,
                blackout_team,
            )
        )

    result.blackouts = blackouts

    print("======================== ingested blackouts: ========================")
    print_collection(result.blackouts)
    print()


def ingest_preassignments_file(
    directory_path: str,
    result: IngestionResult,
) -> None:
    file_path = f"{directory_path}/preassignments.csv"

    with open(file_path, newline="") as file:
        lines = list(csv.reader(file))

    if not lines:
        raise Exception("preassignments.csv must contain at least 1 line (a header)")

    if lines[0] != [
        "date",
        "time",
        "location",
        "division",
        "team a",
        "team b",
    ]:
        raise Exception(
            "preassignments.csv should have 6 columns: 'date', 'time', 'location', 'division', 'team a', and 'team b'"
        )

    for (
        date_string,
        time_string,
        location_name,
        division,
        team_a_name,
        team_b_name,
    ) in lines[1:]:
        date = datetime.strptime(date_string, "%m/%d/%Y").date()
        time = datetime.strptime(time_string, "%I:%M%p").time()
        location = result.locations[location_name]
        team_a = result.teams[(division, team_a_name)]
        team_b = result.teams[(division, team_b_name)]

        result.preassignments.append(
            Preassignment(
                date,
                time,
                location,
                team_a,
                team_b,
            )
        )


def print_collection(items: Sequence[object]) -> None:
    if len(items) <= 20:
        for item in items:
            print(item)
        return

    for item in items[:10]:
        print(item)

    print(f"...{len(items) - 20} more...")

    for item in items[-10:]:
        print(item)
