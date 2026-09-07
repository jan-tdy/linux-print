"""Tests for plotter_tab.py's module-level raster-import and shape helpers.

These are plain functions with no Qt widget/QApplication dependency (only
actually instantiating PlotterTab() would need a running QApplication), so
they're safe to unit test directly like any other pure function here.
_shape_outline_points only touches QPointF, a plain value type that (unlike
QFont/QPainterPath.addText, used for the text tool) doesn't need a
QGuiApplication either.
"""

import os

import pytest
from PyQt6.QtCore import QPointF

from linuxprint.gui.plotter_tab import (
    _read_png_dpi,
    _regmark_settings_for_canvas,
    _render_pdf_first_page,
    _shape_outline_points,
)
from linuxprint.plotter.regmarks import MARK_SIZE_MM, merge_raster_with_regmarks


def test_read_png_dpi_returns_declared_value(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    png_path = tmp_path / "300dpi.png"
    Image.new("RGB", (10, 10), "white").save(png_path, dpi=(300, 300))

    # PNG stores DPI as pixels-per-meter internally, so round-tripping
    # 300 loses a hair of precision (e.g. 299.9994) -- approx accounts for that.
    assert _read_png_dpi(str(png_path)) == pytest.approx(300.0, abs=0.01)


def test_read_png_dpi_defaults_to_96_without_declared_dpi(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    png_path = tmp_path / "no_dpi.png"
    Image.new("RGB", (10, 10), "white").save(png_path)

    assert _read_png_dpi(str(png_path)) == 96.0


def test_read_png_dpi_defaults_to_96_without_pillow(tmp_path, monkeypatch):
    # _read_png_dpi must degrade gracefully (not raise) when Pillow isn't
    # installed at all -- simulate that by making the import fail.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("simulated missing Pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _read_png_dpi(str(tmp_path / "whatever.png")) == 96.0


def test_read_png_dpi_rejects_a_zero_pixels_per_unit_phys_chunk(tmp_path, monkeypatch):
    # A malformed pHYs chunk (unit=meters, 0 pixels-per-unit on both axes)
    # would make Pillow report dpi=(0.0, 0.0) -- accepting that verbatim
    # would later divide by zero in _render_preview's DPI-based scaling.
    pytest.importorskip("PIL")
    from PIL import Image

    def fake_open(path):
        class _FakeImage:
            info = {"dpi": (0.0, 0.0)}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _FakeImage()

    monkeypatch.setattr(Image, "open", fake_open)
    assert _read_png_dpi(str(tmp_path / "degenerate.png")) == 96.0


def test_render_pdf_first_page_produces_a_png(tmp_path):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from PIL import Image

    pdf_path = tmp_path / "page.pdf"
    Image.new("RGB", (300, 150), "blue").save(pdf_path, "PDF")

    out_path = _render_pdf_first_page(str(pdf_path), dpi=150.0)
    try:
        result = Image.open(out_path)
        assert result.format == "PNG"
        # 300x150 points at 150dpi (PDF's native unit is 72 points/inch).
        assert result.size == (625, 313)
        # Preserved so a later print/regmark step agrees on physical scale.
        assert result.info.get("dpi") == pytest.approx((150.0, 150.0), abs=0.05)
    finally:
        os.unlink(out_path)


def test_shape_outline_points_square_forces_equal_sides():
    points = _shape_outline_points("square", QPointF(0, 0), QPointF(10, 30))
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert max(xs) - min(xs) == pytest.approx(30.0)
    assert max(ys) - min(ys) == pytest.approx(30.0)


def test_shape_outline_points_rectangle_keeps_free_aspect_ratio():
    points = _shape_outline_points("rectangle", QPointF(0, 0), QPointF(10, 30))
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert max(xs) - min(xs) == pytest.approx(10.0)
    assert max(ys) - min(ys) == pytest.approx(30.0)


def test_shape_outline_points_circle_is_closed_and_centered():
    points = _shape_outline_points("circle", QPointF(0, 0), QPointF(20, 20))
    assert points[0] == pytest.approx(points[-1])  # closed contour
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert (min(xs) + max(xs)) / 2 == pytest.approx(10.0, abs=0.01)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(10.0, abs=0.01)


def test_shape_outline_points_triangle_has_three_corners():
    points = _shape_outline_points("triangle", QPointF(0, 0), QPointF(10, 20))
    assert points[0] == points[-1]  # closed contour
    assert len(points) == 4  # 3 corners + closing point


def test_shape_outline_points_returns_empty_for_a_zero_size_drag():
    assert _shape_outline_points("square", QPointF(5, 5), QPointF(5, 5)) == []


def test_regmark_settings_for_canvas_scales_down_for_a_small_image():
    # Regression test for a real bug report: a 600x600px PNG at 96 DPI is
    # 159x159mm, well under the *fixed* default RegmarkSettings layout
    # (marks out to 195x250mm), which used to make merge_raster_with_regmarks
    # raise "too small" on perfectly normal small artwork. The layout must
    # instead scale down to fit whatever canvas is actually being printed.
    settings = _regmark_settings_for_canvas(159.0, 159.0, quad=False)
    assert settings.enabled is True
    assert settings.width_mm < 159.0
    assert settings.length_mm < 159.0


def test_regmark_settings_for_canvas_never_shrinks_below_one_mark():
    settings = _regmark_settings_for_canvas(10.0, 10.0, quad=True)
    assert settings.width_mm >= MARK_SIZE_MM
    assert settings.length_mm >= MARK_SIZE_MM


def test_small_png_that_used_to_be_rejected_now_merges_successfully(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    png_path = tmp_path / "small600.png"
    Image.new("RGB", (600, 600), "white").save(png_path, dpi=(96, 96))

    settings = _regmark_settings_for_canvas(159.0, 159.0, quad=False)
    out_path = merge_raster_with_regmarks(str(png_path), settings, dpi=96.0)
    assert os.path.exists(out_path)
