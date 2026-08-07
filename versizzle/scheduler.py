import calendar
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from heapq import nlargest

from versizzle import ingestion, postprocessor, utils
from versizzle.blackout import Blackout
from versizzle.gameslot import Gameslot
from versizzle.location import Location
from versizzle.matchup import Matchup
from versizzle.preassignment import Preassignment
from versizzle.team import Team
from versizzle.utils import unwrap
from versizzle.window_constraint import WindowConstraint

divisions_to_counts: dict[str, int] = defaultdict(int)  # maps division -> # of teams in division
teams: dict[tuple[str, str], Team] = dict()  # maps (division, team name) -> team object
matchups: Sequence[Matchup] = []
gameslots: list[Gameslot] = []
locations: dict[str, Location] = dict()  # maps location name -> location object
blackouts: Sequence[Blackout] = []
preassignments: list[Preassignment] = []

backup_selection_dead_ends: int
backup_selection_depth: int


def generate_schedule(
    input_dir_path: str,
    output_dir_path: str,
    random_seed: int,
    window_constraints: list[WindowConstraint],
    scarce_location_names: list[str],
    is_test_run_for_seed: bool = False,
):
    global divisions_to_counts
    global teams
    global matchups
    global gameslots
    global locations
    global blackouts
    global preassignments
    global backup_selection_dead_ends
    global backup_selection_depth

    backup_selection_dead_ends = 0
    backup_selection_depth = 0

    random.seed(random_seed)

    ingestion_result = ingestion.ingest_files(input_dir_path, scarce_location_names)
    divisions_to_counts = ingestion_result.divisions_to_counts
    teams = ingestion_result.teams
    matchups = ingestion_result.matchups
    gameslots = ingestion_result.gameslots
    locations = ingestion_result.locations
    blackouts = ingestion_result.blackouts
    preassignments = ingestion_result.preassignments

    do_preassignments(window_constraints)
    select_preferred_home_teams()
    assign_candidate_gameslots_to_matchups()

    success = select_gameslots_for_matchups(window_constraints)

    if not success:
        print("Failed to find a schedule. Try relaxing your window constraints.")
        return

    print("A valid schedule was found!")

    postprocessor.PostProcessor(matchups, gameslots, window_constraints).post_process()

    if is_test_run_for_seed:
        log_seed_info_from_test_run(output_dir_path, random_seed)
        return

    write_output_files(output_dir_path)


def do_preassignments(window_constraints: list[WindowConstraint]):
    print(f"Performing {len(preassignments)} preassignments")

    for preassignment in preassignments:
        preassignment.assign(matchups, gameslots, blackouts, window_constraints)

    print("Preassignments complete.")
    print()


def select_preferred_home_teams():
    """For each matchup, selects which team is the preferred home team."""

    for division in divisions_to_counts:
        if any(m.is_preassigned for m in matchups if m.division == division):
            select_preferred_home_teams_in_preassigned_division(division)
        else:
            select_preferred_home_teams_in_nonpreassigned_division(division)


