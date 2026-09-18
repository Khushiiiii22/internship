import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

def send_failure_notification(dataset_name: str, error_msg: str) -> None:
    """
    Sends a desktop notification on macOS indicating a download failure.
    Falls back to a simple log message on other platforms.
    """
    title = f"NSE Downloader: {dataset_name} Failed"
    message = str(error_msg).replace('"', "'")

    if sys.platform == "darwin":
        try:
            apple_script = f'display notification "{message}" with title "{title}" sound name "Basso"'
            subprocess.run(["osascript", "-e", apple_script], check=False)
        except Exception as exc:
            logger.debug("Failed to send macOS desktop notification: %s", exc)
    else:
        logger.error("[NOTIFICATION] %s: %s", title, message)
