"""Thin wrapper around `systemctl --user` for the background daemon unit."""

from __future__ import annotations

import subprocess

from .config import APP_ID

SERVICE_NAME = f"{APP_ID}-daemon.service"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args, SERVICE_NAME],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def is_installed() -> bool:
    result = _systemctl("cat")
    return result.returncode == 0


def is_active() -> bool:
    result = _systemctl("is-active")
    return result.stdout.strip() == "active"


def is_enabled() -> bool:
    result = _systemctl("is-enabled")
    return result.stdout.strip() == "enabled"


def start() -> subprocess.CompletedProcess:
    return _systemctl("start")


def stop() -> subprocess.CompletedProcess:
    return _systemctl("stop")


def enable_now() -> subprocess.CompletedProcess:
    return _systemctl("enable", "--now")


def disable_now() -> subprocess.CompletedProcess:
    return _systemctl("disable", "--now")