def select_preferred_home_teams_in_nonpreassigned_division(division: str):
    """
    Takes a division with no preassignments. For every matchup in that division, selects which team is the preferred
    home team. The lack of preassignments allows us to use a more ambitious home selection algorithm. Not only will we
    strive to give each team at least half their games at home, but we will also strive to give each pair of teams who
    play each other an even number of home games with one another. (The latter goal is too complicated when
    preassignments are present in the division.)
    """

    division_matchups = [m for m in matchups if m.division == division]
    random.shuffle(division_matchups)  # TODO: Maybe remove all local shuffling and shuffle once right after ingestion

    team_pairs_to_matchups: defaultdict[tuple[str, str], list[Matchup]] = defaultdict(list)
    for m in division_matchups:
        first_team_name, second_team_name = sorted([m.team_a.name, m.team_b.name])
        team_pairs_to_matchups[(first_team_name, second_team_name)].append(m)

    groups_of_identical_matchups = team_pairs_to_matchups.values()
    groups_of_identical_asymmetric_matchups: list[list[Matchup]] = []
    groups_of_identical_symmetric_matchups: list[list[Matchup]] = []
    for g in groups_of_identical_matchups:
        if g[0].team_a.home_location == g[0].team_b.home_location:
            groups_of_identical_symmetric_matchups.append(g)
        else:
            groups_of_identical_asymmetric_matchups.append(g)

    # First distribute groups of identical asymmetric matchups evenly between the two competing teams. Save the last
    # matchup if there's an odd number; we'll deal with it next...

    for group in groups_of_identical_asymmetric_matchups:
        team_a, team_b = group[0].team_a, group[0].team_b

        for _ in range(len(group) // 2):
            group.pop().select_preferred_home_team(team_a)
            group.pop().select_preferred_home_team(team_b)

    # In each matchup group, there may be one remaining matchup (if it had an odd number originally). These matchups are
    # special because, unlike the matchups processed so far, they have no natural home team. Therefore we can assign
    # them home teams in whatever way best balances the number of home games for each team.

    for group in groups_of_identical_asymmetric_matchups:
        if group:
            m = group[0]

            home_team = get_team_who_needs_home_in_asymmetric_matchup(m)
            if home_team is None:
                home_team = get_team_with_lower_asymmetric_preferred_home_ratio(m.team_a, m.team_b)

            m.select_preferred_home_team(home_team)

    # All that's left to handle are the symmetric matchups. Of course, it doesn't matter which home team we pick for
    # these from a scheduling standpoint, but it does have a slight aesthetic effect because it determines the order in
    # which we display the teams. From an aesthetic standpoint, it is nice to balance our symmetric matchups, meaning if
    # two teams play each other multiple times, we call each team the home team half of the time.

    for group in groups_of_identical_symmetric_matchups:
        team_a, team_b = group[0].team_a, group[0].team_b

        for _ in range(len(group) // 2):
            group.pop().select_preferred_home_team(team_a)
            group.pop().select_preferred_home_team(team_b)

        if group:
            # If there's an extra matchup, give it to the team with the lower asymmetric home ratio.
            group[0].select_preferred_home_team(get_team_with_lower_asymmetric_preferred_home_ratio(team_a, team_b))


def select_preferred_home_teams_in_preassigned_division(division: str):
    """
    Takes a division with at least one preassignment. For every matchup in that division, selects which team is the
    preferred home team. Preassignments can seriously complicate preferred home selection, so we use a less ambitious
    algorithm. Namely, we only seek to give each team at least half their games at home, without worrying about how many
    home games the team has against a specific opponent team.
    """

    division_matchups = [m for m in matchups if m.division == division]
    random.shuffle(division_matchups)  # TODO: Maybe remove all local shuffling and shuffle once right after ingestion

    # First, handle preassigned asymmetric matchups. The preferred home team is obvious here: we just use whichever home
    # location was preassigned.

    for matchup in division_matchups:
        if not matchup.is_preassigned:
            continue
        if matchup.team_a.home_location == matchup.team_b.home_location:
            continue

        location = unwrap(matchup.selected_gameslot).location
        if location == matchup.team_a.home_location:
            home_team = matchup.team_a
        elif location == matchup.team_b.home_location:
            home_team = matchup.team_b
        else:
            # A preassigned matchup being placed at neither team's home is rare. Rather than carefully considering this
            # case, We'll let randomness find a good solution over many seeds.
            home_team = random.choice((matchup.team_a, matchup.team_b))

        matchup.select_preferred_home_team(home_team)

    # Second, handle nonpreassigned asymmetric matchups. This is the interesting case. Our strategy is to take as the
    # home team whichever team has a lower asymmetric home ratio so far. However, there is a caveat: if either team
    # needs all its remaining matchups to be home games in order to reach half its asymmetric matchups at home, then
    # that team is given home no matter what.

    for matchup in division_matchups:
        if matchup.is_preassigned:
            continue
        if matchup.team_a.home_location == matchup.team_b.home_location:
            continue

        home_team = get_team_who_needs_home_in_asymmetric_matchup(matchup)
        if home_team is None:
            home_team = get_team_with_lower_asymmetric_preferred_home_ratio(matchup.team_a, matchup.team_b)

        matchup.select_preferred_home_team(home_team)

    # All that's left to handle are the symmetric matchups (both preassigned and not). Of course, it doesn't matter
    # which home team we pick for these from a scheduling standpoint, but it does have a slight aesthetic effect because
    # it determines the order in which we display the teams. From an aesthetic standpoint, it is nice to balance our
    # symmetric matchups, meaning if two teams play each other multiple times, we call each team the home team half of
    # the time.

    groups_of_identical_symmetric_matchups: defaultdict[tuple[str, str], list[Matchup]] = defaultdict(list)
    for matchup in division_matchups:
        if matchup.team_a.home_location == matchup.team_b.home_location:
            first_team_name, second_team_name = sorted((matchup.team_a.name, matchup.team_b.name))
            groups_of_identical_symmetric_matchups[(first_team_name, second_team_name)].append(matchup)

    for group in groups_of_identical_symmetric_matchups.values():
        team_a, team_b = group[0].team_a, group[0].team_b

        for _ in range(len(group) // 2):
            group.pop().select_preferred_home_team(team_a)
            group.pop().select_preferred_home_team(team_b)

        if group:
            # If there's an extra matchup, give it to the team with the lower asymmetric home ratio.
            group[0].select_preferred_home_team(get_team_with_lower_asymmetric_preferred_home_ratio(team_a, team_b))


def get_team_who_needs_home_in_asymmetric_matchup(matchup: Matchup) -> Team | None:
    """
    Takes an asymmetric matchup which has not been assigned a preferred home team. If (exactly) one of the teams in the
    matchup needs to be given preferred-home games in all of its remaining asymmetric matchups in order to have half of
    its games at home, returns that team. Otherwise returns None.
    """

    assert matchup.team_a.home_location != matchup.team_b.home_location
    assert matchup.preferred_home_team is None

    team_a = matchup.team_a
    team_b = matchup.team_b
    team_a_min_asymmetric_home_games_desired = team_a.num_asymmetric_matchups // 2
    team_b_min_asymmetric_home_games_desired = team_b.num_asymmetric_matchups // 2
    team_a_max_asymmetric_home_games_achievable = team_a.num_asymmetric_matchups_preferring_this_team_as_home + (
        team_a.num_asymmetric_matchups - team_a.num_asymmetric_matchups_with_home_preference_chosen
    )
    team_b_max_asymmetric_home_games_achievable = team_b.num_asymmetric_matchups_preferring_this_team_as_home + (
        team_b.num_asymmetric_matchups - team_b.num_asymmetric_matchups_with_home_preference_chosen
    )
    team_a_must_be_home = team_a_max_asymmetric_home_games_achievable <= team_a_min_asymmetric_home_games_desired
    team_b_must_be_home = team_b_max_asymmetric_home_games_achievable <= team_b_min_asymmetric_home_games_desired

    if team_a_must_be_home and not team_b_must_be_home:
        return team_a
    if team_b_must_be_home and not team_a_must_be_home:
        return team_b

    return None


def get_team_with_lower_asymmetric_preferred_home_ratio(team_1: Team, team_2: Team):
    team_1_home_ratio = (
        0.5
        if team_1.num_asymmetric_matchups_with_home_preference_chosen == 0
        else team_1.num_asymmetric_matchups_preferring_this_team_as_home
        / float(team_1.num_asymmetric_matchups_with_home_preference_chosen)
    )
    team_2_home_ratio = (
        0.5
        if team_2.num_asymmetric_matchups_with_home_preference_chosen == 0
        else team_2.num_asymmetric_matchups_preferring_this_team_as_home
        / float(team_2.num_asymmetric_matchups_with_home_preference_chosen)
    )
    if abs(team_1_home_ratio - team_2_home_ratio) < 0.0001:
        return random.choice((team_1, team_2))

    return team_1 if team_1_home_ratio < team_2_home_ratio else team_2


def assign_candidate_gameslots_to_matchups():
    for g in gameslots:
        if g.is_preassigned:
            continue

        g.matchups_that_prefer_this_slot = set()

    for m in matchups:
        if m.is_preassigned:
            continue

        assert m.preferred_home_team is not None

        m.preferred_gameslots = []
        m.backup_gameslots = []

        for g in gameslots:
            if g.is_preassigned:
                continue
            if any(b.prohibits_matchup_in_slot(m, g) for b in blackouts):
                continue

            assert g.matchups_that_prefer_this_slot is not None

            if m.preferred_home_team.home_location == g.location:
                m.preferred_gameslots.append(g)
                g.matchups_that_prefer_this_slot.add(m)
            else:
                m.backup_gameslots.append(g)

        random.shuffle(m.preferred_gameslots)
        random.shuffle(m.backup_gameslots)


def select_gameslots_for_matchups(window_constraints: list[WindowConstraint]):
    print("Preferred selection phase started.")

    select_preferred_gameslots(window_constraints)

    print("Preferred selection phase complete.")

    matchups_using_backup_slots = list(filter(lambda m: m.selected_gameslot is None, matchups))

    print(f"Number of matchups that did not get preferred selection: {len(matchups_using_backup_slots)}")
    print("Block sizes after preferred selection phase:")
    print()
    print_block_size_metrics()

    print("Backup selection phase started.")

    matchups_using_backup_slots.sort(key=lambda m: len(unwrap(m.backup_gameslots)))
    success = select_backup_gameslots(matchups_using_backup_slots, 0, window_constraints)

    print(f"Backup selection completed with {backup_selection_dead_ends} dead ends.")

    return success


def select_preferred_gameslots(window_constraints: list[WindowConstraint]):
    # Randomize processing order for matchups. If we don't do this, matchups near the end
    # of matchups.csv get processed later, meaning their preferences are less likely to be
    # satisified.
    unprocessed_matchups = [m for m in matchups if m.selected_gameslot is None]
    random.shuffle(unprocessed_matchups)

    print("Starting step 1 of preferred selection phase (same home matchups)")

    # If both teams in a matchup have the same home location, it would be egregious
    # for them to have to travel elsewhere. So those matchups are processed early to
    # make sure they get their preferred location.
    same_home_matchups = [m for m in unprocessed_matchups if m.team_a.home_location == m.team_b.home_location]
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
    print(f"Scarce location(s): {', '.join([str(l) for l in locations.values() if l.is_scarce])}")
    print(f"{len(scarce_home_matchups)} scarce home matchups to process")
    unprocessed_scarce_home_matchups = scarce_home_matchups.copy()
    while unprocessed_scarce_home_matchups:
        if len(unprocessed_scarce_home_matchups) % 10 == 0:
            print(f"{len(unprocessed_scarce_home_matchups)} remaining")

        smallest_home_percentage = min(
            unwrap(m.preferred_home_team).get_home_percentage() for m in unprocessed_scarce_home_matchups
        )
        matchups_with_smallest_home_percentage = [
            m
            for m in unprocessed_scarce_home_matchups
            if abs(unwrap(m.preferred_home_team).get_home_percentage() - smallest_home_percentage) < 0.0001
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

        matchup_to_process = get_most_constrained_matchup_in_list(unprocessed_matchups, window_constraints)
        select_preferred_gameslot_for_matchup(matchup_to_process, window_constraints)
        unprocessed_matchups.remove(matchup_to_process)


def select_preferred_gameslot_for_matchup(matchup: Matchup, window_constraints: list[WindowConstraint]) -> bool:
    """
    If the given matchup has at least one preferred gameslot that can be selected, selects the best preferred gameslot.
    Returns `True` if a gameslot was selected, `False` if not.
    """

    assert matchup.preferred_gameslots is not None

    for reuse_location in True, False:
        for use_weekend in True, False:
            for avoid_consecutive_days in True, False:
                for gameslot in matchup.preferred_gameslots:
                    if gameslot.selected_matchup is not None:
                        continue
                    if reuse_location and gameslot.location.num_games_by_date[gameslot.date] == 0:
                        continue
                    if not reuse_location and gameslot.location.num_games_by_date[gameslot.date] != 0:
                        continue
                    if use_weekend and gameslot.date.weekday() not in [4, 5]:
                        continue
                    if not use_weekend and gameslot.date.weekday() in [4, 5]:
                        continue
                    if avoid_consecutive_days and selection_will_create_consecutive_game_days(matchup, gameslot):
                        continue
                    if not avoid_consecutive_days and not selection_will_create_consecutive_game_days(
                        matchup, gameslot
                    ):
                        continue
                    if not all(w.is_satisfied_by_selection(matchup, gameslot) for w in window_constraints):
                        continue

                    matchup.select_gameslot(gameslot)
                    return True

    return False


def get_most_constrained_matchup_in_list(
    matchup_list: list[Matchup], window_constraints: list[WindowConstraint]
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

    return unwrap(most_constrained_matchup)


def get_slot_availability_score(matchup: Matchup, window_constraints: list[WindowConstraint]) -> float:
    """
    Returns a score indicating how many preferred gameslots are still available for the given matchup.

    This score helps us to decide the order in which to process matchups. The idea is that if a matchup has many
    preferred slots, it's unlikely that an earlier matchup will take all of them. Therefore it's safe to consider it at
    the end. On the other hand, if a matchup has few preferred slots, then it's in danger of losing its preferred slots,
    so it should be considered early.
    """

    if matchup.selected_gameslot is not None:
        raise Exception(
            "Tried to calculate slot availability score for matchup " + "that has already selected a gameslot."
        )
    if matchup.preferred_gameslots is None:
        raise Exception(
            "Preferred gameslots must be initialized on a matchup before slot availability score can be calculated."
        )

    return len(
        [
            g
            for g in matchup.preferred_gameslots
            if g.selected_matchup is None and all(w.is_satisfied_by_selection(matchup, g) for w in window_constraints)
        ]
    )


def select_backup_gameslots(
    matchups_using_backup_slots: list[Matchup],
    start: int,
    window_constraints: list[WindowConstraint],
):
    global backup_selection_dead_ends
    global backup_selection_depth
    if start == 0:
        backup_selection_dead_ends = 0
        backup_selection_depth = 0

    if start > backup_selection_depth:
        backup_selection_depth = start
        print(f"New depth reached: {backup_selection_depth} / {len(matchups_using_backup_slots)}")

    if backup_selection_dead_ends >= 10000:
        # It's taking too long. We assume it will not complete in a reasonable time.
        return False

    if start == len(matchups_using_backup_slots):
        return True

    matchup = matchups_using_backup_slots[start]
    assert matchup.backup_gameslots is not None

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
                        if reuse_single_use_location and gameslot.location.num_games_by_date[gameslot.date] != 1:
                            continue
                        if not reuse_single_use_location and gameslot.location.num_games_by_date[gameslot.date] == 1:
                            continue
                        if reuse_multi_use_location and gameslot.location.num_games_by_date[gameslot.date] <= 1:
                            continue
                        if not reuse_multi_use_location and gameslot.location.num_games_by_date[gameslot.date] > 1:
                            continue
                        if give_nonpreferred_team_home and not selection_gives_either_team_home(matchup, gameslot):
                            continue
                        if not give_nonpreferred_team_home and selection_gives_either_team_home(matchup, gameslot):
                            continue
                        if use_weekend and gameslot.date.weekday() not in [4, 5]:
                            continue
                        if not use_weekend and gameslot.date.weekday() in [4, 5]:
                            continue
                        if avoid_consecutive_days and selection_will_create_consecutive_game_days(matchup, gameslot):
                            continue
                        if not avoid_consecutive_days and not selection_will_create_consecutive_game_days(
                            matchup, gameslot
                        ):
                            continue
                        if not all(w.is_satisfied_by_selection(matchup, gameslot) for w in window_constraints):
                            continue

                        matchup.select_gameslot(gameslot)

                        if select_backup_gameslots(matchups_using_backup_slots, start + 1, window_constraints):
                            return True

                        matchup.deselect_gameslot()

    backup_selection_dead_ends += 1
    if backup_selection_dead_ends % 1000 == 0:
        print(f"Backup selection has hit {backup_selection_dead_ends} dead ends")

    return False


def selection_gives_either_team_home(matchup: Matchup, gameslot: Gameslot):
    return gameslot.location == matchup.team_a.home_location or gameslot.location == matchup.team_b.home_location


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


def write_output_files(output_dir_path: str):
    with open(f"{output_dir_path}/master.txt", "w") as f:
        print_master_schedule(f)

    with open(f"{output_dir_path}/pasteable.txt", "w") as f:
        print_pasteable_schedule(f)

    with open(f"{output_dir_path}/breakout.txt", "w") as f:
        print_breakout_schedule(f)

    with open(f"{output_dir_path}/metrics.txt", "w") as f:
        print_metrics(f)


def print_master_schedule(file=None):
    gameslots_by_day = defaultdict(list)
    blackouts_by_day = defaultdict(list)

    for g in gameslots:
        gameslots_by_day[g.date].append(g)
    for b in blackouts:
        blackouts_by_day[b.date].append(b)

    schedule_table: Sequence[Sequence[object]] = [
        ["Schedule Slot", "Scheduled Matchup", "Blackouts"],
        ["-------------", "-----------------", "---------"],
    ]

    for day in sorted(gameslots_by_day.keys()):
        gameslots_on_day = gameslots_by_day[day]
        blackouts_on_day = blackouts_by_day[day]

        for i, gameslot in enumerate(gameslots_on_day):
            blackout_str = "" if i >= len(blackouts_on_day) else str(blackouts_on_day[i])
            matchup_str = "Open" if gameslot.selected_matchup is None else str(gameslot.selected_matchup)

            row = [str(gameslot), matchup_str, blackout_str]

            schedule_table.append(row)

        if len(blackouts_on_day) > len(gameslots_on_day):
            num_unshown_blackouts = len(blackouts_on_day) - len(gameslots_on_day)
            schedule_table[-1][-1] += f" ({num_unshown_blackouts} blackouts not shown)"

        schedule_table.append(["", "", ""])

    utils.pretty_print_table(schedule_table, file=file)


def print_pasteable_schedule(file=None):
    gameslots_by_day = defaultdict(list)

    for g in gameslots:
        gameslots_by_day[g.date].append(g)

    for day in sorted(gameslots_by_day.keys()):
        gameslots_on_day = gameslots_by_day[day]

        for gameslot in gameslots_on_day:
            if gameslot.selected_matchup is None:
                matchup_str = "\t\tOPEN"
            else:
                matchup = gameslot.selected_matchup
                division = matchup.division
                division_str = "7/8B" if division in ["7/8B South", "7/8B North"] else division
                home_team, away_team = matchup.get_teams_in_home_away_order()

                matchup_str = f"{division_str}\t{home_team.name}\t{away_team.name}"

            print(matchup_str, file=file)

        # print(file=file)


def print_breakout_schedule(file=None):
    for team in teams.values():
        table = []
        table.append(["", "Date", "Day", "Time", "Home Team", "Away Team", "Location"])
        table.append(["", "----", "---", "----", "---------", "---------", "--------"])

        team.matchups.sort(key=lambda m: unwrap(m.selected_gameslot).date)

        for i, matchup in enumerate(team.matchups):
            assert matchup.selected_gameslot is not None

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

        print(str(team), file=file)
        print("-" * len(str(team)), file=file)
        utils.pretty_print_table(table, file=file)
        print(file=file)


def print_metrics(file=None):
    print_home_preference_metrics(file=file)
    print(file=file)
    print_non_preferred_gameslot_metrics(file=file)
    print(file=file)
    print_largest_gap_metrics(file=file)
    print(file=file)
    print_block_size_metrics(file=file)
    print(file=file)
    print_weekday_metrics(file=file)
    print(file=file)
    print_consecutive_game_day_metrics(file=file)


def print_home_preference_metrics(file=None):

    print("Teams with lowest preferred asymmetric home percentage:\n", file=file)

    table: list[Sequence[object]] = [
        ["Team", "Preferred asymmetric home percentage"],
        ["----", "------------------------------------"],
    ]

    team_metrics = []
    for team in teams.values():
        denominator = team.num_asymmetric_matchups_with_home_preference_chosen
        numerator = team.num_asymmetric_matchups_preferring_this_team_as_home
        percentage = numerator / denominator
        team_metrics.append((percentage, str(team), numerator, denominator))

    for percentage, team_name, numerator, denominator in sorted(team_metrics)[:7]:
        table.append([team_name, f"{percentage:.1%} ({numerator}/{denominator})"])

    utils.pretty_print_table(table, file=file)
    print(file=file)

    print("Teams with lowest actual asymmetric home percentage:\n", file=file)

    table: list[Sequence[object]] = [
        ["Team", "Actual asymmetric home percentage"],
        ["----", "---------------------------------"],
    ]

    team_metrics = []
    for team in teams.values():
        asymmetric_matchups = [
            matchup for matchup in team.matchups if matchup.team_a.home_location != matchup.team_b.home_location
        ]
        denominator = len(asymmetric_matchups)
        numerator = sum(
            unwrap(matchup.selected_gameslot).location == team.home_location for matchup in asymmetric_matchups
        )
        percentage = numerator / denominator
        team_metrics.append((percentage, str(team), numerator, denominator))

    for percentage, team_name, numerator, denominator in sorted(team_metrics)[:7]:
        table.append([team_name, f"{percentage:.1%} ({numerator}/{denominator})"])

    utils.pretty_print_table(table, file=file)


def print_consecutive_game_day_metrics(file=None):
    table: list[Sequence[object]] = [
        ["# of Consecutive Game Day Pairs", "# of Teams With That Many Pairs"],
        ["-------------------------------", "-------------------------------"],
    ]

    num_pairs_to_num_teams = get_num_consecutive_pairs_to_num_teams()

    for num_pairs, num_teams in sorted(num_pairs_to_num_teams.items()):
        table.append([num_pairs, num_teams])

    table.append(["", ""])

    total_pairs = sum(p * t for p, t in num_pairs_to_num_teams.items())
    table.append(["TOTAL PAIRS", total_pairs])

    utils.pretty_print_table(table, file=file)


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


def print_non_preferred_gameslot_metrics(file=None):
    non_preferred_matchups = list(filter(lambda m: not m.selected_gameslot_is_preferred, matchups))
    non_preferred_matchups.sort(key=lambda m: unwrap(m.preferred_home_team).name)
    non_preferred_matchups.sort(key=lambda m: unwrap(m.preferred_home_team).division)

    print(
        f"{len(non_preferred_matchups)} out of {len(matchups)} matchups received "
        + "non-preferred locations. Non-preferred assignments (if any) are listed below:",
        file=file,
    )
    print(file=file)
    if non_preferred_matchups:
        table: list[Sequence[object]] = [
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
                    unwrap(matchup.preferred_home_team).name,
                    unwrap(matchup.selected_gameslot).location,
                ]
            )
        utils.pretty_print_table(table, file=file)
        print(file=file)

    num_games_at_neither_home = 0
    for m in matchups:
        assert m.selected_gameslot is not None
        if (
            m.selected_gameslot.location != m.team_a.home_location
            and m.selected_gameslot.location != m.team_b.home_location
        ):
            num_games_at_neither_home += 1
    print(
        f"{num_games_at_neither_home} games were at *neither* team's home location "
        + "(you can find them in the table above).",
        file=file,
    )


def print_largest_gap_metrics(file=None):
    table: list[Sequence[object]] = [
        ["Team", "Largest gap between games"],
        ["----", "-------------------------"],
    ]

    table.extend(get_largest_team_gap_pairs())
    utils.pretty_print_table(table, file=file)


def print_block_size_metrics(file=None):
    table: list[Sequence[object]] = [
        ["# of Games in Block", "# of Occurrences"],
        ["-------------------", "----------------"],
    ]

    block_sizes_to_counts = get_block_sizes_to_counts()

    for block_size, count in sorted(block_sizes_to_counts.items()):
        table.append([block_size, count])

    total_blocks = sum(block_sizes_to_counts.values())
    table.append(["", ""])
    table.append(["TOTAL BLOCKS", total_blocks])

    utils.pretty_print_table(table, file=file)


def get_block_sizes_to_counts() -> dict[int, int]:
    block_sizes_to_counts = defaultdict(int)
    for location in locations.values():
        for num_games in location.num_games_by_date.values():
            if num_games != 0:
                block_sizes_to_counts[num_games] += 1

    return block_sizes_to_counts


def print_weekday_metrics(file=None):
    table: list[Sequence[object]] = [
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

    utils.pretty_print_table(table, file=file)


def get_num_weekday_games_to_num_teams():
    num_weekday_games_to_num_teams = defaultdict(int)

    for team in teams.values():
        num_weekday_games = 0

        for matchup in team.matchups:
            game_is_weekend = unwrap(matchup.selected_gameslot).date.weekday() in [4, 5]
            if not game_is_weekend:
                num_weekday_games += 1

        num_weekday_games_to_num_teams[num_weekday_games] += 1

    return num_weekday_games_to_num_teams


def get_largest_team_gap_pairs() -> list[tuple[Team, int]]:
    gaps = []
    for team in teams.values():
        game_dates = sorted(unwrap(matchup.selected_gameslot).date for matchup in team.matchups)
        gaps.extend(
            (team, (second_date - first_date).days)
            for first_date, second_date in zip(game_dates, game_dates[1:], strict=False)
        )

    return nlargest(5, gaps, key=lambda team_gap: team_gap[1])


def do_test_run_for_seeds(
    start_seed,
    end_seed,
    input_dir_path,
    output_dir_path,
    window_constraints,
    scarce_location_names,
):
    seed_file_path = output_dir_path + "/seeds.txt"

    header = (
        "seed - "
        "num weekday games - "
        "bad asymmetric home percentages - "
        "smallest block size, num smallest blocks - "
        "most consec pairs, teams with most consec - "
        "longest gaps between games"
    )
    with open(seed_file_path, "w") as f:
        f.write(header + "\n")

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
        total_weekday_games = sum(g * t for g, t in num_weekday_games_to_num_teams.items())

        asymmetric_home_fractions = []
        for team in teams.values():
            asymmetric_matchups = [
                matchup for matchup in team.matchups if matchup.team_a.home_location != matchup.team_b.home_location
            ]
            home_fraction = sum(
                unwrap(matchup.selected_gameslot).location == team.home_location for matchup in asymmetric_matchups
            ) / len(asymmetric_matchups)
            asymmetric_home_fractions.append(home_fraction)

        # List of all asymmetric home percentages less than 50% starting with the lowest
        bad_asymmetric_home_percentages = [
            f"{fraction:.1%}"[:-1] for fraction in sorted(asymmetric_home_fractions) if fraction < 0.5
        ]
        bad_asymmetric_home_percentages_str = ",".join(bad_asymmetric_home_percentages)

        block_sizes_to_counts = get_block_sizes_to_counts()
        smallest_block_size_to_count = min(block_sizes_to_counts.items())
        smallest_block_size, num_smallest_blocks = smallest_block_size_to_count

        num_consec_pairs_to_num_teams = get_num_consecutive_pairs_to_num_teams()
        largest_consec_pairs_to_num_teams = max(num_consec_pairs_to_num_teams.items())
        most_consec_pairs, teams_with_most_consec = largest_consec_pairs_to_num_teams

        longest_gaps_str = ",".join(str(gap) for _, gap in get_largest_team_gap_pairs())

        file_line = (
            f"{random_seed}"
            + f" - {total_weekday_games}"
            + f" - {bad_asymmetric_home_percentages_str}"
            + f" - {smallest_block_size} {num_smallest_blocks}"
            + f" - {most_consec_pairs} {teams_with_most_consec}"
            + f" - {longest_gaps_str}"
        )
        f.write(file_line + "\n")
