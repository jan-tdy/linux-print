import pytest

from linuxprint.plotter.svg_import import ParsedSvg, export_svg, parse_svg

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


def test_export_svg_round_trips_through_parse_svg(tmp_path):
    original = ParsedSvg(
        cut_paths=[[(10.0, 10.0), (50.0, 10.0), (50.0, 50.0)]],
        draw_paths=[[(0.0, 0.0), (5.0, 5.0)]],
        width_mm=100.0,
        height_mm=100.0,
    )
    out_path = str(tmp_path / "exported.svg")
    export_svg(original, out_path)

    reparsed = parse_svg(out_path)
    assert len(reparsed.cut_paths) == 1
    assert len(reparsed.draw_paths) == 1
    for (x0, y0), (x1, y1) in zip(reparsed.cut_paths[0], original.cut_paths[0]):
        assert x0 == pytest.approx(x1, abs=0.01)
        assert y0 == pytest.approx(y1, abs=0.01)


def test_export_svg_falls_back_to_bounding_box_without_declared_size(tmp_path):
    parsed = ParsedSvg(cut_paths=[[(0.0, 0.0), (30.0, 40.0)]])
    out_path = str(tmp_path / "no_size.svg")
    export_svg(parsed, out_path)

    reparsed = parse_svg(out_path)
    assert reparsed.width_mm == pytest.approx(40.0, abs=0.01)  # 30 + 10mm margin
    assert reparsed.height_mm == pytest.approx(50.0, abs=0.01)  # 40 + 10mm margin


def test_export_svg_handles_negative_coordinates_without_clipping(tmp_path):
    # A panned drawing canvas can produce negative scene coordinates (see
    # plotter_tab.py's _DrawingView) -- a "0 0 ..." viewBox would silently
    # clip anything left of/above the origin instead of exporting it.
    parsed = ParsedSvg(cut_paths=[[(-20.0, -30.0), (10.0, 5.0)]])
    out_path = str(tmp_path / "negative.svg")
    export_svg(parsed, out_path)

    reparsed = parse_svg(out_path)
    assert len(reparsed.cut_paths) == 1
    xs = [x for x, _ in reparsed.cut_paths[0]]
    ys = [y for _, y in reparsed.cut_paths[0]]
    # The negative-coordinate point must round-trip (shifted by a constant
    # offset so everything lands >=0 with a 10mm margin), not get clipped
    # to 0 -- the *shape* of the path (its extent) must be preserved.
    assert max(xs) - min(xs) == pytest.approx(30.0, abs=0.01)  # 10 - (-20)
    assert max(ys) - min(ys) == pytest.approx(35.0, abs=0.01)  # 5 - (-30)
    assert min(xs) == pytest.approx(10.0, abs=0.01)  # shifted to sit at the margin
    assert min(ys) == pytest.approx(10.0, abs=0.01)
