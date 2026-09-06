#!/usr/bin/env bash
# Install (or uninstall) the Jadiv Print Center desktop launcher on Linux.
#
#   ./install-launcher.sh            # install for the current user
#   ./install-launcher.sh --uninstall
#
# Installs into the per-user XDG locations (no root required):
#   ~/.local/share/applications/                  – the .desktop launcher
#   ~/.local/share/icons/hicolor/scalable/apps/   – the icon
set -euo pipefail

# Absolute path to this repository (where jadiv_print_center.py lives).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$REPO_DIR/assets"

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

DESKTOP_FILE=jadiv-print-center.desktop
ICON_NAME=jadiv-print-center.svg

# update_caches refreshes the desktop-entry database and GTK icon cache when the required commands are available.
update_caches() {
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 \
        && gtk-update-icon-cache -f -i -t \
            "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" \
            >/dev/null 2>&1 || true
}

# do_uninstall removes the per-user Jadiv Print Center desktop launcher and icon, then refreshes relevant caches.
do_uninstall() {
    rm -f "$APP_DIR/$DESKTOP_FILE"
    rm -f "$ICON_DIR/$ICON_NAME"
    update_caches
    echo "Removed Jadiv Print Center launcher."
}

# do_install installs the Jadiv Print Center desktop launcher and icon for the current user.
do_install() {
    # The desktop entry embeds this path in both Exec and Path. Quotes and
    # backslashes have syntax-specific meanings there, so refuse paths that
    # cannot be substituted literally instead of generating a broken entry.
    if [[ "$REPO_DIR" == *'"'* || "$REPO_DIR" == *'\'* ]]; then
        echo 'Error: the repository path must not contain quotes or backslashes.' >&2
        exit 1
    fi

    # Sanity check: make sure the app and its dependencies are reachable.
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Error: python3 is not installed." >&2
        exit 1
    fi
    if ! python3 -c "import PyQt6" >/dev/null 2>&1; then
        # Plain "pip" can resolve to a different interpreter than the
        # "python3" the .desktop launcher runs (Exec=python3 ...), so a
        # package it installs may be invisible to the app. Always go
        # through "python3 -m pip" so it lands in the same interpreter.
        # Debian/Ubuntu/Arch also refuse a direct pip install into the
        # system Python (PEP 668, "externally-managed-environment"); the
        # --user --break-system-packages combination is what pip's own
        # error message recommends as the override.
        echo "Warning: PyQt6 is not installed. Install it with:" >&2
        printf '    python3 -m pip install --user -r %q\n' \
            "$REPO_DIR/requirements.txt" >&2
        echo "    (add --break-system-packages if pip refuses with" >&2
        echo "     'externally-managed-environment', or use" >&2
        echo "     'sudo apt install python3-pyqt6')" >&2
    fi
    if ! python3 -c "import usb, svgelements, defusedxml" >/dev/null 2>&1; then
        echo "Warning: pyusb, svgelements and/or defusedxml are not installed (needed" >&2
        echo "for the Plotter tab -- printing still works without them). Install with:" >&2
        printf '    python3 -m pip install --user -r %q\n' \
            "$REPO_DIR/requirements.txt" >&2
        echo "    (add --break-system-packages if pip refuses with" >&2
        echo "     'externally-managed-environment')" >&2
    fi
    if ! command -v lpadmin >/dev/null 2>&1; then
        echo "Warning: 'lpadmin' not found. Install CUPS with:" >&2
        echo "    sudo apt install cups cups-client" >&2
    fi

    mkdir -p "$APP_DIR" "$ICON_DIR"
    install -m 0644 "$ASSETS_DIR/$ICON_NAME" "$ICON_DIR/$ICON_NAME"

    # Substitute the placeholder with the validated repo path. Python performs
    # a literal replacement, while the check above excludes characters that
    # would need desktop-entry escaping in the generated fields.
    python3 -c 'import sys; sys.stdout.write(sys.stdin.read().replace("__INSTALL_DIR__", sys.argv[1]))' \
        "$REPO_DIR" < "$ASSETS_DIR/$DESKTOP_FILE" > "$APP_DIR/$DESKTOP_FILE"
    chmod 0644 "$APP_DIR/$DESKTOP_FILE"

    update_caches
    echo "Installed Jadiv Print Center launcher into $APP_DIR"
    echo "Look for 'Jadiv Print Center' in your application menu."
    echo "Tip: run ./install-service.sh to also keep it self-healing in the background."
}

case "${1:-}" in
    "")            do_install ;;
    -u|--uninstall) do_uninstall ;;
    -h|--help)
        echo "Usage: $0 [options]"
        echo "  (no args)        Install the launcher and icon"
        echo "  -u, --uninstall  Uninstall the launcher and icon"
        echo "  -h, --help       Show this help message"
        ;;
    *)
        echo "Unknown option: $1" >&2
        echo "Try '$0 --help'." >&2
        exit 1
        ;;
esac
