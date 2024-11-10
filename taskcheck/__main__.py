import tomllib
import argparse

from taskcheck.parallel import check_tasks_parallel
from taskcheck.sequential import check_tasks_sequentially
from taskcheck.common import config_dir

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument(
    "-v", "--verbose", action="store_true", help="increase output verbosity"
)

args = arg_parser.parse_args()


# Load working hours and exceptions from TOML file
def load_config():
    with open(config_dir / "taskcheck.toml", "rb") as f:
        config = tomllib.load(f)
    return config


def main():
    # Load data and check tasks
    config = load_config()
    algo = config["scheduler"].get("algorithm", "parallel")
    if algo == "parallel":
        block = config["scheduler"].get("block", 2)
        check_tasks_parallel(config, block, verbose=args.verbose)
    elif algo == "sequential":
        check_tasks_sequentially(config, verbose=args.verbose)
    else:
        raise ValueError(f"Unknown algorithm: {algo}")


if __name__ == "__main__":
    main()
