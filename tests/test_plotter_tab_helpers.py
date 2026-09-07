"""Tests for plotter_tab.py's module-level raster-import helpers.

These are plain functions with no Qt widget/QApplication dependency (only
actually instantiating PlotterTab() would need a running QApplication), so
they're safe to unit test directly like any other pure function here.
"""

import os

import pytest

from linuxprint.gui.plotter_tab import _read_png_dpi, _render_pdf_first_page


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
