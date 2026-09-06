import pytest

from linuxprint.plotter.svg_import import parse_svg

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <path d="M10,10 L50,10 L50,50 Z" stroke="#ff0000" fill="none" stroke-width="1"/>
  <circle cx="70" cy="70" r="10" stroke="#000000" fill="none"/>
  <path d="M10,90 C 20,80 40,80 50,90" stroke="red" fill="none"/>
  <line x1="0" y1="0" x2="5" y2="5" fill="none"/>
</svg>
"""


def _write_sample(tmp_path):
    path = tmp_path / "sample.svg"
    path.write_text(SAMPLE_SVG, encoding="utf-8")
    return str(path)


def test_parse_svg_classifies_red_stroke_as_cut(tmp_path):
    result = parse_svg(_write_sample(tmp_path))
    assert len(result.cut_paths) == 2  # the red rectangle-ish path and the red curve
    assert len(result.draw_paths) == 2  # the black circle and the strokeless line


def test_parse_svg_converts_units_to_millimetres(tmp_path):
    result = parse_svg(_write_sample(tmp_path))
    rect_path = min(result.cut_paths, key=len)
    # First point of the "M10,10 L50,10 L50,50 Z" path should land at (10, 10) mm.
    x, y = rect_path[0]
    assert x == pytest.approx(10.0, abs=0.01)
    assert y == pytest.approx(10.0, abs=0.01)
    assert result.width_mm == pytest.approx(100.0, abs=0.01)
    assert result.height_mm == pytest.approx(100.0, abs=0.01)


def test_parse_svg_flattens_curves_into_multiple_points(tmp_path):
    result = parse_svg(_write_sample(tmp_path))
    curve_path = max(result.cut_paths, key=len)
    assert len(curve_path) > 5  # a curve, not a single line segment


def test_parse_svg_finer_tolerance_yields_more_points(tmp_path):
    coarse = parse_svg(_write_sample(tmp_path), curve_tolerance_mm=2.0)
    fine = parse_svg(_write_sample(tmp_path), curve_tolerance_mm=0.05)
    coarse_curve = max(coarse.cut_paths, key=len)
    fine_curve = max(fine.cut_paths, key=len)
    assert len(fine_curve) > len(coarse_curve)
