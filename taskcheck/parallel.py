import subprocess
import re
from dataclasses import dataclass

from datetime import datetime, timedelta
from taskcheck.common import (
    AVOID_STATUS,
    console,
    get_calendars,
    get_long_range_time_map,
    get_tasks,
    hours_to_pdth,
    pdth_to_hours,
    hours_to_decimal,
)


@dataclass
class UrgencyCoefficients:
    estimated: dict
    inherit: bool
    active: float


def get_urgency_coefficients():
    """
    Retrieves urgency coefficients from Taskwarrior configurations.
    Returns a dictionary mapping 'estimated.<value>.coefficient' to its float value and a
    boolean indicating if the urgency should be inherited by its dependants (`urgency.inherit`).
    """
    result = subprocess.run(["task", "_show"], capture_output=True, text=True)
    inherit_urgency = False
    active_task_coefficient = 0
    coefficients = {}
    pattern1 = re.compile(r"^urgency\.uda\.estimated\.(.+)\.coefficient=(.+)$")
    pattern2 = re.compile(r"^urgency\.inherit=(.+)$")
    pattern3 = re.compile(r"^urgency\.active.coefficient=(.+)$")
    for line in result.stdout.splitlines():
        match = pattern1.match(line)
        if match:
            estimated_value = match.group(1)
            coefficient = float(match.group(2))
            coefficients[estimated_value] = coefficient

        match = pattern2.match(line)
        if match:
            inherit_urgency = match.group(1) == "1"

        match = pattern3.match(line)
        if match:
            active_coefficient = float(match.group(1))
            active_task_coefficient = active_coefficient

    return UrgencyCoefficients(coefficients, inherit_urgency, active_task_coefficient)


def compute_estimated_urgency(remaining_hours, urgency_coefficients):
    """
    Computes the estimated urgency for the given remaining hours using the coefficients.
    """
    # Find the closest match (e.g., if '2h' is not available, use '1h' or '3h')
    closest_match = min(
        urgency_coefficients.estimated.keys(),
        key=lambda x: abs(pdth_to_hours(x) - remaining_hours),
    )
    coefficient = urgency_coefficients.estimated[closest_match]
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
        estimated_hours = pdth_to_hours(task["estimated"])
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
            "started": False,
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
        sorted_task_ids = sorted(
            tasks_remaining.keys(),
            key=lambda x: (tasks_remaining[x]["urgency"], x),
            reverse=True,
        )

        allocated = False
        for uuid in sorted_task_ids:
            if uuid not in tasks_remaining:
                # already completed
                continue
            info = tasks_remaining[uuid]
            if any(d in tasks_remaining for d in info["task"].get("depends", [])):
                # cannot execute this task until all its dependencies are completed
                continue
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
                    del tasks_remaining[uuid]
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
    return {
        info["task"]["uuid"]: info
        for info in task_info.values()
        if info["remaining_hours"] > 0 and info["task_time_map"][day_offset] > 0
    }


def recompute_urgencies(tasks_remaining, urgency_coefficients):
    # Recompute estimated urgencies as before
    for info in tasks_remaining.values():
        remaining_hours = info["remaining_hours"]
        estimated_urgency = compute_estimated_urgency(
            remaining_hours, urgency_coefficients
        )
        _old_estimated_urgency = info["estimated_urgency"]
        info["estimated_urgency"] = estimated_urgency
        info["urgency"] = info["urgency"] - _old_estimated_urgency + estimated_urgency
        started_by_user = info["task"].get("start", "") != ""
        started_by_scheduler = info["started"]
        if started_by_scheduler and not started_by_user:
            # If the task was started by the scheduler, apply the active task coefficient
            info["urgency"] += urgency_coefficients.active

    if urgency_coefficients.inherit:
        # Define a recursive function to compute the maximum urgency
        def get_max_urgency(info, visited):
            task_uuid = info["task"]["uuid"]
            if task_uuid in visited:
                return visited[task_uuid]  # Return cached value to avoid cycles
            # Start with the current task's urgency
            urgency = info["urgency"]
            visited[task_uuid] = urgency  # Mark as visited
            # Recursively compute urgencies of dependents
            for dep_uuid in info["task"].get("depends", []):
                if dep_uuid in tasks_remaining:
                    dep_info = tasks_remaining[dep_uuid]
                    dep_urgency = get_max_urgency(dep_info, visited)
                    urgency = max(urgency, dep_urgency)
            visited[task_uuid] = urgency  # Update with the maximum urgency found
            return urgency

        # Update urgencies based on dependents
        for info in tasks_remaining.values():
            visited = {}  # Reset visited dictionary for each task
            max_urgency = get_max_urgency(info, visited)
            info["urgency"] = max_urgency  # Update the task's urgency


def allocate_time_to_task(info, day_offset, day_remaining_hours):
    task_daily_available = info["task_time_map"][day_offset]
    if task_daily_available <= 0:
        return 0

    allocation = min(
        info["remaining_hours"],
        task_daily_available,
        day_remaining_hours,
        hours_to_decimal(info["task"].get("min_block", 2)),
    )

    if allocation <= 0.05:
        return 0

    info["remaining_hours"] -= allocation
    info["task_time_map"][day_offset] -= allocation
    info["started"] = True

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
            scheduling_note += f"{date_str} - {hours_to_pdth(hours)}\n"

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
        due = task.get("due")
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
        if due is not None and end_date > datetime.strptime(due, "%Y%m%dT%H%M%SZ"):
            console.print(
                f"[red]Warning: Task {task['id']} ('{task['description']}') is not going to be completed on time.[/red]"
            )

        if verbose:
            print(
                f"Updated task {task['id']} with scheduled dates {start_date} to {end_date}"
            )
