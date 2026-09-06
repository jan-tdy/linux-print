import pytest

from linuxprint.plotter.job import MEDIA_PRESETS, PlotJob, RegmarkSettings, ToolPass


def test_tool_pass_rejects_unknown_tool():
    with pytest.raises(ValueError):
        ToolPass(tool="laser", paths=[[(0, 0), (1, 1)]]).to_json()


def test_tool_pass_to_json_shape():
    step = ToolPass(tool="blade", paths=[[(0, 0), (1, 2)]], speed=7, pressure=20)
    data = step.to_json()
    assert data["tool"] == "blade"
    assert data["speed"] == 7
    assert data["pressure"] == 20
    assert data["paths"] == [[[0, 0], [1, 2]]]


def test_regmark_settings_disabled_serializes_to_none():
    assert RegmarkSettings(enabled=False).to_json() is None


def test_regmark_settings_enabled_serializes_fields():
    data = RegmarkSettings(enabled=True, width_mm=100.0, quad=True).to_json()
    assert data["width_mm"] == 100.0
    assert data["quad"] is True


def test_plot_job_resolves_known_media_preset():
    job = PlotJob(media_preset="cameo_12x12")
    cuttingmat, width, height = job.resolved_media()
    assert cuttingmat == "cameo_12x12"
    assert width == MEDIA_PRESETS["cameo_12x12"][1]
    assert height == MEDIA_PRESETS["cameo_12x12"][2]


def test_plot_job_falls_back_to_default_for_unknown_preset():
    job = PlotJob(media_preset="does-not-exist")
    cuttingmat, width, height = job.resolved_media()
    assert (cuttingmat, width, height) == MEDIA_PRESETS["A4"]


def test_plot_job_explicit_size_overrides_preset():
    job = PlotJob(media_preset="A4", media_width_mm=123.0, media_height_mm=456.0)
    _, width, height = job.resolved_media()
    assert width == 123.0
    assert height == 456.0


def test_plot_job_to_json_includes_passes_and_media():
    job = PlotJob(
        passes=[ToolPass(tool="pen", paths=[[(0, 0), (1, 1)]])],
        media_preset="cameo_12x12",
        force_hardware="Silhouette_Cameo5",
    )
    data = job.to_json()
    assert data["force_hardware"] == "Silhouette_Cameo5"
    assert data["cuttingmat"] == "cameo_12x12"
    assert len(data["passes"]) == 1
    assert data["regmark"] is None
