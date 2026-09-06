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
LEGACY_TRANSPORT_WARNING = (
    "The selected printer URI uses an unencrypted legacy network transport. "
    "Only continue if you trust the printer and the network."
)


class CupsToolMissing(RuntimeError):
    """Raised when a required CUPS command-line tool isn't installed."""


@dataclass
class ToolResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def _which(binary: str) -> str:
    """
    Resolve a CUPS command name to its executable path.
    
    Parameters:
        binary (str): Name of the executable to locate.
    
    Returns:
        str: Path to the executable.
    
    Raises:
        CupsToolMissing: If the executable cannot be found.
    """
    path = shutil.which(binary)
    if not path:
        raise CupsToolMissing(
            f"'{binary}' nebol nájdený. Nainštaluj balík 'cups-client' "
            f"(napr. `sudo apt install cups-client`)."
        )
    return path


def run(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> ToolResult:
    """
    Execute a CUPS command and capture its result.
    
    Parameters:
    	args (list[str]): Command name followed by its arguments.
    	timeout (int): Maximum execution time in seconds.
    
    Returns:
    	ToolResult: Command success status, exit code, standard output, and error output. A timed-out command has return code -1.
    """
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
    """Determine whether a command-line binary is available on the system.
    
    Parameters:
    	binary (str): The binary name or path to check.
    
    Returns:
    	bool: `true` if the binary is available, `false` otherwise.
    """
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
    """
    Parse CUPS printer status output into printer records keyed by printer name.
    
    Parameters:
        output (str): Text produced by `lpstat -p`.
    
    Returns:
        dict[str, Printer]: Printer records containing each printer's state and status reason.
    """
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
    """
    Parse printer job-acceptance statuses from `lpstat -a` output.
    
    Parameters:
        output (str): Raw output from the `lpstat -a` command.
    
    Returns:
        dict[str, bool]: A mapping of printer names to whether they accept jobs.
    """
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
    """
    Parse CUPS device listing output into printer names and device URIs.
    
    Parameters:
        output (str): Output from `lpstat -v`.
    
    Returns:
        dict[str, str]: A mapping from printer name to device URI.
    """
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
    """
    List configured printers with their default status, job acceptance state, and device URI.
    
    Returns:
    	dict[str, Printer]: Printers keyed by name.
    """
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
    """Retrieve the device URI for a printer.
    
    Parameters:
    	name (str): The printer name.
    
    Returns:
    	str | None: The printer's device URI, or `None` if no URI is found.
    """
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
    """Parse CUPS device discovery output into discovered devices.
    
    Parameters:
    	output (str): Device discovery output with one device kind and URI per line.
    
    Returns:
    	list[DiscoveredDevice]: Devices parsed from valid lines.
    """
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
    """List devices discovered by CUPS."""
    return parse_lpinfo_v(run(["lpinfo", "-v"], timeout=30).stdout)


# ---------------------------------------------------------------------------
# lpadmin (add / modify / remove)
# ---------------------------------------------------------------------------


def requires_legacy_transport_opt_in(uri: str) -> bool:
    """Return whether a network printer URI requires explicit user consent."""
    normalized = uri.lower()
    scheme = normalized.split(":", 1)[0]
    if scheme in {"ipp", "socket", "lpd", "http"}:
        return True
    if scheme == "dnssd":
        authority = normalized.partition("://")[2].split("/", 1)[0]
        return "._ipps._tcp." not in authority and not authority.endswith("._ipps._tcp")
    return False


def _legacy_transport_denied(uri: str, allow_legacy_transport: bool) -> ToolResult | None:
    if requires_legacy_transport_opt_in(uri) and allow_legacy_transport is not True:
        return ToolResult(False, -1, "", LEGACY_TRANSPORT_WARNING)
    return None


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
    allow_legacy_transport: bool = False,
) -> ToolResult:
    """
    Create or update a CUPS printer and optionally configure its operating state.
    
    Parameters:
        name (str): Printer name.
        uri (str): Device URI for the printer.
        description (str): Printer description.
        location (str): Printer location.
        driverless (bool): Whether to use the driverless `everywhere` model when no PPD is provided.
        ppd (str | None): PPD or CUPS model name to use instead of the driverless model.
        shared (bool): Whether to share the printer.
        enable (bool): Whether to enable the printer after creation or update.
        accept (bool): Whether to accept print jobs after creation or update.
        set_default (bool): Whether to make the printer the default.
        allow_legacy_transport (bool): Whether the user explicitly accepted an unencrypted network transport.
    
    Returns:
        ToolResult: The result of the printer creation or update command. Subsequent configuration commands are run only when that command succeeds.
    """
    denied = _legacy_transport_denied(uri, allow_legacy_transport)
    if denied is not None:
        return denied

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
        default_result = run(["lpoptions", "-d", name])
        if not default_result.ok:
            return default_result
    return result


