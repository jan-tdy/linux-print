import xml.etree.ElementTree as ET

import pytest
from defusedxml.common import DefusedXmlException

from linuxprint.plotter.job import RegmarkSettings
from linuxprint.plotter.regmarks import MARK_SIZE_MM, merge_svg_with_regmarks, regmark_points_mm

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="300mm" viewBox="0 0 300 300">
  <path d="M10,10 L50,10" stroke="#ff0000" fill="none"/>
</svg>
"""


def test_regmark_points_three_marks_by_default():
    settings = RegmarkSettings(enabled=True, origin_x_mm=15, origin_y_mm=20, width_mm=180, length_mm=230)
    points = regmark_points_mm(settings)
    assert points == [(15, 20), (195, 20), (15, 250)]


def test_regmark_points_quad_adds_fourth_mark():
    settings = RegmarkSettings(
        enabled=True, origin_x_mm=15, origin_y_mm=20, width_mm=180, length_mm=230, quad=True
    )
    points = regmark_points_mm(settings)
    assert len(points) == 4
    assert points[3] == (195, 250)


def test_merge_svg_with_regmarks_appends_expected_rects(tmp_path):
    # SAMPLE_SVG's viewBox="0 0 300 300" over a width/height of "300mm" means
    # 1 user unit == 1mm here, so the expected coordinates below happen to
    # equal the mm inputs -- see test_merge_svg_with_regmarks_scales_for_mismatched_viewbox
    # for a case where the viewBox actually rescales things.
    svg_path = tmp_path / "sample.svg"
    svg_path.write_text(SAMPLE_SVG, encoding="utf-8")

    settings = RegmarkSettings(enabled=True, origin_x_mm=15.0, origin_y_mm=20.0, width_mm=180.0, length_mm=230.0)
    merged_path = merge_svg_with_regmarks(str(svg_path), settings)

    tree = ET.parse(merged_path)
    rects = tree.getroot().findall("{http://www.w3.org/2000/svg}rect")
    assert len(rects) == 3
    first = rects[0]
    assert float(first.get("x")) == pytest.approx(15.0)
    assert float(first.get("y")) == pytest.approx(20.0)
    assert float(first.get("width")) == pytest.approx(MARK_SIZE_MM)
    assert first.get("fill") == "#000000"
    # Plain numbers, not CSS lengths -- unit suffixes on child elements
    # ignore the ancestor viewBox and would land in the wrong place.
    assert "mm" not in first.get("x")

    # original content must still be present
    paths = tree.getroot().findall("{http://www.w3.org/2000/svg}path")
    assert len(paths) == 1


def test_merge_svg_with_regmarks_scales_for_mismatched_viewbox(tmp_path):
    # A 100mm-wide page whose viewBox uses 1000 user units per side (1 user
    # unit == 0.1mm) -- a real-world case (e.g. Inkscape's default 96 DPI
    # document with a viewBox in a different unit) where naively writing
    # "15mm" would land 10x too far right/down.
    svg_path = tmp_path / "scaled.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 1000 1000"><path d="M10,10 L50,10" stroke="#ff0000" fill="none"/></svg>',
        encoding="utf-8",
    )

    settings = RegmarkSettings(enabled=True, origin_x_mm=15.0, origin_y_mm=20.0, width_mm=60.0, length_mm=70.0)
    merged_path = merge_svg_with_regmarks(str(svg_path), settings)

    tree = ET.parse(merged_path)
    rects = tree.getroot().findall("{http://www.w3.org/2000/svg}rect")
    first = rects[0]
    assert float(first.get("x")) == pytest.approx(150.0)
    assert float(first.get("y")) == pytest.approx(200.0)
    assert float(first.get("width")) == pytest.approx(MARK_SIZE_MM * 10)


def test_merge_svg_with_regmarks_applies_preserve_aspect_ratio_centering(tmp_path):
    # A 200mm x 100mm (2:1) page with a square 100x100 viewBox: the default
    # preserveAspectRatio="xMidYMid meet" uniformly scales the viewBox to
    # fit the *shorter* dimension (height) and centers it horizontally,
    # adding an X offset this transform must account for -- not just a
    # per-axis scale factor. The physical center of the page (100mm, 50mm)
    # must land at the viewBox's own center (50, 50).
    svg_path = tmp_path / "letterboxed.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm" '
        'viewBox="0 0 100 100"><path d="M10,10 L50,10" stroke="#ff0000" fill="none"/></svg>',
        encoding="utf-8",
    )

    settings = RegmarkSettings(enabled=True, origin_x_mm=100.0, origin_y_mm=50.0, width_mm=1.0, length_mm=1.0)
    merged_path = merge_svg_with_regmarks(str(svg_path), settings)

    tree = ET.parse(merged_path)
    rects = tree.getroot().findall("{http://www.w3.org/2000/svg}rect")
    first = rects[0]
    assert float(first.get("x")) == pytest.approx(50.0, abs=1e-3)
    assert float(first.get("y")) == pytest.approx(50.0, abs=1e-3)
    # The page's 100mm height maps 1:1 onto the viewBox's 100 user units (the
    # "meet" scale is uniform across both axes), so the mark's physical 5mm
    # size is unchanged here -- this test is about the centering offset, not
    # a scale factor; test_merge_svg_with_regmarks_scales_for_mismatched_viewbox
    # covers a real scale change.
    assert float(first.get("width")) == pytest.approx(MARK_SIZE_MM, abs=1e-3)


def test_merge_svg_with_regmarks_rejects_xxe(tmp_path):
    svg_path = tmp_path / "malicious.svg"
    svg_path.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm">'
        "<title>&xxe;</title></svg>",
        encoding="utf-8",
    )
    settings = RegmarkSettings(enabled=True)
    with pytest.raises(DefusedXmlException):
        merge_svg_with_regmarks(str(svg_path), settings)
