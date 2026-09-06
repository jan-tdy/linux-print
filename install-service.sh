#!/usr/bin/env bash
# Install (or uninstall) the Jadiv Print Center background self-healing
# service as a systemd --user unit.
#
#   ./install-service.sh              # install, enable and start it
#   ./install-service.sh --uninstall  # stop, disable and remove it
#
# The service just runs `jadiv_print_center.py --daemon`: no window, only a
# tray icon and the background watcher that keeps autodiscovering printers
# and repairing device URIs that drifted (e.g. after a DHCP lease renewal
# changed a network printer's IP). It survives logout/login and starts
# automatically once enabled -- no root required, this only touches
# ~/.config/systemd/user/.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$REPO_DIR/assets"

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE=jadiv-print-center-daemon.service

do_uninstall() {
    systemctl --user disable --now "$UNIT_FILE" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT_FILE"
    systemctl --user daemon-reload
    echo "Removed the Jadiv Print Center background service."
}

do_install() {
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "Error: systemctl not found -- this system doesn't use systemd." >&2
        echo "You can still run 'python3 $REPO_DIR/jadiv_print_center.py --daemon' manually" >&2
        echo "(e.g. as a Startup Application in your desktop environment)." >&2
        exit 1
    fi

    mkdir -p "$UNIT_DIR"
    python3 -c 'import sys; sys.stdout.write(sys.stdin.read().replace("__INSTALL_DIR__", sys.argv[1]))' \
        "$REPO_DIR" < "$ASSETS_DIR/$UNIT_FILE" > "$UNIT_DIR/$UNIT_FILE"
    chmod 0644 "$UNIT_DIR/$UNIT_FILE"

    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT_FILE"
    echo "Installed and started the Jadiv Print Center background service."
    echo "Check its status any time with:"
    echo "    systemctl --user status $UNIT_FILE"
}

case "${1:-}" in
    "")            do_install ;;
    -u|--uninstall) do_uninstall ;;
    -h|--help)
        echo "Usage: $0 [options]"
        echo "  (no args)        Install, enable and start the background service"
        echo "  -u, --uninstall  Stop, disable and remove the background service"
        echo "  -h, --help       Show this help message"
        ;;
    *)
        echo "Unknown option: $1" >&2
        echo "Try '$0 --help'." >&2
        exit 1
        ;;
esac
