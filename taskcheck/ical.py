from icalendar import Calendar
from datetime import datetime, timedelta
from dateutil.rrule import rruleset, rrulestr
from requests_cache import CachedSession

import time


def fetch_ical_data(url, expiration, verbose):
    session = CachedSession(
        "taskcheck",
        use_cache_dir=True,  # Save files in the default user cache dir
        cache_control=True,  # Use Cache-Control response headers for expiration, if available
        urls_expire_after={url: expiration},  # Set expiration time
        allowable_codes=[
            200,
        ],
        allowable_methods=["GET", "POST"],  # Cache whatever HTTP methods you want
        stale_if_error=True,  # In case of request errors, use stale cache data if possible
    )
    ttt = time.time()
    response = session.get(url)
    if verbose:
        print("Time taken to fetch ical data: ", time.time() - ttt)
    response.raise_for_status()
    return response.text


def parse_ical_events(ical_text, days_ahead, all_day):
    cal = Calendar.from_ical(ical_text)
    today = datetime.now().date()
    end_date = today + timedelta(days=days_ahead)

    events = []

    for component in cal.walk():
        if component.name == "VEVENT":
            event_start = component.get("dtstart").dt
            event_end = component.get("dtend").dt
            recurrence_rule = component.get("rrule")
            recurrence_id = component.get("recurrence-id")

            # skip all-day events if not requested
            is_all_day = not hasattr(event_start, "hour") or event_start == event_end
            if is_all_day:
                if not all_day:
                    continue
                else:
                    # all-day events should block since 00:00 and end at 23:59:59
                    event_start = datetime(
                        event_start.year,
                        event_start.month,
                        event_start.day,
                        0,
                        0,
                        0,
                        0,
                    )
                    event_end = event_start + timedelta(days=1) - timedelta(seconds=1)
            if recurrence_id:
                continue  # Ignore recurrence exceptions here for simplicity

            event_dates = rruleset()
            if recurrence_rule:
                rrule = rrulestr(
                    str(recurrence_rule.to_ical(), "utf-8"), dtstart=event_start
                )
                event_dates.rrule(rrule)  # type: ignore
            else:
                event_dates.rdate(event_start)

            for event_date in event_dates:
                if today <= event_date.date() <= end_date:
                    events.append(
                        {
                            "summary": component.get("summary"),
                            "start": event_date,
                            "end": event_end,
                        }
                    )

    return events


def ical_to_dict(url, days_ahead=7, all_day=False, expiration=0.25, verbose=False):
    ical_text = fetch_ical_data(url, expiration * 3600, verbose)
    events = parse_ical_events(ical_text, days_ahead, all_day)
    return events
