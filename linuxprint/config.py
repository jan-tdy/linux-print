"""Paths and persisted settings for Jadiv Print Center."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def _xdg_dir(env_var: str, default: str) -> Path:
    """
    Resolve a directory path from an environment variable or a home-directory default.
    
    Parameters:
        env_var (str): Name of the environment variable to inspect.
        default (str): Relative default directory path under the user's home directory.
    
    Returns:
        Path: The configured directory path, or the default path when the environment variable is unset or empty.
    """
    value = os.environ.get(env_var)
    return Path(value) if value else Path.home() / default


APP_ID = "jadiv-print-center"
APP_NAME = "Jadiv Print Center"
APP_VERSION = "1.5.0"

CONFIG_DIR = _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_ID
DATA_DIR = _xdg_dir("XDG_DATA_HOME", ".local/share") / APP_ID
LOG_DIR = DATA_DIR / "logs"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
IDENTITY_FILE = DATA_DIR / "printers.json"
HEALER_LOG_FILE = LOG_DIR / "healer.log"
IPC_SOCKET_NAME = f"{APP_ID}-ipc"
IPC_LOCK_FILE = CONFIG_DIR / f"{APP_ID}.lock"


@dataclass
class Settings:
    check_interval_seconds: int = 30
    notifications_enabled: bool = True
    autoheal_enabled: bool = True
    known_remote_servers: list[str] | None = None

    def __post_init__(self) -> None:
        """Initialize the known remote server list when it was not provided."""
        if self.known_remote_servers is None:
            self.known_remote_servers = []


def ensure_dirs() -> None:
    """
    Create the application configuration, data, and log directories if they do not exist.
    """
    for path in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


# Expected type for each Settings field, used to reject a corrupt or
# hand-edited settings.json instead of crashing later (e.g. the watcher
# doing arithmetic on a check_interval_seconds that turned out to be a str).
_FIELD_TYPES: dict[str, type] = {
    "check_interval_seconds": int,
    "notifications_enabled": bool,
    "autoheal_enabled": bool,
    "known_remote_servers": list,
}

# check_interval_seconds also needs a range check, not just a type check:
# it feeds QTimer.setInterval(seconds * 1000) (linuxprint/watcher.py), and
# QTimer's interval is a signed 32-bit millisecond count, so an
# out-of-range-but-technically-valid int (e.g. from a hand-edited
# settings.json) would overflow it. This mirrors the GUI's own
# QSpinBox(5, 3600) range.
_CHECK_INTERVAL_RANGE = (5, 3600)


def load_settings() -> Settings:
    """
    Load application settings from the persisted settings file.
    
    Malformed, unreadable, or missing settings files result in default settings. Unrecognized fields are ignored.
    
    Returns:
        Settings: The loaded settings or default settings when the file is unavailable or invalid.
    """
    ensure_dirs()
    if not SETTINGS_FILE.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    valid = {}
    for key, value in data.items():
        expected = _FIELD_TYPES.get(key)
        if expected is None:
            continue
        # bool is a subclass of int, so it has to be handled explicitly on
        # both sides: an int field must reject True/False (isinstance(True,
        # int) is True), and a bool field must reject plain 0/1.
        is_bool_value = isinstance(value, bool)
        if expected is bool:
            if is_bool_value:
                valid[key] = value
        elif expected is int:
            if isinstance(value, int) and not is_bool_value and _CHECK_INTERVAL_RANGE[0] <= value <= _CHECK_INTERVAL_RANGE[1]:
                valid[key] = value
        elif isinstance(value, expected):
            valid[key] = value
    return Settings(**valid)


def save_settings(settings: Settings) -> None:
    """
    Persist application settings as formatted JSON.
    """
    ensure_dirs()
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
