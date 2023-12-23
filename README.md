# Versizzle

A game scheduler for sports leagues.

## Basics

Versizzle takes in a list of **matchups** and a list of **gameslots**. 

- **matchup** - a game that must be played between two teams
- **gameslot** - an available timeslot for a game at some location

It assigns each matchup to a gameslot. These assignments constitute a schedule.

## Features

- **blackouts** - gameslots can be marked as unsuitable ("blacked out") for some teams
- **home balancing** - if possible, each team is given an equal number of home and away games
- **window constraints** - to ensure an even distribution of games throughout the season, Versizzle can enforce constraints like "no team plays two games on the same day" or "no team plays more than two games in any five-day window" 
- **game blocking** - Versizzle strongly prefers to schedule games in consecutive blocks at a single location. This is convenient for referees who want to work a series of games in a row
- **preassignments** - a portion of the schedule can be filled in manually, and the scheduler will handle the rest
- **seed searching** - Versizzle can run many randomized schedules and output metrics for each, allowing the user to choose the best possible schedule

## Generate a schedule

1. Clone the repository and `cd` into it.
2. Install `requirements.txt` into a virtual environment. For example, on Ubuntu:
    
    ```
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3. Copy all of the `csv` files from `examples/basketball_2024` into the `in` folder.
4. Run the scheduler:

    ```
    python3 -m versizzle
    ```

5. Verify that all of the expected files appeared in `out`:
    - `breakout.txt`
    - `master.txt`
    - `metrics.txt`
    - `pasteable.txt`

## Run a seed search

Instead of generating a single schedule, Versizzle can also be configured to run many possible schedules, outputting metrics for each. By examining these metrics, you can look for a schedule with optimal properties. To perform a seed search:

1. Uncomment the `seed_search` block in `config.yml`.
2. Run the scheduler:

    ```
    python3 -m versizzle
    ```

3. Verify that `seeds.txt` appeared in `out`.
