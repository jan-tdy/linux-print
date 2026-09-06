"""Is a Silhouette Cameo plugged in? A quick status check for the GUI.

Deliberately independent of the vendored GPL-2.0 driver (see
vendor/inkscape_silhouette/NOTICE.md) and of vendor/plot_cli.py: spawning a
subprocess just to answer "is anything plugged in" for a status label would
be needlessly slow. USB vendor/product IDs are plain facts about a device,
not copyrightable protocol logic, so listing them here to recognise a
Cameo is fine to do directly with pyusb (MIT-compatible, BSD-3-Clause
licensed) in the main (MIT) process.
"""

from __future__ import annotations

from dataclasses import dataclass

# Vendor IDs used by Graphtec/Silhouette hardware, and the product IDs of
# the models this integration's Plotter tab targets. Kept intentionally
# small (Cameo 4/5 family) rather than mirroring the vendored driver's full
# device table -- anything it doesn't recognise here still shows up as
# "connected" with a generic name, and the actual cut still goes through
# the real driver's own (more complete) autodetection.
VENDOR_ID_GRAPHTEC = 0x0B4D
VENDOR_ID_CAMEO5ALPHA = 0x3844

KNOWN_DEVICES: dict[tuple[int, int], str] = {
    (VENDOR_ID_GRAPHTEC, 0x1137): "Silhouette Cameo 4",
    (VENDOR_ID_GRAPHTEC, 0x1138): "Silhouette Cameo 4 Plus",
    (VENDOR_ID_GRAPHTEC, 0x1139): "Silhouette Cameo 4 Pro",
    (VENDOR_ID_GRAPHTEC, 0x1140): "Silhouette Cameo 5",
    (VENDOR_ID_GRAPHTEC, 0x1141): "Silhouette Cameo 5 Plus",
    (VENDOR_ID_GRAPHTEC, 0x1146): "Silhouette Cameo Pro Mk II",
    (VENDOR_ID_CAMEO5ALPHA, 0x0001): "Silhouette Cameo 5 Alpha",
    (VENDOR_ID_CAMEO5ALPHA, 0x0002): "Silhouette Cameo 5 Alpha Plus",
}

KNOWN_VENDOR_IDS = {VENDOR_ID_GRAPHTEC, VENDOR_ID_CAMEO5ALPHA}


@dataclass
class DeviceStatus:
    connected: bool
    name: str = ""
    error: str = ""  # set when detection itself failed (e.g. no libusb)


def detect_cameo() -> DeviceStatus:
    try:
        import usb.core
    except ImportError:
        return DeviceStatus(connected=False, error="pyusb nie je nainštalované")

    try:
        for vendor_id in KNOWN_VENDOR_IDS:
            device = usb.core.find(idVendor=vendor_id)
            if device is None:
                continue
            name = KNOWN_DEVICES.get((vendor_id, device.idProduct))
            if name is None:
                name = f"Neznáme zariadenie Graphtec/Silhouette (0x{device.idProduct:04x})"
            return DeviceStatus(connected=True, name=name)
    except usb.core.NoBackendError:
        return DeviceStatus(
            connected=False,
            error="Chýba knižnica libusb (nainštaluj 'libusb-1.0-0').",
        )
    except Exception as exc:  # defensive: never let a status check crash the GUI
        return DeviceStatus(connected=False, error=str(exc))

    return DeviceStatus(connected=False)
