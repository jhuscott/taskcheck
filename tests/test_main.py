import pytest
from unittest.mock import patch, Mock, mock_open
import argparse
import sys

from taskcheck.__main__ import main, load_config, arg_parser


class TestArgumentParsing:
    def test_arg_parser_defaults(self):
        """Test default argument values."""
        args = arg_parser.parse_args([])
        
        assert args.verbose is False
        assert args.install is False
        assert args.report is None
        assert args.schedule is False
        assert args.force_update is False
        assert args.taskrc is None

    def test_arg_parser_all_flags(self):
        """Test all command line flags."""
        args = arg_parser.parse_args([
            "-v", "-i", "-r", "today", "-s", "-f", "--taskrc", "/custom/path"
        ])
        
        assert args.verbose is True
        assert args.install is True
        assert args.report == "today"
        assert args.schedule is True
        assert args.force_update is True
        assert args.taskrc == "/custom/path"

    def test_arg_parser_long_form(self):
        """Test long form arguments."""
        args = arg_parser.parse_args([
            "--verbose", "--install", "--report", "eow", 
            "--schedule", "--force-update", "--taskrc", "/test"
        ])
        
        assert args.verbose is True
        assert args.install is True
        assert args.report == "eow"
        assert args.schedule is True
        assert args.force_update is True
        assert args.taskrc == "/test"


class TestConfigLoading:
    @patch('builtins.open', new_callable=mock_open, read_data=b'[scheduler]\ndays_ahead = 7')
    @patch('tomllib.load')
    def test_load_config_success(self, mock_toml_load, mock_file, sample_config):
        """Test successful config loading."""
        mock_toml_load.return_value = sample_config
        
        config = load_config()
        
        assert config == sample_config
        mock_file.assert_called_once()
        mock_toml_load.assert_called_once()

    @patch('builtins.open')
    def test_load_config_file_not_found(self, mock_file):
        """Test config loading when file doesn't exist."""
        mock_file.side_effect = FileNotFoundError("Config file not found")
        
        with pytest.raises(FileNotFoundError):
            load_config()

    @patch('builtins.open', new_callable=mock_open, read_data=b'invalid toml content')
    @patch('tomllib.load')
    def test_load_config_invalid_toml(self, mock_toml_load, mock_file):
        """Test config loading with invalid TOML."""
        mock_toml_load.side_effect = Exception("Invalid TOML")
        
        with pytest.raises(Exception):
            load_config()


