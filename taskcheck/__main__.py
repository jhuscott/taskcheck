import subprocess
import tomllib
import json
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import appdirs

from taskcheck.ical import ical_to_dict

config_dir = Path(appdirs.user_config_dir("task"))

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument(
    "-t",
    "--today",
    type=float,
    action="store",
    help="specify how many hours you have already worked today (default: 0)",
    default=0,
)
arg_parser.add_argument(
    "-v", "--verbose", action="store_true", help="increase output verbosity"
)

args = arg_parser.parse_args()

# Taskwarrior status to avoid
AVOID_STATUS = ["completed", "deleted", "recurring"]

long_range_time_map = {}


# Load working hours and exceptions from TOML file
def load_config():
    with open(config_dir / "taskcheck.toml", "rb") as f:
        config = tomllib.load(f)
    return config


# Get tasks from Taskwarrior and sort by urgency
def get_tasks():
    result = subprocess.run(["task", "export"], capture_output=True, text=True)
    tasks = json.loads(result.stdout)
    return sorted(
        (task for task in tasks if "estimated" in task),
        key=lambda t: -t.get("urgency", 0),
    )


def _hours_to_decimal(hour):
    return int(hour) + (hour - int(hour)) * 100 / 60


def _hours_to_time(hour):
    hours = int(hour)
    minutes = int((hour - hours) * 60)
    return datetime.strptime(f"{hours}:{minutes}", "%H:%M").time()


def _time_to_hours(time):
    return time.hour + time.minute / 60


def get_available_hours(time_map, date, calendars):
    day_of_week = date.strftime("%A").lower()
    schedule = time_map.get(day_of_week, [])
    available_hours = sum(
        _hours_to_decimal(end) - _hours_to_decimal(start) for start, end in schedule
    )

    blocked_hours = 0
    for schedule_start, schedule_end in schedule:
        # schedule_start and schedule_end are numbers, actually
        # so let's convert them to datetime.time objects
        schedule_start = _hours_to_time(schedule_start)
        schedule_end = _hours_to_time(schedule_end)
        for calendar in calendars:
            for event in calendar:
                if event["start"].date() > date:
                    break
                elif event["end"].date() < date:
                    continue
                # check if the event overlaps with one of the working hours
                event_start = event["start"].time()
                event_end = event["end"].time()
                if event_start < schedule_end and event_end > schedule_start:
                    blocked_hours += _time_to_hours(
                        min(schedule_end, event_end)
                    ) - _time_to_hours(max(schedule_start, event_start))
    available_hours -= blocked_hours
    return available_hours


def PDTH_to_hours(duration_str):
    # string format is P#DT#H
    # with D and H optional
    duration_str = duration_str[1:]  # Remove leading "P"
    days, hours = 0, 0
    if "D" in duration_str:
        days, duration_str = duration_str.split("D")
        days = int(days)
    if "H" in duration_str:
        hours = int(duration_str.split("T")[1].split("H")[0])
        return days * 24 + hours


def get_long_range_time_map(time_maps, time_map_names, days_ahead, calendars):
    key = ",".join(time_map_names)
    if key in long_range_time_map:
        task_time_map = long_range_time_map[key]
    else:
        if args.verbose:
            print(f"Calculating long range time map for {key}")
        task_time_map = []
        for d in range(days_ahead):
            date = datetime.today().date() + timedelta(days=d)
            daily_hours = 0
            for time_map_name in time_map_names:
                if time_map_name not in time_maps:
                    raise ValueError(f"Time map '{time_map_name}' does not exist.")
                time_map = time_maps[time_map_name]
                daily_hours += get_available_hours(time_map, date, calendars)
            task_time_map.append(daily_hours)
        long_range_time_map[key] = task_time_map

    return task_time_map


