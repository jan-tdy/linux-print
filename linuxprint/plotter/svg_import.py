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


def export_svg(parsed: ParsedSvg, file_path: str, cut_color: str = "#ff0000", draw_color: str = "#000000") -> None:
    """Write cut/draw polylines back out as a standalone SVG file, using the
    same "red stroke == cut" convention parse_svg reads -- so a file written
    here round-trips through parse_svg.

    1 user unit == 1mm (viewBox spans the same numeric range as the mm
    width/height), matching regmarks.merge_svg_with_regmarks's convention;
    child <path> coordinates are plain numbers, not CSS lengths, since a
    unit suffix on a child element ignores the root's viewBox scaling.
    """
    # parse_svg reads a <path>'s "d" numbers directly as mm (divided by
    # PX_PER_MM), with no viewBox-origin compensation of its own -- unlike
    # regmarks.py's mark placement, which does apply a full inverse
    # viewBox transform when merging into an *externally supplied* SVG.
    # So a nonzero viewBox origin here would silently shift every point on
    # re-import; instead, keep viewBox at "0 0 W H" and translate the path
    # data itself so panning the drawing canvas to negative scene
    # coordinates (see plotter_tab.py's _DrawingView) doesn't get clipped.
    all_points = [pt for path in (*parsed.cut_paths, *parsed.draw_paths) for pt in path]
    offset_x, offset_y = 0.0, 0.0
    if parsed.width_mm > 0 and parsed.height_mm > 0:
        width_mm, height_mm = parsed.width_mm, parsed.height_mm
    elif all_points:
        min_x = min(x for x, _ in all_points)
        min_y = min(y for _, y in all_points)
        # Only shift when a coordinate actually goes negative -- otherwise
        # the common case (everything already >=0) keeps its old, simpler
        # "just add a margin past the far edge" output unchanged.
        offset_x = min_x - 10.0 if min_x < 0 else 0.0
        offset_y = min_y - 10.0 if min_y < 0 else 0.0
        width_mm = max(x for x, _ in all_points) + 10.0 - offset_x
        height_mm = max(y for _, y in all_points) + 10.0 - offset_y
    else:
        width_mm, height_mm = 210.0, 297.0

    def _path_element(path: list[tuple[float, float]], color: str) -> str:
        d = "M " + " L ".join(f"{x - offset_x:.3f},{y - offset_y:.3f}" for x, y in path)
        return f'<path d="{d}" stroke="{color}" fill="none" stroke-width="0.3"/>'

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.3f}mm" '
        f'height="{height_mm:.3f}mm" viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">'
    ]
    for path in parsed.cut_paths:
        if len(path) >= 2:
            lines.append(_path_element(path, cut_color))
    for path in parsed.draw_paths:
        if len(path) >= 2:
            lines.append(_path_element(path, draw_color))
    lines.append("</svg>")

    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
