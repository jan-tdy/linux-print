"""Self-healing logic: reconcile installed CUPS printers against freshly
discovered devices and decide what, if anything, needs repairing.

The decision function (:func:`plan_repairs`) is pure -- it takes plain data
in and returns a plain list of :class:`Repair` out, with no subprocess calls
of its own, so the "what should we fix" logic is fully unit-testable. Only
:func:`apply_repairs` touches the system, via :mod:`cups_cli`.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from . import cups_cli
from .cups_cli import Printer
from .discovery import DiscoveredPrinter, IP_PINNED_SCHEMES
from .identity import IdentityRecord


@dataclass
class Repair:
    printer_name: str
    old_uri: str
    new_uri: str
    reason: str


@dataclass
class RepairResult:
    repair: Repair
    ok: bool
    message: str


def plan_repairs(
    installed: dict[str, Printer],
    discovered: list[DiscoveredPrinter],
    identities: dict[str, IdentityRecord],
) -> list[Repair]:
    """Compare what's installed against what's currently discoverable and
    propose device-URI fixes for printers that drifted.

    Printers added via a self-healing scheme (dnssd://, usb://) are skipped
    on purpose -- CUPS already re-resolves those on every job, so touching
    them would only add risk for no benefit. Only printers pinned to a raw
    IP/port (ipp://, ipps://, socket://, lpd://) that we have a recorded
    identity for are candidates for repair.
    """
    by_key: dict[str, DiscoveredPrinter] = {}
    for device in discovered:
        by_key.setdefault(device.identity_key, device)

    repairs: list[Repair] = []
    for name, record in identities.items():
        printer = installed.get(name)
        if printer is None:
            continue  # printer was removed outside this tool; nothing to do
        current_scheme = printer.uri.split(":", 1)[0] if ":" in printer.uri else ""
        if current_scheme not in IP_PINNED_SCHEMES:
            continue
        match = by_key.get(record.identity_key)
        if match is None:
            continue
        if match.uri == printer.uri:
            continue
        repairs.append(
            Repair(
                printer_name=name,
                old_uri=printer.uri,
                new_uri=match.uri,
                reason=(
                    f"Tlačiareň '{name}' zmenila adresu "
                    f"({printer.uri} -> {match.uri}); opravujem CUPS frontu."
                ),
            )
        )
    return repairs


def apply_repairs(repairs: list[Repair]) -> list[RepairResult]:
    results = []
    for repair in repairs:
        result = cups_cli.set_device_uri(repair.printer_name, repair.new_uri)
        message = repair.reason if result.ok else f"Oprava zlyhala: {result.stderr.strip()}"
        results.append(RepairResult(repair=repair, ok=result.ok, message=message))
    return results


def is_host_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick TCP reachability probe, used to flag printers as offline in the
    UI even when we can't (or shouldn't) touch their CUPS configuration."""
    if not host or not port:
        return True
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def log_line(message: str) -> str:
    return f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"


def append_log(message: str) -> None:
    from . import config

    config.ensure_dirs()
    with config.HEALER_LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(log_line(message) + "\n")
