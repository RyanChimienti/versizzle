from versizzle.config import config
from versizzle.window_constraint import WindowConstraint
import versizzle.scheduler as scheduler

print(f"Found config: {config}")

window_constraints = [
    WindowConstraint(w["days"], w["max_games"]) for w in config["window_constraints"]
]
scarce_location_names = config["scarce_locations"]
input_dir_path = config["input_dir"]
output_dir_path = config["output_dir"]

if "seed_search" in config:
    scheduler.do_test_run_for_seeds(
        config["seed_search"]["first_seed"],
        config["seed_search"]["last_seed"],
        input_dir_path,
        output_dir_path,
        window_constraints,
        scarce_location_names,
    )
else:
    scheduler.generate_schedule(
        input_dir_path,
        output_dir_path,
        config["seed"],
        window_constraints,
        scarce_location_names,
    )
