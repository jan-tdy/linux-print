"""Thin, safe wrapper around the standard CUPS command-line tools.

Every function that talks to the system goes through :func:`run`, which never
uses a shell and always returns a :class:`ToolResult` instead of raising on a
non-zero exit code -- CUPS tools routinely return non-zero for perfectly
normal situations (e.g. "no jobs queued"). Parsing of command output is
factored into separate pure functions so it can be unit tested without any
CUPS installation.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

DEFAULT_TIMEOUT = 15


class CupsToolMissing(RuntimeError):
    """Raised when a required CUPS command-line tool isn't installed."""


@dataclass
class ToolResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def _which(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise CupsToolMissing(
            f"'{binary}' nebol nájdený. Nainštaluj balík 'cups-client' "
            f"(napr. `sudo apt install cups-client`)."
        )
    return path


def run(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> ToolResult:
    binary = _which(args[0])
    try:
        proc = subprocess.run(
            [binary, *args[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolResult(False, -1, "", f"timeout: {exc}")
    return ToolResult(proc.returncode == 0, proc.returncode, proc.stdout, proc.stderr)


def is_available(binary: str) -> bool:
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# Printers
# ---------------------------------------------------------------------------


@dataclass
class Printer:
    name: str
    state: str = "unknown"  # idle | printing | stopped | unknown
    state_reason: str = ""
    accepting: bool = True
    is_default: bool = False
    uri: str = ""
    description: str = ""
    location: str = ""
    shared: bool = False


_STATE_RE = re.compile(
    r"^printer\s+(?P<name>\S+)\s+(?P<state>is idle|now printing|is stopped|"
    r"disabled)(?P<rest>.*)$"
)


def parse_lpstat_p(output: str) -> dict[str, Printer]:
    """Parse `lpstat -p` output into a name -> Printer map."""
    printers: dict[str, Printer] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("printer "):
            continue
        m = _STATE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        state_text = m.group("state")
        if state_text == "is idle":
            state = "idle"
        elif state_text == "now printing":
            state = "printing"
        else:
            state = "stopped"
        reason = ""
        rest = m.group("rest") or ""
        reason_match = re.search(r"reason(?:s)?:\s*(.+?)\.?$", rest, re.IGNORECASE)
        if reason_match:
            reason = reason_match.group(1).strip()
        printers[name] = Printer(name=name, state=state, state_reason=reason)
    return printers


def parse_lpstat_d(output: str) -> str | None:
    """Parse `lpstat -d` output, returning the default printer name (or None)."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("system default destination:"):
            value = line.split(":", 1)[1].strip()
            return value or None
        if "no system default destination" in line.lower():
            return None
    return None


def parse_lpstat_a(output: str) -> dict[str, bool]:
    """Parse `lpstat -a` (accepting jobs) into name -> accepting bool."""
    accepting: dict[str, bool] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        name = parts[0]
        accepting[name] = "not accepting" not in line.lower()
    return accepting


def parse_lpstat_v(output: str) -> dict[str, str]:
    """Parse `lpstat -v [name]` into name -> device URI."""
    uris: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("device for "):
            continue
        rest = line[len("device for ") :]
        if ":" not in rest:
            continue
        name, uri = rest.split(":", 1)
        uris[name.strip()] = uri.strip()
    return uris


def list_printers() -> dict[str, Printer]:
    printers = parse_lpstat_p(run(["lpstat", "-p"]).stdout)
    default = parse_lpstat_d(run(["lpstat", "-d"]).stdout)
    accepting = parse_lpstat_a(run(["lpstat", "-a"]).stdout)
    uris = parse_lpstat_v(run(["lpstat", "-v"]).stdout)
    for name, printer in printers.items():
        printer.is_default = name == default
        if name in accepting:
            printer.accepting = accepting[name]
        if name in uris:
            printer.uri = uris[name]
    return printers


def printer_uri(name: str) -> str | None:
    return parse_lpstat_v(run(["lpstat", "-v", name]).stdout).get(name)


# ---------------------------------------------------------------------------
# lpinfo (discovery of available devices/drivers)
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredDevice:
    kind: str  # "network" | "direct" (usb/serial/parallel) | "other"
    uri: str
    scheme: str = field(init=False)

    def __post_init__(self) -> None:
        self.scheme = self.uri.split(":", 1)[0] if ":" in self.uri else ""


def parse_lpinfo_v(output: str) -> list[DiscoveredDevice]:
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        kind, uri = parts
        devices.append(DiscoveredDevice(kind=kind, uri=uri))
    return devices


def lpinfo_devices() -> list[DiscoveredDevice]:
    return parse_lpinfo_v(run(["lpinfo", "-v"], timeout=30).stdout)


# ---------------------------------------------------------------------------
# lpadmin (add / modify / remove)
# ---------------------------------------------------------------------------


def add_or_update_printer(
    name: str,
    uri: str,
    *,
    description: str = "",
    location: str = "",
    driverless: bool = True,
    ppd: str | None = None,
    shared: bool = False,
    enable: bool = True,
    accept: bool = True,
    set_default: bool = False,
) -> ToolResult:
    args = ["lpadmin", "-p", name, "-v", uri, "-E"]
    if driverless and not ppd:
        args += ["-m", "everywhere"]
    elif ppd:
        args += ["-m", ppd]
    if description:
        args += ["-D", description]
    if location:
        args += ["-L", location]
    args += ["-o", "printer-is-shared=" + ("true" if shared else "false")]
    result = run(args)
    if not result.ok:
        return result
    if enable:
        run(["cupsenable", name])
    if accept:
        run(["cupsaccept", name])
    if set_default:
        run(["lpoptions", "-d", name])
    return result


def set_device_uri(name: str, uri: str) -> ToolResult:
    """Repoint an existing printer at a new device URI (used by the healer)."""
    return run(["lpadmin", "-p", name, "-v", uri])


def remove_printer(name: str) -> ToolResult:
    return run(["lpadmin", "-x", name])


def set_default(name: str) -> ToolResult:
    return run(["lpoptions", "-d", name])


def set_enabled(name: str, enabled: bool) -> ToolResult:
    return run(["cupsenable" if enabled else "cupsdisable", name])


def set_accepting(name: str, accepting: bool) -> ToolResult:
    return run(["cupsaccept" if accepting else "cupsreject", name])


def set_shared(name: str, shared: bool) -> ToolResult:
    return run(["lpadmin", "-p", name, "-o", f"printer-is-shared={'true' if shared else 'false'}"])


def rename_printer(old_name: str, new_name: str, uri: str) -> ToolResult:
    """CUPS has no rename primitive: add under the new name, drop the old one."""
    result = add_or_update_printer(new_name, uri)
    if result.ok:
        remove_printer(old_name)
    return result


# ---------------------------------------------------------------------------
# Job queue
# ---------------------------------------------------------------------------


@dataclass
class Job:
    job_id: str
    printer: str
    user: str = ""
    size: str = ""
    raw: str = ""


_JOB_RE = re.compile(r"^(?P<id>\S+)\s+(?P<user>\S+)\s+(?P<size>\d+)\s")


def parse_lpstat_o(output: str) -> list[Job]:
    jobs = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _JOB_RE.match(line)
        job_id = m.group("id") if m else line.split()[0]
        user = m.group("user") if m else ""
        size = m.group("size") if m else ""
        printer = job_id.rsplit("-", 1)[0] if "-" in job_id else job_id
        jobs.append(Job(job_id=job_id, printer=printer, user=user, size=size, raw=line))
    return jobs


def list_jobs(printer: str | None = None) -> list[Job]:
    args = ["lpstat", "-o"]
    if printer:
        args.append(printer)
    return parse_lpstat_o(run(args).stdout)


def cancel_job(job_id: str) -> ToolResult:
    return run(["cancel", job_id])


def hold_job(job_id: str) -> ToolResult:
    return run(["lp", "-i", job_id, "-H", "hold"])


def release_job(job_id: str) -> ToolResult:
    return run(["lp", "-i", job_id, "-H", "resume"])


def move_job(job_id: str, destination_printer: str) -> ToolResult:
    return run(["lpmove", job_id, destination_printer])


# ---------------------------------------------------------------------------
# Remote CUPS server browsing
# ---------------------------------------------------------------------------


def list_remote_printers(server: str) -> list[str]:
    """List printer names shared by a remote CUPS server (host[:port])."""
    result = run(["lpstat", "-h", server, "-a"], timeout=20)
    if not result.ok:
        return []
    return sorted(parse_lpstat_a(result.stdout).keys())
