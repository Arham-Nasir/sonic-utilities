import unittest
from unittest.mock import patch, MagicMock
import socket
import os
import click
from click.testing import CliRunner
import syslog
import pytest
from unittest.mock import Mock

from show.memory_statistics import (
    Config,
    Dict2Obj,
    SonicDBConnector,
    SocketManager,
    display_config,
    display_statistics,
    main,
    show,
    format_field_value,
    clean_and_print,
    validate_command,
)


class TestDict2Obj(unittest.TestCase):
    """Test cases for Dict2Obj class"""
    def test_dict_conversion(self):
        """Test dictionary to object conversion"""
        test_dict = {
            "name": "test",
            "values": [1, 2, 3],
            "nested": {"key": "value"}
        }
        obj = Dict2Obj(test_dict)
        self.assertEqual(obj.name, "test")
        self.assertEqual(obj.values, [1, 2, 3])
        self.assertEqual(obj.nested.key, "value")

    def test_list_conversion(self):
        """Test list conversion"""
        test_list = [{"a": 1}, {"b": 2}]
        obj = Dict2Obj(test_list)
        self.assertEqual(obj.items[0].a, 1)
        self.assertEqual(obj.items[1].b, 2)

    def test_invalid_input(self):
        """Test invalid input handling"""
        with self.assertRaises(ValueError):
            Dict2Obj("invalid")

    def test_to_dict_conversion(self):
        """Test converting object back to dictionary"""
        test_dict = {
            "name": "test",
            "nested": {"key": "value"},
            "list": [{"item": 1}, {"item": 2}]
        }
        obj = Dict2Obj(test_dict)
        result = obj.to_dict()
        self.assertEqual(result, test_dict)

    def test_repr_method(self):
        """Test string representation of Dict2Obj"""
        test_dict = {"name": "test"}
        obj = Dict2Obj(test_dict)
        expected_repr = "<Dict2Obj {'name': 'test'}>"
        self.assertEqual(repr(obj), expected_repr)


