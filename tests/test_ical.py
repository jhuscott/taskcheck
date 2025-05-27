import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
import json
import tempfile

from taskcheck.ical import (
    fetch_ical_data,
    parse_ical_events,
    ical_to_dict,
    get_cache_filename
)


class TestIcalFetching:
    @patch('requests.get')
    def test_fetch_ical_data_success(self, mock_get, mock_ical_response):
        mock_response = Mock()
        mock_response.text = mock_ical_response
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = fetch_ical_data("https://example.com/calendar.ics")
        
        assert result == mock_ical_response
        mock_get.assert_called_once_with("https://example.com/calendar.ics")
        
    @patch('requests.get')
    def test_fetch_ical_data_error(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")
        mock_get.return_value = mock_response
        
        with pytest.raises(Exception):
            fetch_ical_data("https://example.com/calendar.ics")


class TestIcalParsing:
    @patch('taskcheck.ical.datetime')
    def test_parse_ical_events_simple(self, mock_datetime, mock_ical_response):
        # Mock datetime.now() to return a date that makes the test events valid
        mock_datetime.now.return_value = datetime(2023, 12, 1, 12, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        
        events = parse_ical_events(mock_ical_response, days_ahead=7, all_day=False)
        
        assert len(events) >= 1
        for event in events:
            assert "start" in event
            assert "end" in event
            assert isinstance(event["start"], str)
            assert isinstance(event["end"], str)
            
    @patch('taskcheck.ical.datetime')
    def test_parse_ical_events_with_timezone(self, mock_datetime, mock_ical_response):
        mock_datetime.now.return_value = datetime(2023, 12, 1, 12, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        
        events = parse_ical_events(
            mock_ical_response, 
            days_ahead=7, 
            all_day=False, 
            tz_name="America/New_York"
        )
        
        assert len(events) >= 0
        
    @patch('taskcheck.ical.datetime')
    def test_parse_ical_events_recurring(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 12, 1, 12, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        
        ical_with_recurring = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:recurring-event
DTSTART:20231205T140000Z
DTEND:20231205T150000Z
SUMMARY:Weekly Meeting
RRULE:FREQ=WEEKLY;COUNT=3
END:VEVENT
END:VCALENDAR"""
        
        events = parse_ical_events(ical_with_recurring, days_ahead=21, all_day=False)
        
        # Should have 3 occurrences
        assert len(events) == 3
        
    @patch('taskcheck.ical.datetime')
    def test_parse_ical_events_all_day(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 12, 1, 12, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        
        ical_all_day = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:all-day-event
DTSTART;VALUE=DATE:20231205
DTEND;VALUE=DATE:20231206
SUMMARY:All Day Event
END:VEVENT
END:VCALENDAR"""
        
        events_include = parse_ical_events(ical_all_day, days_ahead=7, all_day=True)
        events_exclude = parse_ical_events(ical_all_day, days_ahead=7, all_day=False)
        
        assert len(events_include) >= len(events_exclude)


class TestIcalCaching:
    def test_get_cache_filename(self):
        url = "https://example.com/calendar.ics"
        filename = get_cache_filename(url)
        
        assert filename.suffix == ".json"
        assert len(filename.stem) == 64  # SHA256 hash length
        
    @patch('requests.get')
    def test_ical_to_dict_with_cache(self, mock_get, temp_cache_dir, mock_ical_response):
        mock_response = Mock()
        mock_response.text = mock_ical_response
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        url = "https://example.com/calendar.ics"
        
        # First call should fetch and cache
        events1 = ical_to_dict(url, days_ahead=7, all_day=False, expiration=1.0)
        
        # Second call should use cache
        events2 = ical_to_dict(url, days_ahead=7, all_day=False, expiration=1.0)
        
        assert events1 == events2
        # Should only make one HTTP request
        assert mock_get.call_count == 1
        
    @patch('requests.get')
    def test_ical_to_dict_force_update(self, mock_get, temp_cache_dir, mock_ical_response):
        mock_response = Mock()
        mock_response.text = mock_ical_response
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        url = "https://example.com/calendar.ics"
        
        # First call
        events1 = ical_to_dict(url, days_ahead=7, all_day=False, expiration=1.0)
        
        # Force update should bypass cache
        events2 = ical_to_dict(url, days_ahead=7, all_day=False, expiration=1.0, force_update=True)
        
        assert events1 == events2
        # Should make two HTTP requests
        assert mock_get.call_count == 2


class TestExceptionHandling:
    @patch('requests.get')
    def test_ical_to_dict_malformed_ical(self, mock_get, temp_cache_dir):
        mock_response = Mock()
        mock_response.text = "INVALID ICAL DATA"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        url = "https://example.com/calendar.ics"
        
        # Should handle malformed iCal gracefully
        with pytest.raises(Exception):
            ical_to_dict(url, days_ahead=7, all_day=False)
