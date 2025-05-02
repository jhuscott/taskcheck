import tomllib
import argparse

from taskcheck.parallel import check_tasks_parallel
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
arg_parser.add_argument(
    "-s",
    "--schedule",
    action="store_true",
    help="perform the scheduling algorithm, giving a schedule and a scheduling UDA and alerting for not completable tasks",
)

args = arg_parser.parse_args()


# Load working hours and exceptions from TOML file
def load_config():
    with open(config_dir / "taskcheck.toml", "rb") as f:
        config = tomllib.load(f)
    return config


def main():
    # Load data and check tasks
    print_help = True
    if args.install:
        from taskcheck.install import install

        install()
        return

    if args.schedule:
        config = load_config()
        check_tasks_parallel(config, verbose=args.verbose)
        print_help = False

    if args.report:
        from taskcheck.report import generate_report

        config = load_config()
        generate_report(config, args.report, args.verbose)
        print_help = False

    if print_help:
        arg_parser.print_help()


if __name__ == "__main__":
    main()
