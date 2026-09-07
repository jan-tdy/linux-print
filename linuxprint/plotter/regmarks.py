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

import io
import os
import tempfile
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import fromstring as safe_fromstring
from svgelements import SVG, Matrix, Point

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


def _inverse_viewbox_transform(svg_content: bytes) -> Matrix:
    """Return the transform that maps a point in the document's physical
    CSS-pixel space (its width/height attributes, at 96 user units per
    inch, with no viewBox involved) into the *user units* its root <svg>
    element draws direct children in.

    A unit-suffixed length like "15mm" on a child element is an absolute
    CSS length -- it is NOT scaled by an ancestor's viewBox the way a plain
    unitless number is. So when the root element has a viewBox (e.g.
    width="300mm" height="300mm" viewBox="0 0 300 300", where 1 user unit
    is meant to equal 1mm), writing x="15mm" ends up ~3.78x too far (96/25.4
    user units per intended user unit) instead of landing at the intended
    15mm. Converting to plain numbers in the root's actual user-unit space
    avoids that.

    svgelements' own `viewbox_transform` already implements the SVG spec's
    viewBox-to-viewport mapping -- including preserveAspectRatio's default
    uniform "meet" scale and xMidYMid centering offset for a document whose
    viewBox aspect ratio doesn't match its physical width/height -- so its
    inverse is used here rather than hand-rolling (and getting wrong) that
    same math. With no viewBox at all, svgelements reports an identity
    transform, which correctly leaves CSS pixels as-is.

    Takes already-read bytes rather than a path: svgelements' own parser
    isn't hardened against XXE, so it must run against the exact same
    content defusedxml already validated, not re-read the file from disk a
    second time (which would both risk a TOCTOU swap of validated content
    for a malicious payload, and could silently compute the transform from
    different content than what's actually written out).
    """
    svg = SVG.parse(io.BytesIO(svg_content))
    matrix = Matrix(svg.viewbox_transform)
    matrix.inverse()
    return matrix


def _mm_to_user_units(inverse_transform: Matrix, x_mm: float, y_mm: float) -> tuple[float, float]:
    point = Point(x_mm * _USER_UNITS_PER_MM, y_mm * _USER_UNITS_PER_MM) * inverse_transform
    return (point.x, point.y)


def merge_svg_with_regmarks(svg_path: str, settings: RegmarkSettings) -> str:
    """Copy svg_path to a temp file with the registration squares appended
    as extra <rect> elements, ready to print. Returns the temp file path;
    the caller is responsible for deleting it once printing is done."""
    # Read the file exactly once and validate that one snapshot with
    # defusedxml (XXE / entity-expansion hardening) -- both the output tree
    # and the viewBox transform are then derived from these same bytes, so
    # there's no window for the file to change between two separate reads
    # (which could smuggle an unvalidated payload into svgelements' own
    # unhardened parser, or compute the transform from different content
    # than what actually gets written out).
    with open(svg_path, "rb") as f:
        svg_content = f.read()

    ET.register_namespace("", _SVG_NS)
    root = safe_fromstring(svg_content)
    tree = ET.ElementTree(root)

    inverse_transform = _inverse_viewbox_transform(svg_content)
    for x_mm, y_mm in regmark_points_mm(settings):
        x0, y0 = _mm_to_user_units(inverse_transform, x_mm, y_mm)
        # Transform a corner-to-corner vector rather than scaling MARK_SIZE_MM
        # directly: preserveAspectRatio can scale x/y unevenly (or offset the
        # origin), so only the *difference* between two transformed points
        # gives the mark's correct width/height in user units.
        x1, y1 = _mm_to_user_units(inverse_transform, x_mm + MARK_SIZE_MM, y_mm + MARK_SIZE_MM)
        rect = ET.SubElement(root, f"{{{_SVG_NS}}}rect")
        rect.set("x", f"{x0:.4f}")
        rect.set("y", f"{y0:.4f}")
        rect.set("width", f"{abs(x1 - x0):.4f}")
        rect.set("height", f"{abs(y1 - y0):.4f}")
        rect.set("fill", "#000000")

    fd, out_path = tempfile.mkstemp(suffix=".svg", prefix="jadiv-print-center-regmarks-")
    os.close(fd)
    tree.write(out_path, xml_declaration=True, encoding="utf-8")
    return out_path


def merge_raster_with_regmarks(image_path: str, settings: RegmarkSettings, dpi: float = 96.0) -> str:
    """Composite the registration squares directly onto a raster (PNG)
    image, for print-and-cut when the artwork came from a PNG/PDF import
    rather than an SVG (a raster image has no XML tree to inject <rect>
    elements into, so this draws pixels instead).

    `dpi` is the image's assumed physical resolution in pixels per inch,
    used to convert the mm positions everything else in this app works in
    into pixel coordinates -- pass the value the image was actually
    produced at (a PNG's own declared DPI when it has one, or the DPI a
    PDF page was rendered at) so marks land at the intended physical
    position on the printed sheet.

    Requires Pillow (an optional dependency of the Plotter tab's PNG/PDF
    import feature, not needed for the SVG-only workflow) -- imported here,
    not at module load, so importing this module doesn't require Pillow
    just to merge marks into an SVG.

    Raises ValueError if the image is too small to fit every mark at its
    configured position: Pillow's ImageDraw silently clips a rectangle that
    falls (partly) outside the image instead of raising, which would
    otherwise mean a mark quietly missing from the printed sheet -- and the
    cutter's optical search failing to find it -- with no indication why.
    """
    from PIL import Image, ImageDraw

    px_per_mm = dpi / 25.4
    with Image.open(image_path) as img:
        img = img.convert("RGB")

        points_mm = regmark_points_mm(settings)
        required_width_mm = max(x for x, _ in points_mm) + MARK_SIZE_MM
        required_height_mm = max(y for _, y in points_mm) + MARK_SIZE_MM
        if img.width < required_width_mm * px_per_mm or img.height < required_height_mm * px_per_mm:
            raise ValueError(
                f"Image ({img.width}x{img.height} px at {dpi:.0f} DPI, i.e. "
                f"{img.width / px_per_mm:.0f}x{img.height / px_per_mm:.0f} mm) is too small for the "
                f"registration marks (needs at least {required_width_mm:.0f}x{required_height_mm:.0f} mm) "
                "-- enlarge the media or turn off registration marks."
            )

        draw = ImageDraw.Draw(img)
        for x_mm, y_mm in points_mm:
            x0 = x_mm * px_per_mm
            y0 = y_mm * px_per_mm
            x1 = x0 + MARK_SIZE_MM * px_per_mm
            y1 = y0 + MARK_SIZE_MM * px_per_mm
            draw.rectangle([x0, y0, x1, y1], fill="#000000")

        fd, out_path = tempfile.mkstemp(suffix=".png", prefix="jadiv-print-center-regmarks-")
        os.close(fd)
        # Preserve the DPI this function's own mark placement assumed --
        # without it, CUPS would fall back to any DPI already embedded in
        # the source image (which may be a different value) or its own
        # default, printing marks at the wrong physical position/size even
        # though the pixels here are correct for the intended DPI.
        img.save(out_path, format="PNG", dpi=(dpi, dpi))
    return out_path
