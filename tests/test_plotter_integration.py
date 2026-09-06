"""End-to-end test of the plotter pipeline: builds a real job, spawns the
real vendor/plot_cli.py subprocess (which imports the real vendored
Graphtec.py driver) with dry_run=True, and checks it completes cleanly.

dry_run=True still probes for a real USB device (see Graphtec.py's own
docstring: "the device is still searched for ... it is allowed that there
be no device currently attached"), so this passes with no cutter plugged
in, but it does exercise the whole real code path -- subprocess, imports,
setup()/plot() -- rather than mocking any of it.
"""

from linuxprint.plotter.device_cli import run_job
from linuxprint.plotter.job import PlotJob, RegmarkSettings, ToolPass


def test_dry_run_cut_job_completes():
    job = PlotJob(
        passes=[ToolPass(tool="blade", paths=[[(0, 0), (10, 0), (10, 10)]])],
        dry_run=True,
    )
    events = []
    result = run_job(job, on_event=events.append)
    assert result.kind == "done"
    assert result.ok is True
    assert [e.kind for e in events] == ["pass_started", "pass_done", "done"]


def test_dry_run_multi_pass_job_without_regmark_completes():
    job = PlotJob(
        passes=[
            ToolPass(tool="blade", paths=[[(0, 0), (5, 5)]]),
            ToolPass(tool="pen", paths=[[(1, 1), (2, 2)]]),
        ],
        dry_run=True,
    )
    result = run_job(job)
    assert result.kind == "done"


def test_regmark_search_fails_without_a_real_device():
    # Print-and-cut's optical registration-mark search genuinely needs a
    # responding cutter (the driver waits for a status byte confirming the
    # marks were found); with no device attached, even dry_run correctly
    # reports failure rather than silently pretending it worked. This test
    # documents that real, expected behaviour rather than a bug.
    job = PlotJob(
        passes=[ToolPass(tool="blade", paths=[[(0, 0), (5, 5)]])],
        dry_run=True,
        regmark=RegmarkSettings(enabled=True),
    )
    result = run_job(job)
    assert result.kind == "error"
    assert "registration marks" in (result.message or "").lower()


def test_invalid_job_json_reports_error():
    import subprocess
    import sys

    from linuxprint.plotter.device_cli import PLOT_CLI

    process = subprocess.run(
        [sys.executable, str(PLOT_CLI)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode != 0
    assert "error" in process.stdout
