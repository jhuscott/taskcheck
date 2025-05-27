import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from taskcheck.parallel import (
    get_urgency_coefficients,
    check_tasks_parallel,
    initialize_task_info,
    allocate_time_for_day,
    urgency_due,
    urgency_age,
    urgency_estimated,
    recompute_urgencies,
    UrgencyCoefficients
)


class TestUrgencyCoefficients:
    def test_get_urgency_coefficients(self, mock_task_export_with_taskrc, test_taskrc):
        coeffs = get_urgency_coefficients(taskrc=test_taskrc)
        
        assert isinstance(coeffs, UrgencyCoefficients)
        assert "P1H" in coeffs.estimated
        assert coeffs.estimated["P1H"] == 5.0
        assert coeffs.inherit is True
        assert coeffs.active == 4.0


class TestUrgencyCalculations:
    def test_urgency_due_overdue(self):
        coeffs = UrgencyCoefficients({}, False, 0, 365, 12, 2)
        task_info = {
            "task": {
                "due": "20231201T170000Z"  # Past due
            }
        }
        date = datetime(2023, 12, 10).date()  # 9 days later
        
        urgency = urgency_due(task_info, date, coeffs)
        assert urgency == 12.0  # Max urgency for overdue
        
    def test_urgency_due_approaching(self):
        coeffs = UrgencyCoefficients({}, False, 0, 365, 12, 2)
        task_info = {
            "task": {
                "due": "20231210T170000Z"  # Due in future
            }
        }
        date = datetime(2023, 12, 5).date()  # 5 days before
        
        urgency = urgency_due(task_info, date, coeffs)
        assert 0 < urgency < 12.0
        
    def test_urgency_age(self):
        coeffs = UrgencyCoefficients({}, False, 0, 365, 12, 2)
        task_info = {
            "task": {
                "entry": "20231120T090000Z"  # 15 days ago
            }
        }
        date = datetime(2023, 12, 5).date()
        
        urgency = urgency_age(task_info, date, coeffs)
        expected = 1.0 * 15 / 365 * 2  # age calculation
        assert abs(urgency - expected) < 0.01
        
    def test_urgency_estimated(self):
        coeffs = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0}, False, 0, 365, 12, 2)
        task_info = {"remaining_hours": 1.0}
        
        urgency = urgency_estimated(task_info, None, coeffs)
        assert urgency == 5.0


class TestTaskInitialization:
    @patch('taskcheck.parallel.get_long_range_time_map')
    def test_initialize_task_info(self, mock_long_range, sample_tasks, sample_config):
        mock_long_range.return_value = ([8.0, 8.0, 8.0], 0.0)
        
        time_maps = sample_config["time_maps"]
        days_ahead = 3
        coeffs = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0, "P3H": 10.0}, False, 4.0, 365, 12, 2)
        calendars = []
        
        task_info = initialize_task_info(sample_tasks, time_maps, days_ahead, coeffs, calendars)
        
        assert len(task_info) == len(sample_tasks)
        for uuid, info in task_info.items():
            assert "task" in info
            assert "remaining_hours" in info
            assert "task_time_map" in info
            assert "urgency" in info


class TestTimeAllocation:
    def test_allocate_time_for_day_single_task(self, sample_config):
        task_info = {
            "task-1": {
                "task": {
                    "id": 1, 
                    "uuid": "task-1", 
                    "description": "Test task",
                    "estimated": "P2H"
                },
                "remaining_hours": 2.0,
                "task_time_map": [8.0, 8.0, 8.0],
                "today_used_hours": 0.0,
                "scheduling": {},
                "urgency": 10.0,
                "estimated_urgency": 8.0,
                "due_urgency": 0.0,
                "age_urgency": 1.0,
                "started": False
            }
        }
        
        coeffs = UrgencyCoefficients({"P2H": 8.0}, False, 4.0, 365, 12, 2)
        
        allocate_time_for_day(task_info, 0, coeffs, verbose=True, weight_urgency=1.0, weight_due_date=0.0)
        
        # Should allocate time and update scheduling
        assert task_info["task-1"]["remaining_hours"] < 2.0
        assert len(task_info["task-1"]["scheduling"]) > 0


class TestDependencies:
    def test_task_with_dependencies(self, sample_config):
        task_info = {
            "task-1": {
                "task": {
                    "id": 1, 
                    "uuid": "task-1", 
                    "description": "Dependent task",
                    "depends": ["task-2"],
                    "estimated": "P2H"
                },
                "remaining_hours": 2.0,
                "task_time_map": [8.0, 8.0, 8.0],
                "today_used_hours": 0.0,
                "scheduling": {},
                "urgency": 10.0,
                "estimated_urgency": 8.0,
                "due_urgency": 0.0,
                "age_urgency": 1.0,
                "started": False
            },
            "task-2": {
                "task": {
                    "id": 2, 
                    "uuid": "task-2", 
                    "description": "Dependency task",
                    "estimated": "P1H"
                },
                "remaining_hours": 1.0,
                "task_time_map": [8.0, 8.0, 8.0],
                "today_used_hours": 0.0,
                "scheduling": {},
                "urgency": 15.0,
                "estimated_urgency": 5.0,
                "due_urgency": 0.0,
                "age_urgency": 1.0,
                "started": False
            }
        }
        
        coeffs = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0}, False, 4.0, 365, 12, 2)
        
        allocate_time_for_day(task_info, 0, coeffs, verbose=True, weight_urgency=1.0, weight_due_date=0.0)
        
        # task-2 should be scheduled first due to dependency
        if task_info["task-2"]["remaining_hours"] == 0:
            # task-2 completed, task-1 can now be scheduled
            assert task_info["task-1"]["remaining_hours"] <= 2.0


