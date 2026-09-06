# Stub replacement for inkscape-silhouette's silhouette/BLETransport.py.
#
# The real inkscape-silhouette ships a full Bluetooth LE (BLE GATT) transport
# there. This linux-print integration only targets USB Silhouette Cameo
# devices for now (see the Plotter tab in the main app), so pulling in the
# real BLE transport -- and its extra platform-specific BLE stack dependency
# -- isn't worth it yet. Graphtec.py still unconditionally imports this name,
# so this stub exists purely to satisfy that import; every code path in
# Graphtec.py that would use it is only reached when the caller explicitly
# passes bluetooth_le=True / bluetooth_name= / bluetooth_identifier=, which
# linuxprint's plotter code never does.
#
# This file is original to jan-tdy/linux-print (not copied from
# inkscape-silhouette) but lives alongside GPL-2.0 vendored code that it
# exists solely to satisfy the import of, so it is released under the same
# GPL-2.0 terms as the rest of this directory (see LICENSE).


class BLETransport:
    @classmethod
    def connect(cls, *args, **kwargs):
        raise RuntimeError(
            "Bluetooth LE is not supported by this build of linux-print's "
            "Plotter tab (USB only). Connect the Cameo over USB instead."
        )
