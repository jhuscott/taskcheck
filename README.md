
> _A non-AI automatic scheduler for taskwarrior (i.e. alternative to skedpal/timehero/flowsavvy/reclaim/trevor/motion)_

This is a taskwarrior extension checks if tasks can be completed on time, considering estimated time and working hours.

<p align="center">
<img src="https://github.com/user-attachments/assets/b9082701-339b-4407-b941-b613a717382c"/>
</p>

## Features

- [x] Use arbitrarily complex time maps
- [x] Use ical to block time from scheduling (e.g. for meetings, vacations, etc.)
- [x] Implement scheduling algorithm for parallely working on multiple tasks
- [ ] Use Google API to access calendars
- [ ] Export tasks to iCal calendar and API calendars

## Install

1. `pipx install taskcheck`
2. `taskcheck --install`

## How does it work

This extension parses your pending and waiting tasks sorted decreasingly by urgency and tries to schedule them in the future.
It considers their estimated time to schedule all tasks starting from the most urgent one.

#### UDAs

Taskcheck leverages two UDAs, `estimated` and `time_map`. The `estimated` attribute is
the expected time to complete the task in hours. The `time_map` is a comma-separated list of strings
that indicates the hours per day in which you will work on a task (e.g. `work`, `weekend`, etc.).
The exact correspondence between the `time_map` and the hours of the day is defined in the configuration
file of taskcheck. For instance:

```toml
[time_maps]
# get an error)
[time_maps.work]
monday = [[9, 12.30], [14, 17]]
tuesday = [[9, 12.30], [14, 17]]
# ...
```

#### They say it's an "AI"

Taskcheck will also parse online iCal calendars (Google, Apple, etc.) and will match them with your time maps.
It will then modify the Taskwarrior tasks by adding the `completion_date` attribute with the expected
date of completion and the `scheduled` attribute with the date in which the task is expected to
start.

It will also print a red line for every task whose `completion_date` is after its `due_date`.

In general, it is recommended to run taskcheck rather frequently and at least once at the beginning
of your working day.

#### Reports

You can also print simple reports that exploit the `scheduling` UDA filled by Taskcheck to grasp
how much time you have to work on which task in which day. For
instance:

- `taskcheck -r today` will show the tasks planned for today
- `taskcheck -r 1w` will show the tasks planned for the next week


## Configuration

`taskcheck --install` allows you to create required and recommended configurations for
   taskwarrior. It will also generate a default configuration file for taskcheck.

Below is an example of taskcheck configuration file:

```toml
[time_maps]
# in which hours you will work in each day (in 24h format, if you use e.g. 25.67 you will likely 
# get an error)
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

[report]
additional_attributes = ["estimated", "due", "urgency"] # additional attributes to show in the report
# when these words are matched in the task description, the corresponding emoji is used
emoji_keywords = {"meet"=":busts_in_silhouette:", "review"=":mag_right:"}
include_unplanned = true # include unplanned tasks in the report in an ad-hoc section
additional_attributes_unplanned = ["due", "urgency"] # additional attributes to show in the report for unplanned tasks
```

## Algorithm

The algorithm simulates what happens if you work on a task for a certain time on a given day.

For each day X starting from today, it sorts the tasks by decreasing urgency. 
It start from the most urgent tasks that can be allocated on day X depending on the task's
`time_map` and on your calendars. It allocates a few number of hours to the task,
then recomputes the urgencies exactly as Taskwarrior would do
if it was running on day X. Having recomputed the urgencies, it restarts.

If after 2 hours a long task has decreased its urgency, it will be noticed and the newer most urgent
task will get scheduled in its place.

For `today`, taskcheck will skip the hours in the past -- i.e. if you're running at 12 pm, it will
skip all the available slots until 12 pm.

The maximum time that is allocated at each attempt is by default 2 hours
(or less if the task is shorter), but you can change it by tuning the Taskwarrior UDA `min_block`.

## Tips and Tricks

- You can exclude a task from being scheduled by removing the `time_map` or `estimated` attributes.
- You can see tasks that you can execute now with the `task ready` report.

## CLI Options

```
-v, --verbose: increase output verbosity
-i, --install: install taskcheck configuration
-r, --report: show tasks planned until a certain time
```
