import subprocess
import re

from datetime import datetime, timedelta
from taskcheck.common import (
    AVOID_STATUS,
    get_calendars,
    get_long_range_time_map,
    get_tasks,
    hours_to_PDTH,
    PDTH_to_hours,
)


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


def check_tasks_parallel(config, verbose=False):
    tasks = get_tasks()
    time_maps = config["time_maps"]
    days_ahead = config["scheduler"]["days_ahead"]
    calendars = get_calendars(config)
    today = datetime.today().date()
    urgency_coefficients = get_urgency_coefficients()

    task_info = initialize_task_info(
        tasks, time_maps, days_ahead, urgency_coefficients, calendars
    )

    for day_offset in range(days_ahead):
        date = today + timedelta(days=day_offset)
        allocate_time_for_day(
            task_info, day_offset, date, urgency_coefficients, verbose
        )

    update_tasks_with_scheduling_info(task_info, verbose)


def initialize_task_info(tasks, time_maps, days_ahead, urgency_coefficients, calendars):
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
        estimated_urgency = compute_estimated_urgency(
            estimated_hours, urgency_coefficients
        )
        task_info[task_uuid] = {
            "task": task,
            "remaining_hours": estimated_hours,
            "task_time_map": task_time_map,
            "today_used_hours": today_used_hours,
            "scheduling": {},
            "urgency": initial_urgency,
            "estimated_urgency": estimated_urgency,
            "min_block": task["min_block"],
        }
    return task_info


def allocate_time_for_day(task_info, day_offset, date, urgency_coefficients, verbose):
    total_available_hours = compute_total_available_hours(task_info, day_offset)
    if verbose:
        print(f"Day {date}, total available hours: {total_available_hours:.2f}")
    if total_available_hours <= 0:
        return

    day_remaining_hours = total_available_hours
    tasks_remaining = prepare_tasks_remaining(task_info, day_offset)

    while day_remaining_hours > 0 and tasks_remaining:
        recompute_urgencies(tasks_remaining, urgency_coefficients)
        tasks_remaining.sort(key=lambda x: -x["urgency"])

        allocated = False
        for info in tasks_remaining.copy():
            allocation = allocate_time_to_task(info, day_offset, day_remaining_hours)
            if allocation > 0:
                day_remaining_hours -= allocation
                allocated = True
                date_str = date.isoformat()
                update_task_scheduling(info, allocation, date_str)
                if verbose:
                    print(
                        f"Allocated {allocation:.2f} hours to task {info['task']['id']} on {date}"
                    )
                if (
                    info["remaining_hours"] <= 0
                    or info["task_time_map"][day_offset] <= 0
                ):
                    tasks_remaining.remove(info)
                # if day_remaining_hours <= 0:
                break
        if not allocated:
            break
    if verbose and day_remaining_hours > 0:
        print(f"Unused time on {date}: {day_remaining_hours:.2f} hours")


def compute_total_available_hours(task_info, day_offset):
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
    return total_available_hours


def prepare_tasks_remaining(task_info, day_offset):
    return [
        info
        for info in task_info.values()
        if info["remaining_hours"] > 0 and info["task_time_map"][day_offset] > 0
    ]


def recompute_urgencies(tasks_remaining, urgency_coefficients):
    for info in tasks_remaining:
        remaining_hours = info["remaining_hours"]
        estimated_urgency = compute_estimated_urgency(
            remaining_hours, urgency_coefficients
        )
        _old_estimated_urgency = info["estimated_urgency"]
        info["estimated_urgency"] = estimated_urgency
        info["urgency"] = info["urgency"] - _old_estimated_urgency + estimated_urgency


def allocate_time_to_task(info, day_offset, day_remaining_hours):
    task_daily_available = info["task_time_map"][day_offset]
    if task_daily_available <= 0:
        return 0

    allocation = min(
        info["remaining_hours"],
        task_daily_available,
        day_remaining_hours,
        info["min_block"],
    )

    if allocation <= 0:
        return 0

    info["remaining_hours"] -= allocation
    info["task_time_map"][day_offset] -= allocation

    return allocation


def update_task_scheduling(info, allocation, date_str):
    if date_str not in info["scheduling"]:
        info["scheduling"][date_str] = 0
    info["scheduling"][date_str] += allocation


def update_tasks_with_scheduling_info(task_info, verbose):
    for info in task_info.values():
        task = info["task"]
        scheduling_note = ""
        scheduled_dates = sorted(info["scheduling"].keys())
        if not scheduled_dates:
            continue
        start_date = scheduled_dates[0]
        end_date = scheduled_dates[-1]
        for date_str in scheduled_dates:
            hours = info["scheduling"][date_str]
            scheduling_note += f"{date_str}: {hours:.2f} hours\n"

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
        if verbose:
            print(
                f"Updated task {task['id']} with scheduled dates {start_date} to {end_date}"
            )
