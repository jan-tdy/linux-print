#!/usr/bin/env bash
# Install (or uninstall) the udev rule that lets the Plotter tab talk to a
# Silhouette Cameo over USB without running as root.
#
#   sudo ./install-plotter-udev.sh              # install
#   sudo ./install-plotter-udev.sh --uninstall  # remove
#
# Requires root because /etc/udev/rules.d/ is root-owned; everything else
# in this repo's install scripts is per-user and needs no sudo, but a udev
# rule is inherently a system-wide, root-only setting.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_FILE=61-silhouette-cameo.rules
DEST="/etc/udev/rules.d/$RULE_FILE"

do_uninstall() {
    rm -f "$DEST"
    udevadm control --reload-rules
    udevadm trigger
    echo "Removed $DEST"
}

do_install() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Error: this needs root (writes to /etc/udev/rules.d/). Try:" >&2
        echo "    sudo $0" >&2
        exit 1
    fi
    install -m 0644 "$REPO_DIR/assets/$RULE_FILE" "$DEST"
    udevadm control --reload-rules
    udevadm trigger
    echo "Installed $DEST"
    echo "Unplug and replug the Cameo (or reboot) for the new permissions to take effect."
}

case "${1:-}" in
    "")            do_install ;;
    -u|--uninstall) do_uninstall ;;
    -h|--help)
        echo "Usage: sudo $0 [options]"
        echo "  (no args)        Install the udev rule"
        echo "  -u, --uninstall  Remove the udev rule"
        echo "  -h, --help       Show this help message"
        ;;
    *)
        echo "Unknown option: $1" >&2
        echo "Try '$0 --help'." >&2
        exit 1
        ;;
esac
