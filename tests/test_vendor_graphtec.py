"""Smoke tests for the vendored (GPL-2.0) Graphtec.py driver: confirms our
minimal modifications (relative imports, the USB-only BLETransport stub)
still leave the module importable and its pure helper functions intact,
without touching any real USB hardware.

See linuxprint/plotter/vendor/inkscape_silhouette/NOTICE.md for what this
file is and why it lives in this repository.
"""

from linuxprint.plotter.vendor.inkscape_silhouette import Graphtec


def test_mm_and_inch_conversion_round_trip():
    # Native resolution is 0.05mm per the file's own header comment.
    assert Graphtec._mm_2_SU(1.0) == round(1.0 / 0.05)
    assert Graphtec._inch_2_SU(1.0) == round(25.4 / 0.05)


def test_device_table_includes_cameo5_family():
    names = {entry["name"] for entry in Graphtec.DEVICE}
    for expected in (
        "Silhouette_Cameo4",
        "Silhouette_Cameo5",
        "Silhouette_Cameo5_Plus",
    ):
        assert expected in names, f"{expected} missing from vendored DEVICE table: {sorted(names)}"


def test_cameo_mats_has_common_presets():
    assert "cameo_12x12" in Graphtec.CAMEO_MATS
    assert "no_mat" in Graphtec.CAMEO_MATS


def test_to_bytes_and_delimit_commands():
    assert Graphtec.to_bytes("AB") == b"AB"
    assert Graphtec.to_bytes(b"AB") == b"AB"
    assert Graphtec.delimit_commands("FOO") == b"FOO" + Graphtec.CMD_ETX
    assert Graphtec.delimit_commands(["A", "B"]) == b"A" + Graphtec.CMD_ETX + b"B" + Graphtec.CMD_ETX


def test_ble_transport_stub_raises_clearly():
    from linuxprint.plotter.vendor.inkscape_silhouette.BLETransport import BLETransport

    try:
        BLETransport.connect()
    except RuntimeError as exc:
        assert "USB" in str(exc)
    else:
        raise AssertionError("expected RuntimeError from the BLE stub")