def schedule_task_on_day(
    is_starting,
    day_offset,
    start_date,
    end_date,
    task_remaining_hours,
    task_time_map,
    today,
    used_hours,
    wait,
):
    # we can schedule task on this day
    employable_hours = task_time_map[day_offset] - used_hours[day_offset]
    current_date = today + timedelta(days=day_offset)
    if wait and current_date < wait:
        if args.verbose:
            print(f"Skipping date {current_date} because of wait date {wait}")
        return start_date, end_date, task_remaining_hours, is_starting

    if is_starting:
        if args.verbose:
            print(f"Starting task on {current_date}")
        is_starting = False
        start_date = current_date

    if task_remaining_hours <= employable_hours:
        # consume all the remaining task's hours
        used_hours[day_offset] += task_remaining_hours
        task_remaining_hours = 0
        end_date = current_date
        if args.verbose:
            print(f"Task can be completed on {current_date}")
            print(f"Used hours on {current_date}: {used_hours[day_offset]}")
    else:
        # consume all the available hours on this task
        task_remaining_hours -= employable_hours
        used_hours[day_offset] += employable_hours
        if args.verbose:
            print(f"Working for {employable_hours} hours on task on {current_date}")
    return start_date, end_date, task_remaining_hours, is_starting


def mark_end_date(due_date, end_date, start_date, id, description=None):
    start_end_fields = [f"scheduled:{start_date}", f"completion_date:{end_date}"]

    subprocess.run(
        [
            "task",
            str(id),
            "modify",
            *start_end_fields,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if due_date is not None and end_date > due_date:
        # print in bold red using ANSI escape codes
        description = "('" + description + "')" if description is not None else ""
        print(f"\033[1;31mTask {id} {description} may not be completed on time\033[0m")


def get_calendars(config):
    calendars = []
    for calname in config["calendars"]:
        calendar = config["calendars"][calname]
        calendar = ical_to_dict(
            calendar["url"],
            config["scheduler"]["days_ahead"],
            all_day=calendar["event_all_day_is_blocking"],
            expiration=calendar["expiration"],
            verbose=args.verbose,
        )
        calendar.sort(key=lambda e: e["start"])
        calendars.append(calendar)
    if args.verbose:
        print(f"Loaded {len(calendars)} calendars")
    return calendars


# Check if tasks can be completed on time sequentially
def check_tasks_sequentially(tasks, config):
    time_maps = config["time_maps"]
    today = datetime.today().date()
    todo = [True if t["status"] not in AVOID_STATUS else False for t in tasks]
    used_hours = [args.today] + [0] * config["scheduler"]["days_ahead"]
    calendars = get_calendars(config)

    while any(todo):
        for i, task in enumerate(tasks):
            if not todo[i]:
                # skipping tasks already completed
                continue

            due_date = (
                datetime.strptime(task["due"], "%Y%m%dT%H%M%SZ").date()
                if "due" in task
                else None
            )
            wait_date = (
                datetime.strptime(task["wait"], "%Y%m%dT%H%M%SZ").date()
                if "wait" in task
                else None
            )
            estimated_hours = (
                PDTH_to_hours(task["estimated"]) if "estimated" in task else None
            )  # Remove trailing "PT" and "H"
            time_map_names = (
                task.get("time_map").split(",") if "time_map" in task else None
            )
            if estimated_hours is None or time_map_names is None:
                todo[i] = False
                if args.verbose:
                    print(
                        f"Task {task['id']} ('{task['description']}') has no estimated time or time map: {estimated_hours}, {time_map_names}"
                    )
                continue
            # if args.verbose:
            #     print(
            #         f"Checking task {task['id']} ('{task['description']}') with estimated hours: {estimated_hours} and wait date: {wait_date}"
            #     )

            task_remaining_hours = estimated_hours
            task_time_map = get_long_range_time_map(
                time_maps, time_map_names, config["scheduler"]["days_ahead"], calendars
            )

            # Simulate work day-by-day until task is complete or past due
            is_starting = True
            start_date = end_date = None
            for offset in range(len(task_time_map)):
                if task_time_map[offset] > used_hours[offset]:
                    (start_date, end_date, task_remaining_hours, is_starting) = (
                        schedule_task_on_day(
                            is_starting,
                            offset,
                            start_date,
                            end_date,
                            task_remaining_hours,
                            task_time_map,
                            today,
                            used_hours,
                            wait_date,
                        )
                    )

                if end_date is not None:
                    todo[i] = False
                    mark_end_date(
                        due_date, end_date, start_date, task["id"], task["description"]
                    )
                    break


# Load data and check tasks
config = load_config()
tasks = get_tasks()
check_tasks_sequentially(tasks, config)