class TestSonicDBConnector(unittest.TestCase):
    def setUp(self):
        self.mock_config_db = MagicMock()
        self.patcher = patch('show.memory_statistics.ConfigDBConnector',
                             return_value=self.mock_config_db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    @patch('show.memory_statistics.ConfigDBConnector')
    def test_get_memory_statistics_config(self, mock_config_db):
        """Test retrieving memory statistics configuration"""
        test_config = {
            'memory_statistics': {
                'enabled': 'true',
                'retention_period': '7',
                'sampling_interval': '1'
            }
        }
        mock_config_db.return_value.get_table.return_value = test_config
        connector = SonicDBConnector()
        config = connector.get_memory_statistics_config()
        self.assertEqual(config, test_config['memory_statistics'])

    @patch('show.memory_statistics.ConfigDBConnector')
    def test_get_default_config(self, mock_config_db):
        """Test retrieving default configuration when none exists"""
        mock_config_db.return_value.get_table.return_value = {}
        connector = SonicDBConnector()
        config = connector.get_memory_statistics_config()
        self.assertEqual(config, Config.DEFAULT_CONFIG)

    def test_successful_connection(self):
        """Test successful database connection on first attempt"""
        SonicDBConnector()
        self.mock_config_db.connect.assert_called_once()

    def test_connection_retry_success(self):
        """Test successful connection after initial failures"""
        self.mock_config_db.connect.side_effect = [Exception("First try"), Exception("Second try"), None]
        SonicDBConnector()
        self.assertEqual(self.mock_config_db.connect.call_count, 3)

    def test_get_memory_statistics_config_success(self):
        """Test successful retrieval of memory statistics configuration"""
        test_config = {
            'memory_statistics': {
                'enabled': 'true',
                'retention_period': '7',
                'sampling_interval': '1'
            }
        }
        connector = SonicDBConnector()
        self.mock_config_db.get_table.return_value = test_config
        config = connector.get_memory_statistics_config()
        self.assertEqual(config, test_config['memory_statistics'])

    def test_get_memory_statistics_config_empty(self):
        """Test handling of empty configuration"""
        connector = SonicDBConnector()
        self.mock_config_db.get_table.return_value = {}
        config = connector.get_memory_statistics_config()
        self.assertEqual(config, Config.DEFAULT_CONFIG)

    def test_get_memory_statistics_config_error(self):
        """Test error handling in configuration retrieval"""
        connector = SonicDBConnector()
        self.mock_config_db.get_table.side_effect = Exception("Database error")
        with self.assertRaises(RuntimeError) as context:
            connector.get_memory_statistics_config()
        self.assertIn("Error retrieving memory statistics configuration", str(context.exception))


class TestSocketManager(unittest.TestCase):
    """Test cases for SocketManager class"""
    def setUp(self):
        self.socket_path = '/tmp/test_socket'
        self.socket_manager = SocketManager(self.socket_path)

    @patch('socket.socket')
    def test_successful_connection(self, mock_socket):
        """Test successful socket connection"""
        mock_socket.return_value.connect.return_value = None
        self.socket_manager.connect()
        mock_socket.assert_called_with(socket.AF_UNIX, socket.SOCK_STREAM)

    @patch('socket.socket')
    def test_connection_retry(self, mock_socket):
        """Test connection retry mechanism"""
        mock_socket.return_value.connect.side_effect = [
            socket.error("Connection failed"),
            None
        ]
        self.socket_manager.connect()
        self.assertEqual(mock_socket.return_value.connect.call_count, 2)

    @patch('os.path.exists')
    def test_validate_socket_path_success(self, mock_exists):
        """Test successful socket path validation"""
        mock_exists.return_value = True
        self.socket_manager._validate_socket_path()
        mock_exists.assert_called_once_with(os.path.dirname(self.socket_path))

    @patch('socket.socket')
    def test_connect_success(self, mock_socket):
        """Test successful socket connection"""
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.connect.side_effect = None
        self.socket_manager.connect()
        mock_sock.settimeout.assert_called_with(Config.SOCKET_TIMEOUT)
        mock_sock.connect.assert_called_with(self.socket_path)

    @patch('socket.socket')
    def test_connect_retry_success(self, mock_socket):
        """Test successful connection after retries"""
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.connect.side_effect = [socket.error(), socket.error(), None]
        self.socket_manager.connect()
        self.assertEqual(mock_sock.connect.call_count, 3)

    @patch('socket.socket')
    def test_receive_all_success(self, mock_socket):
        """Test successful data reception"""
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.recv.side_effect = [b'test', b'data', b'']
        self.socket_manager.sock = mock_sock
        result = self.socket_manager.receive_all()
        self.assertEqual(result, 'testdata')

    def test_close_success(self):
        """Test successful socket closure"""
        mock_sock = MagicMock()
        self.socket_manager.sock = mock_sock
        self.socket_manager.close()
        mock_sock.close.assert_called_once()
        self.assertIsNone(self.socket_manager.sock)

    def test_close_with_error(self):
        """Test socket closure with error"""
        mock_sock = MagicMock()
        mock_sock.close.side_effect = Exception("Close error")
        self.socket_manager.sock = mock_sock
        self.socket_manager.close()
        self.assertIsNone(self.socket_manager.sock)

    @patch('socket.socket')
    def test_send_data_success(self, mock_socket):
        """Test successful data sending"""
        mock_sock = MagicMock()
        self.socket_manager.sock = mock_sock
        test_data = "test message"
        self.socket_manager.send(test_data)
        mock_sock.sendall.assert_called_with(test_data.encode('utf-8'))

    def test_to_dict_method_with_list_of_dict2obj(self):
        """Test to_dict method with a list of Dict2Obj instances."""
        class TestDict2Obj(Dict2Obj):
            def to_dict(self):
                return {"test_key": "test_value"}

        test_obj = Dict2Obj({"items": [TestDict2Obj({"key": "value"}), "plain_value"]})
        result = test_obj.to_dict()
        assert result == [{"test_key": "test_value"}, "plain_value"]

    @patch('click.echo')
    def test_display_config_exception(self, mock_echo):
        """Test display_config function with database connection error."""
        mock_db_connector = Mock()
        mock_db_connector.get_memory_statistics_config.side_effect = Exception("DB Error")

        with patch('syslog.syslog') as mock_syslog:
            with pytest.raises(click.ClickException) as excinfo:
                display_config(mock_db_connector)

            assert "Failed to retrieve configuration: DB Error" in str(excinfo.value)
            mock_syslog.assert_called_once_with(
                syslog.LOG_ERR, "Failed to retrieve configuration: DB Error"
            )

    @patch('socket.socket')
    def test_receive_all_timeout_error(self, mock_socket):
        """Test receive_all method with a timeout error."""
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.recv.side_effect = socket.timeout
        self.socket_manager.sock = mock_sock
        with self.assertRaises(ConnectionError) as context:
            self.socket_manager.receive_all()
        self.assertIn("Socket operation timed out after", str(context.exception))

    @patch('socket.socket')
    def test_receive_all_socket_error(self, mock_socket):
        """Test receive_all method with socket error."""
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.recv.side_effect = socket.error
        self.socket_manager.sock = mock_sock
        with self.assertRaises(ConnectionError) as context:
            self.socket_manager.receive_all()
        self.assertIn("Socket error occurred during receive", str(context.exception))

    def test_clean_and_print_success(self):
        """Test clean_and_print function."""
        with patch('sys.stdout', new_callable=MagicMock()) as mock_stdout:
            clean_and_print("test message")
            mock_stdout.write.assert_called_with("test message\n")

    def test_format_field_value(self):
        """Test format_field_value function."""
        formatted_value = format_field_value("test_value")
        self.assertEqual(formatted_value, "test_value")

    @patch('click.echo')
    def test_display_statistics(self, mock_echo):
        """Test display_statistics function."""
        mock_data = {
            "used_memory": "50MB",
            "free_memory": "50MB"
        }
        display_statistics(mock_data)
        mock_echo.assert_called_with(f"Used Memory: 50MB\nFree Memory: 50MB\n")

    @patch('syslog.syslog')
    @patch('click.echo')
    def test_main(self, mock_echo, mock_syslog):
        """Test main function."""
        runner = CliRunner()
        result = runner.invoke(main)
        assert result.exit_code == 0
        mock_syslog.assert_called_once_with(syslog.LOG_INFO, "Displaying memory statistics.")
        mock_echo.assert_called_with("Memory Statistics are being shown...\n")


if __name__ == "__main__":
    unittest.main()
