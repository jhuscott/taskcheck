import re
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
    minutes = int((hour - hours) * 100)
    return datetime.strptime(f"{hours}:{minutes}", "%H:%M").time()


def _time_to_decimal(time):
    # round to 2 digits after the point
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
        schedule_blocked_hours = 0
        for calendar in calendars:
            for event in calendar:
                # we use str to make object serializable as jsons
                if isinstance(event["start"], str):
                    event["start"] = datetime.fromisoformat(event["start"])
                if isinstance(event["end"], str):
                    event["end"] = datetime.fromisoformat(event["end"])

                if event["start"].date() > date:
                    break
                elif event["end"].date() < date:
                    continue

                # check if the event overlaps with one of the working hours
                event_start = event["start"].time()
                event_end = event["end"].time()
                if event["start"].date() < date:
                    event_start = datetime(date.year, date.month, date.day, 0, 0).time()
                if event["end"].date() > date:
                    event_end = datetime(date.year, date.month, date.day, 23, 59).time()

                if event_start < schedule_end and event_end > schedule_start:
                    schedule_blocked_hours += _time_to_decimal(
                        min(schedule_end, event_end)
                    ) - _time_to_decimal(max(schedule_start, event_start))
        if args.verbose and schedule_blocked_hours > 0:
            print(
                f"Blocked hours on {date} between {schedule_start} and {schedule_end}: {schedule_blocked_hours}"
            )
        blocked_hours += schedule_blocked_hours
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


def hours_to_PDTH(hours):
    days = hours // 24
    hours = hours % 24
    return f"P{days}DT{hours}H"


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

    today_time = _time_to_decimal(datetime.now().time())
    today_weekday = datetime.today().strftime("%A").lower()
    today_used_hours = 0
    # compare with the time_maps of today
    for time_map_name in time_map_names:
        time_map = time_maps[time_map_name].get(today_weekday)
        if time_map:
            for schedule_start, schedule_end in time_map:
                if schedule_start <= today_time <= schedule_end:
                    today_used_hours += today_time - schedule_start
                    break
                elif today_time > schedule_end:
                    today_used_hours += schedule_end - schedule_start
    return task_time_map, today_used_hours


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
    scheduling_note,
):
    # we can schedule task on this day
    employable_hours = task_time_map[day_offset] - used_hours[day_offset]
    # avoid using too small values
    employable_hours = 0.01 if 0.01 > employable_hours > 0 else employable_hours
    current_date = today + timedelta(days=day_offset)
    if wait and current_date <= wait:
        if args.verbose:
            print(f"Skipping date {current_date} because of wait date {wait}")
        return start_date, end_date, task_remaining_hours, is_starting, scheduling_note

    if is_starting:
        if args.verbose:
            print(f"Starting task on {current_date}")
        is_starting = False
        start_date = current_date

    # minimum value we admit is 0.01 (1 minute)
    if task_remaining_hours <= employable_hours + 0.01:
        # consume all the remaining task's hours
        if scheduling_note != "":
            scheduling_note += "\n"
        scheduling_note += f"{current_date}: {task_remaining_hours:.2f} hours"
        used_hours[day_offset] += task_remaining_hours
        task_remaining_hours = 0
        end_date = current_date
        if args.verbose:
            print(f"Task can be completed on {current_date}")
            print(f"Used hours on {current_date}: {used_hours[day_offset]}")
    else:
        # consume all the available hours on this task
        if scheduling_note != "":
            scheduling_note += "\n"
        scheduling_note += f"{current_date}: {employable_hours:.2f} hours"
        task_remaining_hours -= employable_hours
        used_hours[day_offset] += employable_hours
        if args.verbose:
            print(f"Working for {employable_hours} hours on task on {current_date}")
    return start_date, end_date, task_remaining_hours, is_starting, scheduling_note


