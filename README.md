
> _A non-AI automatic scheduler for taskwarrior (i.e. alternative to skedpal/timehero/flowsavvy/reclaim/trevor/motion)_

This is a taskwarrior extension checks if tasks can be completed on time, considering estimated time and working hours.

## Features

- [x] Use arbitrarily complex time maps
- [x] Use ical to block time from scheduling (e.g. for meetings, vacations, etc.)
- [ ] Implement scheduling algorithm for parallely working on multiple tasks
- [ ] Use Google/Microsoft/Apple API to access calendars

## Install

> `pipx install taskcheck`

## How does it work

This extension parses your pending and waiting tasks sorted decreasingly by urgency and tries to schedule them in the future.
It considers their estimated time to schedule all tasks one by one (parallel scheduling may be
supported in future).

You will need to add the `estimated` and `time_map` UDAs to your tasks. The `estimated` attribute is
the expected time to complete the task in hours. The `time_map` is a comma-separated list of values
that indicates the hours per day in which you will work on a task.

It will modify the taskwarrior tasks by adding the `completion_date` attribute with the expected
date of completion and the `scheduled` attribute with the date when the task is expected to
start.

It will print a red line for every task whose `completion_date` is after its `due_date`.

You can exclude a task from being scheduled by removing the `time_map` or `estimated` attributes.

You can see tasks that you can execute now with the `task ready` report.

You can see the schedule for a task in the `scheduling` UDA.

## Configuration

1. Create a TOML file at `~/.config/task/taskcheck.toml` with the following format:

```toml
[time_maps]
# in which hours you will work in each day
[time_maps.work]
monday = [[9, 12.30], [14, 17]]
tuesday = [[9, 12.30], [14, 17]]
wednesday = [[9, 12.30], [14, 17]]
thursday = [[9, 12.30], [14, 17]]
friday = [[9, 12.30], [14, 17]]

[time_maps.weekend]
saturday = [[9, 12.30], ]
sunday = [[9, 12.30], ]

[scheduler]
days_ahead = 1000 # how far go with the schedule (lower values make the computation faster)

[calendars]
# ical calendars can be used to block your time and make the scheduling more precise
[calendars.1]
url = "https://your/url/to/calendar.ics"
expiration = 0.08 # in hours (0.08 hours =~ 5 minutes)
timezone = "Europe/Rome" # if set, force timezone for this calendar; timezone values are TZ identifiers (https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

[calendars.holidays]
url = "https://www.officeholidays.com/ics-clean/italy/milan"
event_all_day_is_blocking = true
expiration = 720 # in hours (720 hours = 30 days)
```

2. Add the taskwarrior config

```
# taskcheck UDAs
uda.time_map.type = string
uda.time_map.label = Time Map
uda.time_map.default = work # suggested
uda.estimated.type = duration
uda.estimated.label = Estimated Time
uda.completion_date.type = date
uda.completion_date.label = Expected Completion Date
uda.scheduling.type = string
uda.scheduling.label = Scheduling

# Adjust urgency for taskcheck
# you will use `wait:` to avoid scheduling tasks too much sooner
urgency.waiting.coefficient = 0.0
# you will use `active:` to prioritize tasks already started even if the estimated amount is decreased
urgency.active.coefficient = 3.0 
urgency.scheduled.coefficient = 0.0 # tasks that are not scheduled may still be urgent

# we need to be able to modify recurrent tasks without prompt
recurrence.confirmation=no

# suggested
urgency.inherit=1 # use dependencies to automatically prioritize tasks
urgency.blocking.coefficient=2

# give urgeny values to the estimated time
# this is log(estimation) + 1, with base so that 36 hours has ~12 urgency
urgency.uda.estimated.PT1H.coefficient = 1
urgency.uda.estimated.PT2H.coefficient = 2.32
urgency.uda.estimated.PT3H.coefficient = 3.67
urgency.uda.estimated.PT4H.coefficient = 4.64
urgency.uda.estimated.PT5H.coefficient = 5.39
urgency.uda.estimated.PT6H.coefficient = 6.02
urgency.uda.estimated.PT7H.coefficient = 6.56
urgency.uda.estimated.PT8H.coefficient = 7.03
urgency.uda.estimated.PT9H.coefficient = 7.45
urgency.uda.estimated.PT10H.coefficient = 7.82
urgency.uda.estimated.PT11H.coefficient = 8.16
urgency.uda.estimated.PT12H.coefficient = 8.47
urgency.uda.estimated.PT13H.coefficient = 8.75
urgency.uda.estimated.PT14H.coefficient = 9.01
urgency.uda.estimated.PT15H.coefficient = 9.25
urgency.uda.estimated.PT16H.coefficient = 9.47
urgency.uda.estimated.PT17H.coefficient = 9.68
urgency.uda.estimated.PT18H.coefficient = 9.87
urgency.uda.estimated.PT19H.coefficient = 10.05
urgency.uda.estimated.PT20H.coefficient = 10.22
urgency.uda.estimated.PT21H.coefficient = 10.38
urgency.uda.estimated.PT22H.coefficient = 10.53
urgency.uda.estimated.PT23H.coefficient = 10.67
urgency.uda.estimated.PT24H.coefficient = 10.80
urgency.uda.estimated.PT25H.coefficient = 10.93
urgency.uda.estimated.PT26H.coefficient = 11.05
urgency.uda.estimated.PT27H.coefficient = 11.16
urgency.uda.estimated.PT28H.coefficient = 11.27
urgency.uda.estimated.PT29H.coefficient = 11.37
urgency.uda.estimated.PT30H.coefficient = 11.47
urgency.uda.estimated.PT31H.coefficient = 11.56
urgency.uda.estimated.PT32H.coefficient = 11.65
urgency.uda.estimated.PT33H.coefficient = 11.73
urgency.uda.estimated.PT34H.coefficient = 11.81
urgency.uda.estimated.PT35H.coefficient = 11.89
urgency.uda.estimated.PT36H.coefficient = 11.96
# maximum duration is 36 hours

```

## CLI Options

```

-v, --verbose: increase output verbosity

```
