"""Run a plotter job by launching vendor/plot_cli.py as a subprocess.

This module is MIT-licensed, same as the rest of linuxprint, and never
imports the vendored GPL-2.0 driver directly -- see
vendor/inkscape_silhouette/NOTICE.md for why. It only shells out to it, the
same way linuxprint/cups_cli.py shells out to lpadmin/lpstat instead of
linking libcups.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .job import PlotJob

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
PLOT_CLI = _VENDOR_DIR / "plot_cli.py"


@dataclass
class PlotEvent:
    kind: str  # "pass_started" | "pass_done" | "done" | "error"
    index: int | None = None
    tool: str | None = None
    message: str | None = None
    ok: bool | None = None


def _parse_event(line: str) -> PlotEvent | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return PlotEvent(
        kind=data.get("event", "unknown"),
        index=data.get("index"),
        tool=data.get("tool"),
        message=data.get("message"),
        ok=data.get("ok"),
    )


def run_job(job: PlotJob, on_event=None) -> PlotEvent:
    """Run a plotter job to completion, calling on_event(PlotEvent) for each
    line the subprocess reports (if given). Returns the final "done" or
    "error" event. Raises OSError if the vendored helper can't even start
    (e.g. python3 missing, which would be a packaging bug, not a device
    problem)."""
    process = subprocess.Popen(
        [sys.executable, str(PLOT_CLI)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(job.to_json()))
    process.stdin.close()

    final_event = PlotEvent(kind="error", message="plot_cli.py produced no output")
    for line in process.stdout:
        event = _parse_event(line)
        if event is None:
            continue
        if on_event is not None:
            on_event(event)
        if event.kind in ("done", "error"):
            final_event = event

    returncode = process.wait(timeout=30)
    stderr = process.stderr.read() if process.stderr else ""
    if returncode != 0 and final_event.kind != "error":
        final_event = PlotEvent(kind="error", message=stderr.strip() or f"exit code {returncode}")
    return final_event