def mark_end_date(
    due_date, end_date, start_date, scheduling_note, id, description=None
):
    start_end_fields = [f"scheduled:{start_date}", f"completion_date:{end_date}"]

    subprocess.run(
        [
            "task",
            str(id),
            "modify",
            *start_end_fields,
            f'scheduling:"{scheduling_note}"',
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
            tz_name=calendar.get("timezone"),
        )
        calendar.sort(key=lambda e: e["start"])
        calendars.append(calendar)
    if args.verbose:
        print(f"Loaded {len(calendars)} calendars")
    return calendars


# Check if tasks can be completed on time sequentially
def check_tasks_sequentially(config):
    tasks = get_tasks()
    time_maps = config["time_maps"]
    today = datetime.today().date()
    todo = [True if t["status"] not in AVOID_STATUS else False for t in tasks]
    used_hours = [0] * (config["scheduler"]["days_ahead"] + 1)
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
            if args.verbose:
                print(
                    f"Checking task {task['id']} ('{task['description']}') with estimated hours: {estimated_hours} and wait date: {wait_date}"
                )

            task_remaining_hours = estimated_hours
            task_time_map, today_used_hours = get_long_range_time_map(
                time_maps, time_map_names, config["scheduler"]["days_ahead"], calendars
            )
            used_hours[0] += today_used_hours

            # Simulate work day-by-day until task is complete or past due
            is_starting = True
            scheduling_note = ""
            start_date = end_date = None
            for offset in range(len(task_time_map)):
                if task_time_map[offset] > used_hours[offset]:
                    (
                        start_date,
                        end_date,
                        task_remaining_hours,
                        is_starting,
                        scheduling_note,
                    ) = schedule_task_on_day(
                        is_starting,
                        offset,
                        start_date,
                        end_date,
                        task_remaining_hours,
                        task_time_map,
                        today,
                        used_hours,
                        wait_date,
                        scheduling_note,
                    )

                if end_date is not None:
                    todo[i] = False
                    mark_end_date(
                        due_date,
                        end_date,
                        start_date,
                        scheduling_note,
                        task["id"],
                        task["description"],
                    )
                    break


def get_urgency_coefficients():
    """
    Retrieves urgency coefficients from Taskwarrior configurations.
    Returns a dictionary mapping 'estimated.<value>.coefficient' to its float value.
    """
    result = subprocess.run(["task", "_show"], capture_output=True, text=True)
    coefficients = {}
    pattern = re.compile(r"^urgency\.uda\.estimated\.(.+)\.coefficient=(.+)$")
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match:
            estimated_value = match.group(1)
            coefficient = float(match.group(2))
            coefficients[estimated_value] = coefficient
    return coefficients


def compute_estimated_urgency(remaining_hours, coefficients):
    """
    Computes the estimated urgency for the given remaining hours using the coefficients.
    """
    # Convert remaining hours to PDTH format used in the coefficients
    pdth_value = hours_to_PDTH(remaining_hours)
    # Find the closest match (e.g., if '2h' is not available, use '1h' or '3h')
    closest_match = min(
        coefficients.keys(),
        key=lambda x: abs(int(pdth_value[1]) - int(PDTH_to_hours(x[1]))),
    )
    coefficient = coefficients[closest_match]
    # Compute the urgency
    estimated_urgency = coefficient * remaining_hours
    return estimated_urgency


def check_tasks_parallel(config, max_block):
    """
    Takes the most urgent task and allocates max_block hours (or less), then recomputes the most
    urgent task given that the estimated time of the allocated task is decreased, and so the
    urgency. The new urgency for that task's estimated value is computed by using the "estimated" urgency factor from
    the command line: `task _show`, which should be grepped for line starting with
    `urgency.uda.estimated.{hours_to_PDTH(task_remaining_hours)}.coefficient=`.
    """
    tasks = get_tasks()
    time_maps = config["time_maps"]
    today = datetime.today().date()
    days_ahead = config["scheduler"]["days_ahead"]
    calendars = get_calendars(config)

    # Fetch urgency coefficients from Taskwarrior
    urgency_coefficients = get_urgency_coefficients()

    # Initialize task info: remaining estimated hours, initial urgency
    task_info = {}
    for task in tasks:
        if task.get("status") in AVOID_STATUS:
            continue
        if "estimated" not in task or "time_map" not in task:
            continue
        estimated_hours = PDTH_to_hours(task["estimated"])
        time_map_names = task["time_map"].split(",")
        task_time_map, today_used_hours = get_long_range_time_map(
            time_maps, time_map_names, days_ahead, calendars
        )
        task_uuid = task["uuid"]
        initial_urgency = float(task.get("urgency", 0))
        task_info[task_uuid] = {
            "task": task,
            "remaining_hours": estimated_hours,
            "task_time_map": task_time_map,
            "today_used_hours": today_used_hours,
            "scheduling": {},
            "urgency": initial_urgency,
            "estimated_urgency": compute_estimated_urgency(
                estimated_hours, urgency_coefficients
            ),
        }

    # For each day, allocate time to tasks
    for day_offset in range(days_ahead):
        date = today + timedelta(days=day_offset)
        # Calculate the day's total available hours by finding the maximum available hours among all tasks
        if day_offset == 0:
            total_hours_list = [
                info["task_time_map"][day_offset] - info["today_used_hours"]
                for info in task_info.values()
            ]
        else:
            total_hours_list = [
                info["task_time_map"][day_offset] for info in task_info.values()
            ]
        total_available_hours = max(total_hours_list) if total_hours_list else 0

        if args.verbose:
            print(f"Day {date}, total available hours: {total_available_hours:.2f}")
        if total_available_hours <= 0:
            continue

        # Keep track of day's remaining available hours
        day_remaining_hours = total_available_hours

        # Prepare a list of tasks that can be scheduled on this day
        tasks_remaining = [
            info
            for info in task_info.values()
            if info["remaining_hours"] > 0 and info["task_time_map"][day_offset] > 0
        ]

        while day_remaining_hours > 0 and tasks_remaining:
            # Recompute urgencies based on remaining estimated hours
            for info in tasks_remaining:
                remaining_hours = info["remaining_hours"]
                estimated_urgency = compute_estimated_urgency(
                    remaining_hours, urgency_coefficients
                )
                # urgency is estimated_urgency + k, so we adjust it accordingly to the component
                # tied to the estimated time
                _old_estimated_urgeny = info["estimated_urgency"]
                info["estimated_urgency"] = estimated_urgency
                info["urgency"] = (
                    info["urgency"] - _old_estimated_urgeny + estimated_urgency
                )

            # Sort tasks by urgency in descending order
            tasks_remaining.sort(key=lambda x: -x["urgency"])

            allocated = False
            for info in tasks_remaining:
                task = info["task"]
                task_remaining_hours = info["remaining_hours"]
                task_daily_available = info["task_time_map"][day_offset]
                if task_daily_available <= 0:
                    continue  # Task not available on this day

                # Determine allocation amount
                allocation = min(
                    max_block,
                    task_remaining_hours,
                    task_daily_available,
                    day_remaining_hours,
                )

                if allocation <= 0:
                    continue

                # Allocate time
                info["remaining_hours"] -= allocation
                day_remaining_hours -= allocation
                info["task_time_map"][day_offset] -= allocation

                # Record allocation per day
                date_str = date.isoformat()
                if date_str not in info["scheduling"]:
                    info["scheduling"][date_str] = 0
                info["scheduling"][date_str] += allocation

                allocated = True
                if args.verbose:
                    print(
                        f"Allocated {allocation:.2f} hours to task {task['id']} on {date}"
                    )

                # Update tasks_remaining for next iteration
                # Remove task if fully allocated or no more available time today
                if (
                    info["remaining_hours"] <= 0
                    or info["task_time_map"][day_offset] <= 0
                ):
                    tasks_remaining = [
                        i
                        for i in tasks_remaining
                        if i["task"]["uuid"] != info["task"]["uuid"]
                    ]
                if day_remaining_hours <= 0:
                    break  # No more time in day

            if not allocated:
                # No tasks could be allocated time
                break  # Exit loop

        if args.verbose and day_remaining_hours > 0:
            print(f"Unused time on {date}: {day_remaining_hours:.2f} hours")

    # After scheduling, update tasks with scheduling info
    for info in task_info.values():
        task = info["task"]
        scheduling_note = ""
        scheduled_dates = sorted(info["scheduling"].keys())
        if not scheduled_dates:
            continue  # Task was not scheduled
        start_date = scheduled_dates[0]
        end_date = scheduled_dates[-1]
        for date_str in scheduled_dates:
            hours = info["scheduling"][date_str]
            scheduling_note += f"{date_str}: {hours:.2f} hours\n"

        # Update task in Taskwarrior
        subprocess.run(
            [
                "task",
                str(task["id"]),
                "modify",
                f"scheduled:{start_date}",
                f"completion_date:{end_date}",
                f'scheduling:"{scheduling_note.strip()}"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if args.verbose:
            print(
                f"Updated task {task['id']} with scheduled dates {start_date} to {end_date}"
            )


def main():
    # Load data and check tasks
    config = load_config()
    algo = config["scheduler"].get("algorithm", "parallel")
    if algo == "parallel":
        block = config["scheduler"].get("block", 2)
        check_tasks_parallel(config, block)
    elif algo == "sequential":
        check_tasks_sequentially(config)
    else:
        raise ValueError(f"Unknown algorithm: {algo}")


if __name__ == "__main__":
    main()
