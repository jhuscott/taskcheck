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
            "min_block": task["min_block"],
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

        if verbose:
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
                    task_remaining_hours,
                    task_daily_available,
                    day_remaining_hours,
                )

                if allocation <= 0:
                    continue
                elif allocation > info["min_block"]:
                    allocation = info["min_block"]

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
                if verbose:
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

        if verbose and day_remaining_hours > 0:
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
        if verbose:
            print(
                f"Updated task {task['id']} with scheduled dates {start_date} to {end_date}"
            )
