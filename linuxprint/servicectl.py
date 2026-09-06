"""Thin wrapper around `systemctl --user` for the background daemon unit."""

from __future__ import annotations

import subprocess

from .config import APP_ID

SERVICE_NAME = f"{APP_ID}-daemon.service"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    """
    Run a user-level systemctl command for the service.

    Parameters:
    	args (str): Arguments passed to systemctl before the service name.

    Returns:
    	subprocess.CompletedProcess: The completed systemctl command result,
    	or a synthetic failed result if systemctl is missing or times out.
    """
    command = ["systemctl", "--user", *args, SERVICE_NAME]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # No systemd on this system, or it didn't answer in time -- report
        # it as a failed command instead of letting the exception abort
        # whatever GUI action (e.g. building the settings tab) called us.
        return subprocess.CompletedProcess(command, -1, "", str(exc))


def is_installed() -> bool:
    """
    Determine whether the daemon service is installed.
    
    Returns:
    	bool: `True` if the service unit is installed, `False` otherwise.
    """
    result = _systemctl("cat")
    return result.returncode == 0


def is_active() -> bool:
    """
    Determine whether the daemon service is currently active.
    
    Returns:
    	bool: `true` if the service state is `active`, `false` otherwise.
    """
    result = _systemctl("is-active")
    return result.stdout.strip() == "active"


def is_enabled() -> bool:
    """Determine whether the daemon service is enabled to start automatically.
    
    Returns:
    	bool: `True` if the service is enabled, `False` otherwise.
    """
    result = _systemctl("is-enabled")
    return result.stdout.strip() == "enabled"


def start() -> subprocess.CompletedProcess:
    """Start the daemon service.
    
    Returns:
    	subprocess.CompletedProcess: The result of the systemctl command.
    """
    return _systemctl("start")


def stop() -> subprocess.CompletedProcess:
    """Stop the daemon service.
    
    Returns:
        subprocess.CompletedProcess: The completed systemctl command result.
    """
    return _systemctl("stop")


def enable_now() -> subprocess.CompletedProcess:
    """Enable the daemon service and start it immediately.
    
    Returns:
        subprocess.CompletedProcess: The completed systemctl command result.
    """
    return _systemctl("enable", "--now")


def disable_now() -> subprocess.CompletedProcess:
    """Disable the daemon service and stop it immediately.
    
    Returns:
        subprocess.CompletedProcess: The completed systemctl command result.
    """
    return _systemctl("disable", "--now")
