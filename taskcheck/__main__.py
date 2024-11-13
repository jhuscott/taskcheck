import tomllib
import argparse

from taskcheck.parallel import check_tasks_parallel
from taskcheck.sequential import check_tasks_sequentially
from taskcheck.common import config_dir

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument(
    "-v", "--verbose", action="store_true", help="increase output verbosity."
)
arg_parser.add_argument(
    "-i",
    "--install",
    action="store_true",
    help="install the UDAs, required settings, and default config file.",
)
arg_parser.add_argument(
    "-r",
    "--report",
    action="store",
    help="generate a report of the tasks based on the scheduling; can be any Taskwarrior datetime specification (e.g. today, tomorrow, eom, som, 1st, 2nd, etc.). It is considered as `by`, meaning that the report will be generated for all the days until the specified date and including it.",
)

args = arg_parser.parse_args()


# Load working hours and exceptions from TOML file
def load_config():
    with open(config_dir / "taskcheck.toml", "rb") as f:
        config = tomllib.load(f)
    return config


def main():
    # Load data and check tasks
    if args.install:
        from taskcheck.install import install

        install()
        return

    if args.report:
        from taskcheck.report import generate_report

        config = load_config()
        generate_report(config, args.report, args.verbose)
        return

    config = load_config()
    algo = config["scheduler"].get("algorithm", "parallel")
    if algo == "parallel":
        check_tasks_parallel(config, verbose=args.verbose)
    elif algo == "sequential":
        check_tasks_sequentially(config, verbose=args.verbose)
    else:
        raise ValueError(f"Unknown algorithm: {algo}")


if __name__ == "__main__":
    main()