def set_device_uri(name: str, uri: str, *, allow_legacy_transport: bool = False) -> ToolResult:
    """Update an existing printer to use the specified device URI.
    
    Parameters:
        name (str): Printer name.
        uri (str): New device URI.
        allow_legacy_transport (bool): Whether the user explicitly accepted an unencrypted network transport.
    
    Returns:
        ToolResult: The result of the `lpadmin` command.
    """
    denied = _legacy_transport_denied(uri, allow_legacy_transport)
    if denied is not None:
        return denied
    return run(["lpadmin", "-p", name, "-v", uri])


def remove_printer(name: str) -> ToolResult:
    """Remove a printer from CUPS.
    
    Parameters:
    	name (str): Name of the printer to remove.
    
    Returns:
    	ToolResult: Result of the CUPS removal command.
    """
    return run(["lpadmin", "-x", name])


def set_default(name: str) -> ToolResult:
    """Set the default printer.
    
    Returns:
        ToolResult: The result of the CUPS command.
    """
    return run(["lpoptions", "-d", name])


def set_enabled(name: str, enabled: bool) -> ToolResult:
    """
    Enable or disable a printer.
    
    Parameters:
        name (str): Name of the printer to update.
        enabled (bool): Whether the printer should accept print jobs.
    
    Returns:
        ToolResult: Result of the CUPS command.
    """
    return run(["cupsenable" if enabled else "cupsdisable", name])


def set_accepting(name: str, accepting: bool) -> ToolResult:
    """Set whether a printer accepts new jobs.
    
    Args:
        name: The printer name.
        accepting: Whether the printer should accept new jobs.
    
    Returns:
        The command execution result.
    """
    return run(["cupsaccept" if accepting else "cupsreject", name])


def set_shared(name: str, shared: bool) -> ToolResult:
    """Set whether a printer is shared with other clients.
    
    Parameters:
    	name (str): The printer name.
    	shared (bool): Whether the printer should be shared.
    
    Returns:
    	ToolResult: The result of the CUPS command.
    """
    return run(["lpadmin", "-p", name, "-o", f"printer-is-shared={'true' if shared else 'false'}"])


def rename_printer(
    old_name: str,
    new_name: str,
    uri: str,
    *,
    allow_legacy_transport: bool = False,
) -> ToolResult:
    """
    Rename a CUPS printer by creating the new printer and removing the old one.
    
    Parameters:
        old_name (str): Name of the existing printer.
        new_name (str): Name for the new printer.
        uri (str): Device URI for the new printer.
        allow_legacy_transport (bool): Whether the user explicitly accepted an unencrypted network transport.
    
    Returns:
        ToolResult: Result of creating the new printer.
    """
    result = add_or_update_printer(new_name, uri, allow_legacy_transport=allow_legacy_transport)
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
    """
    Parse CUPS job queue output into job records.
    
    Parameters:
    	output (str): Raw text from the CUPS job listing command.
    
    Returns:
    	list[Job]: Parsed jobs, including raw lines for entries with incomplete formats.
    """
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
    """List queued print jobs, optionally limited to a specific printer.
    
    Parameters:
        printer (str | None): Name of the printer whose queued jobs should be listed.
    
    Returns:
        list[Job]: Parsed queued print jobs.
    """
    args = ["lpstat", "-o"]
    if printer:
        args.append(printer)
    return parse_lpstat_o(run(args).stdout)


def cancel_job(job_id: str) -> ToolResult:
    """Cancel a print job.
    
    Parameters:
    	job_id (str): Identifier of the print job to cancel.
    
    Returns:
    	ToolResult: The result of the CUPS cancel command.
    """
    return run(["cancel", job_id])


def hold_job(job_id: str) -> ToolResult:
    """Place a print job on hold.
    
    Parameters:
    	job_id (str): Identifier of the job to hold.
    
    Returns:
    	ToolResult: The result of the CUPS command.
    """
    return run(["lp", "-i", job_id, "-H", "hold"])


def release_job(job_id: str) -> ToolResult:
    """Resume a paused print job.
    
    Parameters:
    	job_id (str): Identifier of the job to resume.
    
    Returns:
    	ToolResult: The result of the CUPS command."""
    return run(["lp", "-i", job_id, "-H", "resume"])


def move_job(job_id: str, destination_printer: str) -> ToolResult:
    """Move a print job to a different printer.
    
    Parameters:
    	job_id (str): Identifier of the print job to move.
    	destination_printer (str): Name of the printer to receive the job.
    
    Returns:
    	ToolResult: Result of the CUPS move operation.
    """
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
