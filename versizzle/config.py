import yaml

with open("config.yml", "r") as file:
    config = yaml.safe_load(file)

if "input_dir" not in config:
    raise Exception("config.yml should include an `input_dir` field")

if "output_dir" not in config:
    raise Exception("config.yml should include an `output_dir` field")

if "window_constraints" not in config:
    config["window_constraints"] = []

if "scarce_locations" not in config:
    config["scarce_locations"] = []
