"""Parse an SVG file into millimetre polylines for the Plotter tab.

Uses svgelements (MIT license, see NOTICE in vendor/inkscape_silhouette for
the full credits list) purely for SVG parsing and curve flattening -- this
module contains no cutter-protocol code and is independent of the vendored
GPL-2.0 driver in vendor/inkscape_silhouette/.

Convention (matches common practice in hobbyist cutter/laser software):
a red stroke (#ff0000 and close variants) means "cut with the blade";
any other stroke (or a shape with no stroke at all) means "draw with the
pen". This keeps the common case -- "everything in my SVG is a cut line" --
working with zero setup, while still letting a user add pen-only guide
lines by drawing them in a different color.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from svgelements import Arc, Close, CubicBezier, Line, Move, Path, QuadraticBezier, SVG, Shape

# svgelements parses lengths as CSS pixels (96 px per inch) unless the
# document says otherwise; we only care about the physical size, so convert
# everything back to millimetres once, here, rather than propagating pixels.
PX_PER_MM = 96.0 / 25.4

# Stroke colors (case-insensitive hex, after normalization) treated as
# "cut with the blade" rather than "draw with the pen".
_CUT_COLORS = {"ff0000", "f00"}


@dataclass
class ParsedSvg:
    cut_paths: list[list[tuple[float, float]]] = field(default_factory=list)
    draw_paths: list[list[tuple[float, float]]] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0


def _is_cut_stroke(shape: Shape) -> bool:
    stroke = shape.stroke
    if stroke is None or stroke.value is None:
        return False
    hexrgb = (stroke.hexrgb or "").lstrip("#").lower()
    return hexrgb in _CUT_COLORS


def _flatten_segment(segment, points: list[tuple[float, float]], tolerance_mm: float) -> None:
    """Append the (mm) points of one path segment to points, sampling curves
    finely enough that consecutive points are within roughly tolerance_mm."""
    if isinstance(segment, Move):
        return  # handled by the caller, which starts a new polyline
    if isinstance(segment, (Line, Close)):
        if segment.end is not None:
            points.append((segment.end.x / PX_PER_MM, segment.end.y / PX_PER_MM))
        return
    if isinstance(segment, (CubicBezier, QuadraticBezier, Arc)):
        length_mm = segment.length() / PX_PER_MM
        steps = max(2, math.ceil(length_mm / max(tolerance_mm, 0.02)))
        for i in range(1, steps + 1):
            point = segment.point(i / steps)
            points.append((point.x / PX_PER_MM, point.y / PX_PER_MM))
        return
    # Unknown segment type (svgelements covers the SVG spec fully in
    # practice): fall back to its endpoint so we don't silently drop it.
    end = getattr(segment, "end", None)
    if end is not None:
        points.append((end.x / PX_PER_MM, end.y / PX_PER_MM))


def _shape_to_polylines(shape: Shape, tolerance_mm: float) -> list[list[tuple[float, float]]]:
    path = abs(Path(shape))  # absolute coordinates, in document (px) space
    polylines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for segment in path:
        if isinstance(segment, Move):
            if len(current) >= 2:
                polylines.append(current)
            start = segment.end
            current = [(start.x / PX_PER_MM, start.y / PX_PER_MM)] if start is not None else []
            continue
        _flatten_segment(segment, current, tolerance_mm)
    if len(current) >= 2:
        polylines.append(current)
    return polylines


def parse_svg(file_path: str, curve_tolerance_mm: float = 0.2) -> ParsedSvg:
    """Parse an SVG file into cut/draw polylines, in millimetres.

    curve_tolerance_mm controls how finely curves are flattened into line
    segments (smaller = smoother but more points sent to the cutter).
    """
    svg = SVG.parse(file_path)
    result = ParsedSvg()
    try:
        result.width_mm = float(svg.width) / PX_PER_MM if svg.width else 0.0
        result.height_mm = float(svg.height) / PX_PER_MM if svg.height else 0.0
    except (TypeError, ValueError):
        pass

    for element in svg.elements():
        if not isinstance(element, Shape):
            continue
        polylines = _shape_to_polylines(element, curve_tolerance_mm)
        if not polylines:
            continue
        if _is_cut_stroke(element):
            result.cut_paths.extend(polylines)
        else:
            result.draw_paths.extend(polylines)
    return result