class TestMainFunction:
    def test_main_no_args_shows_help(self, capsys):
        """Test that main shows help when no arguments provided."""
        with patch('sys.argv', ['taskcheck']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = False
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                with patch.object(arg_parser, 'print_help') as mock_help:
                    main()
                    mock_help.assert_called_once()

    @patch('taskcheck.install.install')
    def test_main_install_command(self, mock_install):
        """Test install command execution."""
        with patch('sys.argv', ['taskcheck', '--install']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = True
                mock_args.schedule = False
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                main()
                
                mock_install.assert_called_once()

    @patch('taskcheck.__main__.load_config')
    @patch('taskcheck.__main__.check_tasks_parallel')
    def test_main_schedule_command(self, mock_check_tasks, mock_load_config, sample_config, test_taskrc, mock_task_export_with_taskrc):
        """Test schedule command execution."""
        mock_load_config.return_value = sample_config
        
        with patch('sys.argv', ['taskcheck', '--schedule', '--taskrc', test_taskrc]):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = True
                mock_args.report = None
                mock_args.verbose = False
                mock_args.force_update = False
                mock_args.taskrc = test_taskrc
                mock_parse.return_value = mock_args
                
                main()
                
                mock_load_config.assert_called_once()
                mock_check_tasks.assert_called_once_with(
                    sample_config, 
                    verbose=False, 
                    force_update=False, 
                    taskrc=test_taskrc
                )

    @patch('taskcheck.__main__.load_config')
    @patch('taskcheck.report.generate_report')
    def test_main_report_command(self, mock_generate_report, mock_load_config, sample_config, test_taskrc):
        """Test report command execution."""
        mock_load_config.return_value = sample_config
        
        with patch('sys.argv', ['taskcheck', '--report', 'today', '--taskrc', test_taskrc]):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = False
                mock_args.report = "today"
                mock_args.verbose = True
                mock_args.force_update = True
                mock_args.taskrc = test_taskrc
                mock_parse.return_value = mock_args
                
                main()
                
                mock_load_config.assert_called_once()
                mock_generate_report.assert_called_once_with(
                    sample_config, 
                    "today", 
                    True, 
                    force_update=True, 
                    taskrc=test_taskrc
                )

    @patch('taskcheck.__main__.load_config')
    @patch('taskcheck.__main__.check_tasks_parallel')
    @patch('taskcheck.report.generate_report')
    def test_main_schedule_and_report(self, mock_generate_report, mock_check_tasks, mock_load_config, sample_config, test_taskrc, mock_task_export_with_taskrc):
        """Test both schedule and report commands together."""
        mock_load_config.return_value = sample_config
        
        with patch('sys.argv', ['taskcheck', '--schedule', '--report', 'eow', '--taskrc', test_taskrc]):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = True
                mock_args.report = "eow"
                mock_args.verbose = False
                mock_args.force_update = False
                mock_args.taskrc = test_taskrc
                mock_parse.return_value = mock_args
                
                main()
                
                # Config should be loaded twice (once for each command)
                assert mock_load_config.call_count == 2
                mock_check_tasks.assert_called_once()
                mock_generate_report.assert_called_once()

    @patch('taskcheck.__main__.load_config')
    @patch('taskcheck.__main__.check_tasks_parallel')
    def test_main_schedule_with_verbose_and_force_update(self, mock_check_tasks, mock_load_config, sample_config, test_taskrc, mock_task_export_with_taskrc):
        """Test schedule command with verbose and force update flags."""
        mock_load_config.return_value = sample_config
        
        with patch('sys.argv', ['taskcheck', '--schedule', '--verbose', '--force-update', '--taskrc', test_taskrc]):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = True
                mock_args.report = None
                mock_args.verbose = True
                mock_args.force_update = True
                mock_args.taskrc = test_taskrc
                mock_parse.return_value = mock_args
                
                main()
                
                mock_check_tasks.assert_called_once_with(
                    sample_config,
                    verbose=True,
                    force_update=True,
                    taskrc=test_taskrc
                )

    @patch('taskcheck.__main__.load_config')
    def test_main_config_loading_error(self, mock_load_config):
        """Test behavior when config loading fails."""
        mock_load_config.side_effect = FileNotFoundError("Config not found")
        
        with patch('sys.argv', ['taskcheck', '--schedule']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = True
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                with pytest.raises(FileNotFoundError):
                    main()

    def test_main_help_display(self):
        """Test that help is displayed when no valid commands are given."""
        with patch('sys.argv', ['taskcheck']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = False
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                with patch.object(arg_parser, 'print_help') as mock_help:
                    main()
                    mock_help.assert_called_once()

    @patch('taskcheck.install.install')
    def test_main_install_returns_early(self, mock_install):
        """Test that install command returns without processing other commands."""
        with patch('sys.argv', ['taskcheck', '--install', '--schedule']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = True
                mock_args.schedule = True
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                with patch('taskcheck.__main__.load_config') as mock_load:
                    main()
                    
                    mock_install.assert_called_once()
                    # load_config should not be called because install returns early
                    mock_load.assert_not_called()


class TestImportErrorHandling:
    def test_install_import_error(self):
        """Test behavior when install module cannot be imported."""
        with patch('sys.argv', ['taskcheck', '--install']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = True
                mock_args.schedule = False
                mock_args.report = None
                mock_parse.return_value = mock_args
                
                with patch('builtins.__import__', side_effect=ImportError("Install module not found")):
                    with pytest.raises(ImportError):
                        main()

    def test_report_import_error(self):
        """Test behavior when report module cannot be imported."""
        with patch('sys.argv', ['taskcheck', '--report', 'today']):
            with patch('taskcheck.__main__.arg_parser.parse_args') as mock_parse:
                mock_args = Mock()
                mock_args.install = False
                mock_args.schedule = False
                mock_args.report = "today"
                mock_parse.return_value = mock_args
                
                with patch('taskcheck.__main__.load_config', return_value={}):
                    with patch('builtins.__import__', side_effect=ImportError("Report module not found")):
                        with pytest.raises(ImportError):
                            main()
