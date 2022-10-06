from datetime import timedelta
from gameslot import Gameslot
from matchup import Matchup


class WindowConstraint:
    def __init__(self, window_size, max_games_in_window):
        self.window_size = window_size
        self.max_games_in_window = max_games_in_window

    # Takes a matchup without a selected gameslot, and a potential gameslot to select.
    # Returns False if the matchup is prohibited from selecting the gameslot because
    # one of the teams will have too many games in the window. Otherwise returns True.
    def is_satisfied_by_selection(self, matchup: Matchup, gameslot: Gameslot) -> bool:
        if matchup.selected_gameslot is not None:
            raise Exception(
                "Cannot test window constraint if matchup is already assigned to a gameslot"
            )

        candidate_date = gameslot.date

        for team in matchup.team_a, matchup.team_b:
            num_selected_dates_in_window = 0

            left = candidate_date - timedelta(days=self.window_size - 1)
            right = left - timedelta(days=1)

            for _ in range(self.window_size):
                right += timedelta(days=1)
                num_selected_dates_in_window += len(team.games_by_date[right])

            if num_selected_dates_in_window >= self.max_games_in_window:
                # Equality will lead to a violation because the candidate will push
                # num_selected_dates_in_window above the max.
                return False

            for _ in range(self.window_size - 1):
                num_selected_dates_in_window -= len(team.games_by_date[left])
                left += timedelta(days=1)
                right += timedelta(days=1)
                num_selected_dates_in_window += len(team.games_by_date[right])

                if num_selected_dates_in_window >= self.max_games_in_window:
                    return False

        return True
