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


def get_tasks(tasks, year, month, day):
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
                        "urgency": task["urgency"],
                        "due": due,
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


def generate_report(config, constraint, verbose=False):
    console = Console()
    tasks = subprocess.run(
        ["task", "scheduling~.", "export"], capture_output=True, text=True
    )
    tasks = json.loads(tasks.stdout)

    for year, month, day in get_days_in_constraint(constraint):
        this_day_tasks = get_tasks(tasks, year, month, day)

        # Create a colorful date header with emojis and a panel
        date_str = f":calendar: [bold cyan]{year}-{month}-{day}[/bold cyan]"
        console.print(Panel(date_str, style="bold magenta", expand=False))

        if this_day_tasks:
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Task", style="dim", width=12)
            table.add_column("Project", style="dim", width=12)
            table.add_column("Description")
            table.add_column("Time", justify="right")
            table.add_column("Urgency")
            table.add_column("Due date")

            for task in this_day_tasks:
                task_id = f"[bold green]#{task['id']}[/bold green]"
                project = task["project"]
                description = Text(task["description"], style="white")
                hours = f"[yellow]{task['scheduling_hours']}h[/yellow]"
                urgency = f"[bold]{task['urgency']}[/bold]"
                due = task["due"]
                if due != "" and due < timedelta(days=5):
                    due = f"[red]{due.days}d[/red]"
                elif due != "":
                    due = f"[green]{due.days}d[/green]"

                # Add an emoji based on a keyword in the description
                if "meeting" in task["description"].lower():
                    emoji = ":busts_in_silhouette:"
                elif "review" in task["description"].lower():
                    emoji = ":mag_right:"
                elif "write" in task["description"].lower():
                    emoji = ":pencil:"
                else:
                    emoji = ":pushpin:"

                table.add_row(
                    f"{emoji} {task_id}", project, description, hours, urgency, due
                )

            console.print(table)
        else:
            console.print("[italic dim]No tasks scheduled for this day.[/italic dim]")
