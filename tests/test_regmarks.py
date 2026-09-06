import xml.etree.ElementTree as ET

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
    svg_path = tmp_path / "sample.svg"
    svg_path.write_text(SAMPLE_SVG, encoding="utf-8")

    settings = RegmarkSettings(enabled=True, origin_x_mm=15.0, origin_y_mm=20.0, width_mm=180.0, length_mm=230.0)
    merged_path = merge_svg_with_regmarks(str(svg_path), settings)

    tree = ET.parse(merged_path)
    rects = tree.getroot().findall("{http://www.w3.org/2000/svg}rect")
    assert len(rects) == 3
    first = rects[0]
    assert first.get("x") == "15.0mm"
    assert first.get("y") == "20.0mm"
    assert first.get("width") == f"{MARK_SIZE_MM}mm"
    assert first.get("fill") == "#000000"

    # original content must still be present
    paths = tree.getroot().findall("{http://www.w3.org/2000/svg}path")
    assert len(paths) == 1
