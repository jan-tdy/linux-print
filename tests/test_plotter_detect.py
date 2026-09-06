from unittest import mock

import usb.core

from linuxprint.plotter import detect


def test_detect_cameo_reports_missing_backend_gracefully():
    with mock.patch("usb.core.find", side_effect=usb.core.NoBackendError()):
        status = detect.detect_cameo()
    assert status.connected is False
    assert "libusb" in status.error


def test_detect_cameo_finds_known_device():
    fake_device = mock.Mock(idProduct=0x1140)

    def fake_find(idVendor=None, **kwargs):
        return fake_device if idVendor == detect.VENDOR_ID_GRAPHTEC else None

    with mock.patch("usb.core.find", side_effect=fake_find):
        status = detect.detect_cameo()
    assert status.connected is True
    assert status.name == "Silhouette Cameo 5"


def test_detect_cameo_no_device_found():
    with mock.patch("usb.core.find", return_value=None):
        status = detect.detect_cameo()
    assert status.connected is False
    assert status.error == ""


def test_detect_cameo_unrecognised_product_id():
    fake_device = mock.Mock(idProduct=0x9999)

    def fake_find(idVendor=None, **kwargs):
        return fake_device if idVendor == detect.VENDOR_ID_GRAPHTEC else None

    with mock.patch("usb.core.find", side_effect=fake_find):
        status = detect.detect_cameo()
    assert status.connected is True
    assert "Neznáme" in status.name