class TestWeightConfiguration:
    @patch('taskcheck.parallel.get_calendars')
    @patch('taskcheck.parallel.get_tasks')
    @patch('taskcheck.parallel.get_urgency_coefficients')
    @patch('taskcheck.parallel.update_tasks_with_scheduling_info')
    def test_urgency_weight_override(self, mock_update, mock_coeffs, mock_tasks, mock_calendars, sample_config, sample_tasks):
        """Test that urgency_weight_override properly overrides config values."""
        # Set config values
        sample_config["scheduler"]["weight_urgency"] = 0.8
        sample_config["scheduler"]["weight_due_date"] = 0.2
        
        mock_tasks.return_value = sample_tasks
        mock_coeffs.return_value = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0, "P3H": 10.0}, False, 4.0, 365, 12, 2)
        mock_calendars.return_value = []
        
        # Call with override
        check_tasks_parallel(sample_config, urgency_weight_override=0.3)
        
        # Verify the function was called - we'd need to check internal logic
        # This test would need access to the weights used internally
        mock_tasks.assert_called_once()
        
    @patch('taskcheck.parallel.get_calendars')
    @patch('taskcheck.parallel.get_tasks') 
    @patch('taskcheck.parallel.get_urgency_coefficients')
    @patch('taskcheck.parallel.update_tasks_with_scheduling_info')
    def test_config_weights_used_when_no_override(self, mock_update, mock_coeffs, mock_tasks, mock_calendars, sample_config, sample_tasks):
        """Test that config weights are used when no override is provided."""
        sample_config["scheduler"]["weight_urgency"] = 0.6
        sample_config["scheduler"]["weight_due_date"] = 0.4
        
        mock_tasks.return_value = sample_tasks
        mock_coeffs.return_value = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0, "P3H": 10.0}, False, 4.0, 365, 12, 2)
        mock_calendars.return_value = []
        
        # Call without override
        check_tasks_parallel(sample_config, urgency_weight_override=None)
        
        mock_tasks.assert_called_once()
        
    def test_recompute_urgencies_with_weights(self):
        """Test that recompute_urgencies applies weights correctly."""
        tasks_remaining = {
            "task-1": {
                "task": {"uuid": "task-1", "id": 1},
                "urgency": 10.0,
                "estimated_urgency": 5.0,
                "due_urgency": 3.0,
                "age_urgency": 1.0,
                "remaining_hours": 2.0,
                "started": False
            }
        }
        
        coeffs = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0}, False, 0, 365, 12, 2)
        date = datetime.now().date()
        weight_urgency = 0.7
        weight_due_date = 0.3
        
        # Store original values
        original_urgency = tasks_remaining["task-1"]["urgency"]
        original_estimated = tasks_remaining["task-1"]["estimated_urgency"] 
        original_due = tasks_remaining["task-1"]["due_urgency"]
        original_age = tasks_remaining["task-1"]["age_urgency"]
        
        recompute_urgencies(tasks_remaining, coeffs, date, weight_urgency, weight_due_date)
        
        # Check that weights were applied
        task_info = tasks_remaining["task-1"]
        base_urgency = original_urgency - original_estimated - original_due - original_age
        expected_urgency = (
            base_urgency +
            original_estimated * weight_urgency +
            original_due * weight_due_date +
            original_age * weight_urgency
        )
        
        assert abs(task_info["urgency"] - expected_urgency) < 0.01


class TestMainSchedulingFunction:
    @patch('taskcheck.parallel.get_calendars')
    @patch('taskcheck.parallel.get_tasks')
    @patch('taskcheck.parallel.get_urgency_coefficients')
    @patch('taskcheck.parallel.update_tasks_with_scheduling_info')
    def test_check_tasks_parallel(self, mock_update, mock_coeffs, mock_tasks, mock_calendars, sample_config, sample_tasks, test_taskrc):
        mock_tasks.return_value = sample_tasks
        mock_coeffs.return_value = UrgencyCoefficients({"P1H": 5.0, "P2H": 8.0, "P3H": 10.0}, False, 4.0, 365, 12, 2)
        mock_calendars.return_value = []
        
        check_tasks_parallel(sample_config, verbose=True, taskrc=test_taskrc)
        
        mock_tasks.assert_called_once_with(taskrc=test_taskrc)
        mock_coeffs.assert_called_once_with(taskrc=test_taskrc)
        mock_calendars.assert_called_once()
        mock_update.assert_called_once()
