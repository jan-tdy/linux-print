#!/usr/bin/env python3
"""Standalone runner that drives a Silhouette Cameo cutter for one job.

GPL-2.0 licensed (see inkscape_silhouette/LICENSE): this script directly
imports inkscape_silhouette.Graphtec.SilhouetteCameo, the vendored
GPL-2.0 protocol driver, into its own process. See
inkscape_silhouette/NOTICE.md for why this runs as a separate subprocess
instead of being imported by the rest of (MIT-licensed) linuxprint.

Protocol: a single JSON object is read from stdin (see JOB SCHEMA below).
Progress and the final result are written to stdout as one JSON object per
line, so the caller can stream status without waiting for the whole job.
Exit code is 0 on success, 1 on any failure.

JOB SCHEMA (stdin, one JSON object):
{
  "force_hardware": "Silhouette_Cameo5" | null,   # null = autodetect over USB
  "dry_run": false,                                # true: exercise the
                                                    # driver without touching
                                                    # real hardware (used by
                                                    # tests)
  "cuttingmat": "cameo_12x12" | "no_mat" | null,
  "media_width_mm": 300.0,
  "media_height_mm": 300.0,
  "regmark": {                                     # omit/null: no
                                                    # print-and-cut alignment
    "search": true,
    "width_mm": 180.0,
    "length_mm": 230.0,
    "origin_x_mm": 15.0,
    "origin_y_mm": 20.0,
    "quad": false
  },
  "passes": [                                      # run in order, e.g.
                                                    # blade pass then pen pass
    {
      "tool": "blade" | "pen",
      "toolholder": 1,                             # 1 or 2, for the few
                                                    # dual-carriage models
      "speed": 10,
      "pressure": 27,
      "depth": null,
      "paths": [[[x_mm, y_mm], ...], ...]          # polylines in mm,
                                                    # already flattened
    }
  ]
}

Output lines (stdout, one JSON object per line):
  {"event": "pass_started", "index": 0, "tool": "blade"}
  {"event": "pass_done", "index": 0}
  {"event": "done", "ok": true}
  {"event": "error", "message": "..."}
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from inkscape_silhouette.Graphtec import SilhouetteCameo  # noqa: E402


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def run_job(job: dict) -> bool:
    device = SilhouetteCameo(
        log=sys.stderr,
        dry_run=bool(job.get("dry_run", False)),
        force_hardware=job.get("force_hardware"),
    )

    regmark = job.get("regmark") or {}
    media_width = float(job.get("media_width_mm", 210.0))
    media_height = float(job.get("media_height_mm", 297.0))
    cuttingmat = job.get("cuttingmat")

    for index, step in enumerate(job.get("passes", [])):
        tool = step.get("tool", "blade")
        _emit({"event": "pass_started", "index": index, "tool": tool})
        device.setup(
            speed=step.get("speed"),
            pressure=step.get("pressure"),
            toolholder=step.get("toolholder", 1),
            pen=(tool == "pen"),
            depth=step.get("depth"),
            cuttingmat=cuttingmat,
            mediawidth=media_width,
            mediaheight=media_height,
        )
        device.plot(
            mediawidth=media_width,
            mediaheight=media_height,
            pathlist=step.get("paths", []),
            regmark=bool(regmark),
            regsearch=bool(regmark.get("search", True)) if regmark else False,
            regwidth=float(regmark.get("width_mm", 180.0)) if regmark else 180.0,
            reglength=float(regmark.get("length_mm", 230.0)) if regmark else 230.0,
            regoriginx=float(regmark.get("origin_x_mm", 15.0)) if regmark else 15.0,
            regoriginy=float(regmark.get("origin_y_mm", 20.0)) if regmark else 20.0,
            quadregmarks=bool(regmark.get("quad", False)) if regmark else False,
        )
        _emit({"event": "pass_done", "index": index})

    return True


def main() -> int:
    try:
        job = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        _emit({"event": "error", "message": f"invalid job JSON: {exc}"})
        return 1

    try:
        run_job(job)
    except Exception as exc:  # the device/driver can fail in many ways
        _emit({"event": "error", "message": str(exc)})
        return 1

    _emit({"event": "done", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
