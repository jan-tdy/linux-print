"""Persisted mapping from an installed CUPS printer name to the discovery
identity it was added from, so the healer can recognise "the same printer"
again after its IP address or port changes.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from . import config
from .discovery import DiscoveredPrinter


@dataclass
class IdentityRecord:
    identity_key: str
    category: str
    added_uri: str
    added_at: float


def load_map() -> dict[str, IdentityRecord]:
    config.ensure_dirs()
    if not config.IDENTITY_FILE.exists():
        return {}
    try:
        raw = json.loads(config.IDENTITY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    records = {}
    for name, value in raw.items():
        try:
            records[name] = IdentityRecord(**value)
        except TypeError:
            continue
    return records


def save_map(records: dict[str, IdentityRecord]) -> None:
    config.ensure_dirs()
    payload = {name: asdict(record) for name, record in records.items()}
    config.IDENTITY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def remember(name: str, discovered: DiscoveredPrinter) -> None:
    records = load_map()
    records[name] = IdentityRecord(
        identity_key=discovered.identity_key,
        category=discovered.category,
        added_uri=discovered.uri,
        added_at=time.time(),
    )
    save_map(records)


def forget(name: str) -> None:
    records = load_map()
    if name in records:
        del records[name]
        save_map(records)
