import sys
from datetime import timedelta
from datetime import datetime
import json
import re
import subprocess


from rich import print
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel


def get_tasks(config, tasks, year, month, day):
    regex = re.compile(rf"{year}-{month}-{day} - ([PDTHM0-9]+)")
    valid_tasks = []
    for task in tasks:
        for line in task["scheduling"].split("\n"):
            m = regex.match(line)
            if m:
                due = task.get("due", "")
                if due:
                    due = datetime.strptime(due, "%Y%m%dT%H%M%SZ")
                    due = due - datetime.today()
                valid_tasks.append(
                    {
                        "id": task["id"],
                        "project": task.get("project", ""),
                        "description": task["description"],
                        "scheduling_day": f"{year}-{month}-{day}",
                        "scheduling_hours": m.group(1),
                        **{
                            attr: task.get(attr, "")
                            for attr in config.get("additional_attributes", [])
                        },
                    }
                )
    valid_tasks = sorted(valid_tasks, key=lambda x: x["urgency"], reverse=True)
    return valid_tasks


def get_taskwarrior_date(date, _retry=True):
    date = subprocess.run(
        ["task", "calc", date],
        capture_output=True,
        text=True,
    )
    date = date.stdout.strip()
    try:
        date = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
    except Exception as _:
        if _retry:
            return get_taskwarrior_date("today+" + date, False)
        else:
            print(
                "Please provide a valid date. Check with `task calc` that your date is in the format YYYY-MM-DDTHH:MM:SS",
                file=sys.stderr,
            )
            exit(2)
    return date


def get_days_in_constraint(constraint):
    current_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    constraint = get_taskwarrior_date(constraint)
    while current_date <= constraint:
        yield current_date.year, current_date.month, current_date.day
        current_date += timedelta(days=1)


def tostring(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    elif isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    elif isinstance(value, str):
        try:
            date = datetime.strptime(value, "%Y%m%dT%H%M%SZ")
            return date.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value
    else:
        return str(value)


def get_unplanned_tasks(config, tasks):
    tasks = subprocess.run(
        ["task", "scheduling:", "status:pending", "export"],
        capture_output=True,
        text=True,
    )
    tasks = json.loads(tasks.stdout)
    return tasks


def generate_report(config, constraint, verbose=False):
    config = config["report"]
    console = Console()
    tasks = fetch_tasks()

    for year, month, day in get_days_in_constraint(constraint):
        this_day_tasks = get_tasks(config, tasks, year, month, day)

        display_date_header(console, year, month, day)

        display_tasks_table(console, config, this_day_tasks)

    if config.get("include_unplanned"):
        unplanned_tasks = get_unplanned_tasks(config, tasks)
        display_unplanned_tasks(console, config, unplanned_tasks)


def fetch_tasks():
    """Fetch tasks from the task manager and return them as a JSON object."""
    tasks = subprocess.run(
        ["task", "scheduling~.", "(", "+PENDING", "or", "+WAITING", ")", "export"],
        capture_output=True,
        text=True,
    )
    return json.loads(tasks.stdout)


def display_date_header(console, year, month, day):
    """Display a date header with a calendar emoji."""
    date_str = f":calendar: [bold cyan]{year}-{month}-{day}[/bold cyan]"
    console.print(Panel(date_str, style="bold blue", expand=False))


def display_tasks_table(console, config, tasks):
    """Display a table of tasks for a specific day."""
    if tasks:
        table = build_tasks_table(config, tasks)
        console.print(table)
    else:
        console.print("[italic dim]No tasks scheduled for this day.[/italic dim]")


def build_tasks_table(config, tasks):
    """Build a Rich table for displaying tasks."""
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Task", style="dim", width=12)
    table.add_column("Project", style="dim", width=12)
    table.add_column("Description")
    table.add_column("Time", justify="right")
    for attr in config.get("additional_attributes", []):
        table.add_column(attr.capitalize(), justify="right")

    for task in tasks:
        task_id = f"[bold green]#{task['id']}[/bold green]"
        project = task.get("project", "")
        description = Text(task["description"], style="white")
        hours = f"[yellow]{task['scheduling_hours']}[/yellow]"
        emoji = get_task_emoji(config, task)

        table.add_row(
            f"{emoji} {task_id}",
            project,
            description,
            hours,
            *[
                tostring(task.get(attr, ""))
                for attr in config.get("additional_attributes", [])
            ],
        )
    return table


def get_task_emoji(config, task):
    """Get an emoji based on keywords in the task description."""
    for keyword in config.get("emoji_keywords", []):
        if keyword in task["description"].lower():
            return config["emoji_keywords"][keyword]
    return ":pushpin:"


def display_unplanned_tasks(console, config, tasks):
    """Display unplanned tasks if any are found."""
    if tasks:
        table = build_unplanned_tasks_table(config, tasks)
        console.print(Panel("Unplanned Tasks", style="bold blue", expand=False))
        console.print(table)
    else:
        console.print(
            Panel(
                "[italic dim]No unplanned tasks found.[/italic dim]",
                style="bold blue",
                expand=False,
            )
        )


def build_unplanned_tasks_table(config, tasks):
    """Build a Rich table for displaying unplanned tasks."""
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Task", style="dim", width=12)
    table.add_column("Project", style="dim", width=12)
    table.add_column("Description")

    for task in tasks:
        task_id = f"[bold green]#{task['id']}[/bold green]"
        project = task.get("project", "")
        description = Text(task["description"], style="white")
        emoji = get_task_emoji(config, task)

        table.add_row(
            f"{emoji} {task_id}",
            project,
            description,
        )
    return table
