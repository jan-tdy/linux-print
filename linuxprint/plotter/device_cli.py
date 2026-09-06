"""Run a plotter job by launching vendor/plot_cli.py as a subprocess.

This module is MIT-licensed, same as the rest of linuxprint, and never
imports the vendored GPL-2.0 driver directly -- see
vendor/inkscape_silhouette/NOTICE.md for why. It only shells out to it, the
same way linuxprint/cups_cli.py shells out to lpadmin/lpstat instead of
linking libcups.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
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


_STDOUT_DONE = object()  # sentinel: stdout thread hit EOF


def _pump_lines(stream, sink: "queue.Queue") -> None:
    try:
        for line in stream:
            sink.put(line)
    except ValueError:
        pass  # stream closed under us, e.g. after process.kill()
    finally:
        sink.put(_STDOUT_DONE)


def _drain_text(stream, chunks: list[str]) -> None:
    try:
        for chunk in stream:
            chunks.append(chunk)
    except ValueError:
        pass  # stream closed under us, e.g. after process.kill()


def run_job(job: PlotJob, on_event=None, timeout: float = 30.0) -> PlotEvent:
    """Run a plotter job to completion, calling on_event(PlotEvent) for each
    line the subprocess reports (if given). Returns the final "done" or
    "error" event, or an "error" event if the job doesn't finish within
    `timeout` seconds. Raises OSError if the vendored helper can't even
    start (e.g. python3 missing, which would be a packaging bug, not a
    device problem).

    stdout and stderr are drained on separate threads: plot_cli.py passes
    stderr to the vendored driver as its progress-log target, and if that
    pipe's OS buffer fills while this function is only reading stdout, the
    child blocks writing to stderr and this function would otherwise hang
    forever waiting for a stdout line that will never come.
    """
    process = subprocess.Popen(
        [sys.executable, str(PLOT_CLI)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.write(json.dumps(job.to_json()))
    process.stdin.close()

    stdout_lines: queue.Queue = queue.Queue()
    stderr_chunks: list[str] = []
    stdout_thread = threading.Thread(target=_pump_lines, args=(process.stdout, stdout_lines), daemon=True)
    stderr_thread = threading.Thread(target=_drain_text, args=(process.stderr, stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    final_event = PlotEvent(kind="error", message="plot_cli.py produced no output")
    deadline = time.monotonic() + timeout
    timed_out = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            item = stdout_lines.get(timeout=remaining)
        except queue.Empty:
            timed_out = True
            break
        if item is _STDOUT_DONE:
            break
        event = _parse_event(item)
        if event is None:
            continue
        if on_event is not None:
            on_event(event)
        if event.kind in ("done", "error"):
            final_event = event

    if timed_out:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        return PlotEvent(kind="error", message=f"plot_cli.py timed out after {timeout:.0f}s")

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait(timeout=5)
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)

    stderr = "".join(stderr_chunks)
    if returncode != 0 and final_event.kind != "error":
        final_event = PlotEvent(kind="error", message=stderr.strip() or f"exit code {returncode}")
    return final_event
