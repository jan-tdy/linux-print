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

    A raw-IP identity key deliberately excludes the host (see
    :mod:`discovery`), so two *different* physical printers can end up
    sharing one key (e.g. two office printers both serving
    ``ipp://.../ipp/print``). Repairing in that situation would be a guess
    that could silently redirect one printer's jobs to another device, so a
    repair is only ever proposed for a key that maps to exactly one
    installed printer *and* exactly one currently discovered device.
    """
    discovered_by_key: dict[str, list[DiscoveredPrinter]] = {}
    for device in discovered:
        discovered_by_key.setdefault(device.identity_key, []).append(device)

    # A stale record for a printer removed outside this tool must not count
    # toward ambiguity for a live printer that happens to share its key.
    installed_names_by_key: dict[str, list[str]] = {}
    for name, record in identities.items():
        if name not in installed:
            continue
        installed_names_by_key.setdefault(record.identity_key, []).append(name)

    repairs: list[Repair] = []
    for name, record in identities.items():
        printer = installed.get(name)
        if printer is None:
            continue  # printer was removed outside this tool; nothing to do
        current_scheme = printer.uri.split(":", 1)[0] if ":" in printer.uri else ""
        if current_scheme not in IP_PINNED_SCHEMES:
            continue
        if len(installed_names_by_key.get(record.identity_key, [])) != 1:
            continue  # ambiguous: another installed printer shares this identity
        matches = discovered_by_key.get(record.identity_key, [])
        if len(matches) != 1:
            continue  # no match, or more than one device claims this identity
        match = matches[0]
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
    """
    Apply planned printer repairs and collect their outcomes.
    
    Parameters:
    	repairs (list[Repair]): Repairs to apply.
    
    Returns:
    	list[RepairResult]: The result of each repair, including its success status and message.
    """
    results = []
    for repair in repairs:
        result = cups_cli.set_device_uri(repair.printer_name, repair.new_uri)
        message = repair.reason if result.ok else f"Oprava zlyhala: {result.stderr.strip()}"
        results.append(RepairResult(repair=repair, ok=result.ok, message=message))
    return results


def is_host_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Determine whether a host accepts a TCP connection on the specified port.
    
    Parameters:
        host (str): Hostname or IP address to probe.
        port (int): TCP port to probe.
        timeout (float): Maximum time to wait for the connection, in seconds.
    
    Returns:
        bool: `true` if the connection succeeds or the host or port is empty, `false` if the connection fails.
    """
    if not host or not port:
        return True
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def log_line(message: str) -> str:
    """
    Format a message with the current local timestamp.
    
    Parameters:
    	message (str): The message to format.
    
    Returns:
    	str: The timestamped message.
    """
    return f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"


def append_log(message: str) -> None:
    """
    Append a timestamped message to the healer log file.
    
    Parameters:
        message (str): The message to append.
    """
    from . import config

    config.ensure_dirs()
    with config.HEALER_LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(log_line(message) + "\n")
