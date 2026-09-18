from unittest.mock import patch
from nse_downloader.notifications import send_failure_notification

@patch("nse_downloader.notifications.subprocess.run")
def test_send_notification_calls_osascript_on_darwin(mock_run):
    with patch("sys.platform", "darwin"):
        send_failure_notification("Test Dataset", "Connection Error")
        
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
        assert 'Test Dataset Failed' in args[2]
        assert 'Connection Error' in args[2]

@patch("nse_downloader.notifications.logger")
@patch("nse_downloader.notifications.subprocess.run")
def test_send_notification_logs_on_non_darwin(mock_run, mock_logger):
    with patch("sys.platform", "linux"):
        send_failure_notification("Test Dataset", "Connection Error")
        
        mock_run.assert_not_called()
        mock_logger.error.assert_called_once()
