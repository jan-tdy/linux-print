"""Persisted mapping from an installed CUPS printer name to the discovery
identity it was added from, so the healer can recognise "the same printer"
again after its IP address or port changes.
"""

from __future__ import annotations

import fcntl
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from . import config
from .discovery import DiscoveredPrinter

_LOGGER = logging.getLogger(__name__)


@dataclass
class IdentityRecord:
    identity_key: str
    category: str
    added_uri: str
    added_at: float
    legacy_transport_allowed: bool = False


def load_map() -> dict[str, IdentityRecord]:
    """
    Load persisted printer identity records from the identity file.
    
    Returns:
    	dict[str, IdentityRecord]: A mapping of printer names to valid identity records. Empty if the file is missing, unreadable, invalid, or contains no valid records.
    """
    config.ensure_dirs()
    if not config.IDENTITY_FILE.exists():
        return {}
    try:
        raw = json.loads(config.IDENTITY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as err:
        _LOGGER.warning("Could not read printer identity file %s; using an empty map: %s", config.IDENTITY_FILE, err)
        return {}
    if not isinstance(raw, dict):
        _LOGGER.warning("Printer identity file %s is not a JSON object; using an empty map", config.IDENTITY_FILE)
        return {}
    records = {}
    for name, value in raw.items():
        try:
            record = IdentityRecord(**value)
        except TypeError:
            continue
        record.legacy_transport_allowed = record.legacy_transport_allowed is True
        records[name] = record
    return records


def save_map(records: dict[str, IdentityRecord]) -> None:
    """
    Persist printer identity records to the configured identity file.
    
    Parameters:
    	records (dict[str, IdentityRecord]): Mapping of printer names to identity records.
    """
    config.ensure_dirs()
    payload = {name: asdict(record) for name, record in records.items()}
    config.atomic_write_text(config.IDENTITY_FILE, json.dumps(payload, indent=2))


@contextmanager
def _identity_lock():
    lock_path = config.IDENTITY_FILE.with_suffix(config.IDENTITY_FILE.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def remember(name: str, discovered: DiscoveredPrinter, *, legacy_transport_allowed: bool = False) -> None:
    """
    Record a discovered printer's identity information under the specified name.
    
    Parameters:
    	name (str): The printer name used as the mapping key.
    	discovered (DiscoveredPrinter): The discovered printer metadata to store.
        legacy_transport_allowed (bool): Whether the user explicitly accepted this printer's unencrypted transport.
    """
    with _identity_lock():
        records = load_map()
        records[name] = IdentityRecord(
            identity_key=discovered.identity_key,
            category=discovered.category,
            added_uri=discovered.uri,
            added_at=time.time(),
            legacy_transport_allowed=legacy_transport_allowed is True,
        )
        save_map(records)


def forget(name: str) -> None:
    """Remove the stored identity record for a printer name, if present.
    
    Parameters:
    	name (str): The printer name whose identity record should be removed.
    """
    with _identity_lock():
        records = load_map()
        if name in records:
            del records[name]
            save_map(records)
