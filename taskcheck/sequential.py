from datetime import datetime, timedelta
from taskcheck.common import (
    get_calendars,
    get_long_range_time_map,
    get_tasks,
    mark_end_date,
    pdth_to_hours,
    hours_to_pdth,
    AVOID_STATUS,
)


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
    verbose=False,
):
    # we can schedule task on this day
    employable_hours = task_time_map[day_offset] - used_hours[day_offset]
    # avoid using too small values
    employable_hours = 0.01 if 0.01 > employable_hours > 0 else employable_hours
    current_date = today + timedelta(days=day_offset)
    if wait and current_date <= wait:
        if verbose:
            print(f"Skipping date {current_date} because of wait date {wait}")
        return start_date, end_date, task_remaining_hours, is_starting, scheduling_note

    if is_starting:
        if verbose:
            print(f"Starting task on {current_date}")
        is_starting = False
        start_date = current_date

    # minimum value we admit is 0.01 (1 minute)
    if task_remaining_hours <= employable_hours + 0.01:
        # consume all the remaining task's hours
        if scheduling_note != "":
            scheduling_note += "\n"
        scheduling_note += f"{current_date} - {hours_to_pdth(task_remaining_hours)}\n"
        used_hours[day_offset] += task_remaining_hours
        task_remaining_hours = 0
        end_date = current_date
        if verbose:
            print(f"Task can be completed on {current_date}")
            print(f"Used hours on {current_date}: {used_hours[day_offset]}")
    else:
        # consume all the available hours on this task
        if scheduling_note != "":
            scheduling_note += "\n"
        scheduling_note += f"{current_date} - {hours_to_pdth(employable_hours)}\n"
        task_remaining_hours -= employable_hours
        used_hours[day_offset] += employable_hours
        if verbose:
            print(f"Working for {employable_hours} hours on task on {current_date}")
    return start_date, end_date, task_remaining_hours, is_starting, scheduling_note


# Check if tasks can be completed on time sequentially
def check_tasks_sequentially(config, verbose=False):
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
                pdth_to_hours(task["estimated"]) if "estimated" in task else None
            )  # Remove trailing "PT" and "H"
            time_map_names = (
                task.get("time_map").split(",") if "time_map" in task else None
            )
            if estimated_hours is None or time_map_names is None:
                todo[i] = False
                if verbose:
                    print(
                        f"Task {task['id']} ('{task['description']}') has no estimated time or time map: {estimated_hours}, {time_map_names}"
                    )
                continue
            if verbose:
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
