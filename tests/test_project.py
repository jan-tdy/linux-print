import base64

import pytest

from linuxprint.plotter.project import Project, ProjectBackgroundImage, load_project, save_project


def test_save_and_load_project_round_trips_paths_and_settings(tmp_path):
    project = Project(
        cut_paths=[[(0.0, 0.0), (10.0, 10.0)]],
        draw_paths=[[(1.0, 1.0), (2.0, 2.0)]],
        media_preset="cameo_12x12",
        pressure=25,
        speed=8,
        pen_pressure=15,
        regmark_enabled=True,
        regmark_quad=True,
        roll_width_mm=210.0,
    )
    path = str(tmp_path / "project.jpcp")
    save_project(project, path)

    loaded = load_project(path)
    assert loaded.cut_paths == [[(0.0, 0.0), (10.0, 10.0)]]
    assert loaded.draw_paths == [[(1.0, 1.0), (2.0, 2.0)]]
    assert loaded.media_preset == "cameo_12x12"
    assert loaded.pressure == 25
    assert loaded.speed == 8
    assert loaded.pen_pressure == 15
    assert loaded.regmark_enabled is True
    assert loaded.regmark_quad is True
    assert loaded.roll_width_mm == 210.0
    assert loaded.background is None


def test_save_and_load_project_round_trips_embedded_background(tmp_path):
    raw_bytes = b"not a real PNG, just some bytes to round-trip"
    project = Project(background=ProjectBackgroundImage(dpi=150.0, data_base64=base64.b64encode(raw_bytes).decode()))
    path = str(tmp_path / "with_background.jpcp")
    save_project(project, path)

    loaded = load_project(path)
    assert loaded.background is not None
    assert loaded.background.dpi == 150.0
    assert base64.b64decode(loaded.background.data_base64) == raw_bytes


def test_load_project_rejects_a_file_that_is_not_a_project(tmp_path):
    path = tmp_path / "not_a_project.jpcp"
    path.write_text('{"format": "something-else"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Not a Jadiv Print Center project"):
        load_project(str(path))


def test_load_project_rejects_a_zero_background_dpi(tmp_path):
    # A background dpi of 0 would otherwise reach PlotterTab's preview
    # scaling (PREVIEW_PX_PER_MM / (background_dpi / 25.4)) and raise
    # ZeroDivisionError -- reject it at load time instead, like
    # plotter_tab._read_png_dpi already does for a plain PNG import.
    import json

    path = tmp_path / "zero_dpi.jpcp"
    path.write_text(
        json.dumps(
            {
                "format": "jadiv-print-center-project",
                "version": 1,
                "background": {"dpi": 0.0, "data_base64": "AAAA"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid background DPI"):
        load_project(str(path))


def test_load_project_rejects_a_background_missing_required_fields(tmp_path):
    import json

    path = tmp_path / "incomplete_background.jpcp"
    path.write_text(
        json.dumps({"format": "jadiv-print-center-project", "version": 1, "background": {"dpi": 96.0}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid background image"):
        load_project(str(path))
