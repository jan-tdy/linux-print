"""Render the 3 registration marks print-and-cut needs onto a page.

Print-and-cut works by printing a design plus 3 small solid squares at
known positions, then letting the cutter's optical sensor find those
squares (vendor/plot_cli.py passes regmark=True, regsearch=True straight
through to the vendored driver's plot(), which sends the marks-search
protocol commands -- see Graphtec.py's plot() and NOTICE.md) to correct for
any sheet misalignment before cutting.

This module only draws the marks that get printed; it has nothing to do
with the optical search itself; that lives entirely in the vendored
GPL-2.0 driver. This file is original, MIT-licensed code.

Mark placement mirrors vendor/plot_cli.py's regmark JSON fields (origin_x_mm
/ origin_y_mm / width_mm / length_mm), which are passed straight through to
the driver's automatic_regmark_test_mm_cmd(): one mark at the origin, one
`width_mm` to its right, one `length_mm` below it (an "L" layout), plus a
4th at the far corner when quad=True. The mark size (5mm solid squares) and
"Cameo/Portrait"-style square shape match widely documented Silhouette
Studio practice; it has not been hardware-verified in this sandbox (no
physical Cameo to test optical detection against) -- print a test sheet
and confirm the cutter finds the marks before relying on this for a real
cut.
"""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import parse as safe_parse
from svgelements import SVG

from .job import RegmarkSettings

MARK_SIZE_MM = 5.0
_SVG_NS = "http://www.w3.org/2000/svg"

# CSS/SVG default: 1 inch = 96 user units ("px"), 1 inch = 25.4mm. Matches
# svg_import.py's PX_PER_MM -- kept as a separate constant here since this
# module must stay independent of svg_import.py's cut/draw parsing.
_USER_UNITS_PER_MM = 96.0 / 25.4


def regmark_points_mm(settings: RegmarkSettings) -> list[tuple[float, float]]:
    """Top-left corner of each registration square, in mm from the page's
    top-left corner."""
    origin = (settings.origin_x_mm, settings.origin_y_mm)
    right = (settings.origin_x_mm + settings.width_mm, settings.origin_y_mm)
    below = (settings.origin_x_mm, settings.origin_y_mm + settings.length_mm)
    points = [origin, right, below]
    if settings.quad:
        points.append((settings.origin_x_mm + settings.width_mm, settings.origin_y_mm + settings.length_mm))
    return points


def render_regmarks_svg(settings: RegmarkSettings, page_width_mm: float, page_height_mm: float) -> str:
    """Return an SVG document (page_width_mm x page_height_mm) containing
    just the registration squares, ready to be merged under/over the design
    before printing."""
    squares = "".join(
        f'<rect x="{x:.3f}mm" y="{y:.3f}mm" width="{MARK_SIZE_MM}mm" '
        f'height="{MARK_SIZE_MM}mm" fill="#000000"/>\n'
        for x, y in regmark_points_mm(settings)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page_width_mm}mm" height="{page_height_mm}mm" '
        f'viewBox="0 0 {page_width_mm} {page_height_mm}">\n'
        f"{squares}"
        f"</svg>\n"
    )


def _mm_to_user_units_transform(svg_path: str) -> tuple[float, float, float, float]:
    """Return (origin_x, origin_y, scale_x, scale_y) to convert a millimetre
    point (measured from the page's top-left corner) into the *user units*
    the document's own root <svg> element draws its direct children in.

    A unit-suffixed length like "15mm" on a child element is an absolute
    CSS length (always 96 user units per inch) -- it is NOT scaled by an
    ancestor's viewBox the way a plain unitless number is. So when the root
    element has a viewBox (e.g. width="300mm" height="300mm"
    viewBox="0 0 300 300", where 1 user unit is meant to equal 1mm),
    writing x="15mm" ends up ~3.78x too far (96/25.4 user units per
    intended user unit) instead of landing at the intended 15mm. Converting
    to plain numbers in the root's actual user-unit space avoids that.
    """
    svg = SVG.parse(svg_path)
    viewbox = svg.viewbox
    if viewbox is not None and svg.width and svg.height:
        physical_width_mm = float(svg.width) / _USER_UNITS_PER_MM
        physical_height_mm = float(svg.height) / _USER_UNITS_PER_MM
        if physical_width_mm > 0 and physical_height_mm > 0:
            return (
                viewbox.x,
                viewbox.y,
                viewbox.width / physical_width_mm,
                viewbox.height / physical_height_mm,
            )
    # No viewBox (or no resolvable physical size): the root's user-unit
    # space is plain CSS pixels, unscaled by any viewBox.
    return (0.0, 0.0, _USER_UNITS_PER_MM, _USER_UNITS_PER_MM)


def merge_svg_with_regmarks(svg_path: str, settings: RegmarkSettings) -> str:
    """Copy svg_path to a temp file with the registration squares appended
    as extra <rect> elements, ready to print. Returns the temp file path;
    the caller is responsible for deleting it once printing is done."""
    # Reject a malicious DOCTYPE (XXE / entity expansion) via defusedxml
    # before svgelements' own (unhardened) parser ever touches the file.
    ET.register_namespace("", _SVG_NS)
    tree = safe_parse(svg_path)
    root = tree.getroot()

    origin_x, origin_y, scale_x, scale_y = _mm_to_user_units_transform(svg_path)
    for x_mm, y_mm in regmark_points_mm(settings):
        rect = ET.SubElement(root, f"{{{_SVG_NS}}}rect")
        rect.set("x", f"{origin_x + x_mm * scale_x:.4f}")
        rect.set("y", f"{origin_y + y_mm * scale_y:.4f}")
        rect.set("width", f"{MARK_SIZE_MM * scale_x:.4f}")
        rect.set("height", f"{MARK_SIZE_MM * scale_y:.4f}")
        rect.set("fill", "#000000")

    fd, out_path = tempfile.mkstemp(suffix=".svg", prefix="jadiv-print-center-regmarks-")
    os.close(fd)
    tree.write(out_path, xml_declaration=True, encoding="utf-8")
    return out_path
