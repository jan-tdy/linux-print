"""Save/load a .jpcp (Jadiv Print Center Project) file: a self-contained
JSON snapshot of a Plotter tab session (cut/draw paths, tool settings, and
an optional embedded background raster), so work in progress can be closed
and reopened without re-importing the original SVG/PNG/PDF.

Plain JSON with a base64-embedded background image, not a binary format --
easy to inspect/diff and dependency-free to read/write (no extra library
beyond the standard library's json/base64, both already MIT-compatible).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

PROJECT_FORMAT = "jadiv-print-center-project"
PROJECT_VERSION = 1


@dataclass
class ProjectBackgroundImage:
    dpi: float
    data_base64: str


@dataclass
class Project:
    cut_paths: list[list[tuple[float, float]]] = field(default_factory=list)
    draw_paths: list[list[tuple[float, float]]] = field(default_factory=list)
    media_preset: str = "A4"
    pressure: int = 27
    speed: int = 10
    pen_pressure: int = 18
    regmark_enabled: bool = False
    regmark_quad: bool = False
    roll_width_mm: float = 304.8
    background: ProjectBackgroundImage | None = None


def save_project(project: Project, file_path: str) -> None:
    data = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "cut_paths": [[list(point) for point in path] for path in project.cut_paths],
        "draw_paths": [[list(point) for point in path] for path in project.draw_paths],
        "media_preset": project.media_preset,
        "pressure": project.pressure,
        "speed": project.speed,
        "pen_pressure": project.pen_pressure,
        "regmark_enabled": project.regmark_enabled,
        "regmark_quad": project.regmark_quad,
        "roll_width_mm": project.roll_width_mm,
        "background": (
            {"dpi": project.background.dpi, "data_base64": project.background.data_base64}
            if project.background is not None
            else None
        ),
    }
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def load_project(file_path: str) -> Project:
    with open(file_path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
        raise ValueError(f"Not a Jadiv Print Center project file: {file_path}")

    background_data = data.get("background")
    background = (
        ProjectBackgroundImage(dpi=float(background_data["dpi"]), data_base64=background_data["data_base64"])
        if background_data
        else None
    )
    return Project(
        cut_paths=[[tuple(point) for point in path] for path in data.get("cut_paths", [])],
        draw_paths=[[tuple(point) for point in path] for path in data.get("draw_paths", [])],
        media_preset=data.get("media_preset", "A4"),
        pressure=int(data.get("pressure", 27)),
        speed=int(data.get("speed", 10)),
        pen_pressure=int(data.get("pen_pressure", 18)),
        regmark_enabled=bool(data.get("regmark_enabled", False)),
        regmark_quad=bool(data.get("regmark_quad", False)),
        roll_width_mm=float(data.get("roll_width_mm", 304.8)),
        background=background,
    )


def encode_background_file(path: str) -> str:
    """Read a raster file from disk and base64-encode it for embedding."""
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def decode_background_to_file(data_base64: str, out_path: str) -> None:
    """Decode a base64-embedded background image to a file on disk."""
    with open(out_path, "wb") as fh:
        fh.write(base64.b64decode(data_base64))
