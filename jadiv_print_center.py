#!/usr/bin/env python3
"""Jadiv Print Center -- a PyQt6 print manager for Ubuntu/Kubuntu 24.04+.

Manages USB, network and remote-CUPS-server printers on top of the system's
own CUPS installation, with autodiscovery and a background watcher that
repairs printers whose IP address or port changed -- the exact failure mode
that makes the stock Linux print stack feel unreliable.

Usage:
    python3 jadiv_print_center.py            # normal launch (window + tray)
    python3 jadiv_print_center.py --daemon   # start hidden in the tray only
                                              # (used by the systemd --user
                                              # service; see install-service.sh)

If an instance is already running (as the daemon, or launched earlier), a
second launch just raises the existing window instead of starting a second
watcher.
"""

from __future__ import annotations

import argparse
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from linuxprint import config
from linuxprint.cups_cli import is_available
from linuxprint.gui.main_window import MainWindow
from linuxprint.gui.tray import TrayIcon
from linuxprint.ipc import SingleInstanceServer, notify_existing_instance


def parse_args(argv: list[str]) -> argparse.Namespace:
    """
    Parse application command-line options.
    
    Parameters:
        argv (list[str]): Command-line arguments to parse.
    
    Returns:
        argparse.Namespace: Parsed options, including whether daemon mode was requested.
    """
    parser = argparse.ArgumentParser(description=config.APP_NAME)
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Start hidden in the system tray (used by the background service).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the Jadiv Print Center application in windowed or daemon mode.
    
    Parameters:
        argv (list[str] | None): Command-line arguments to parse, excluding the
            program name. If omitted, uses the process command-line arguments.
    
    Returns:
        int: The application's exit status.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if notify_existing_instance():
        return 0

    config.ensure_dirs()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(config.APP_NAME)

    if not is_available("lpstat") or not is_available("lpadmin"):
        QMessageBox.critical(
            None,
            "Chýbajú CUPS nástroje",
            "Nenašiel som 'lpstat'/'lpadmin'. Nainštaluj balík 'cups' a 'cups-client':\n\n"
            "  sudo apt install cups cups-client\n\n"
            "Aplikácia sa teraz ukončí.",
        )
        return 1

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None,
            "Systémová lišta nie je dostupná",
            "Prostredie nemá systémovú lištu -- aplikácia pobeží iba ako okno, "
            "bez ikony na pozadí.",
        )

    main_window = MainWindow(run_watcher=True)
    tray = TrayIcon(main_window, app)
    tray.show()

    ipc_server = SingleInstanceServer()
    ipc_server.show_requested.connect(tray.show_main_window)
    ipc_server.listen()

    if args.daemon:
        watcher = main_window.watcher
        if watcher is not None:
            watcher.repairs_applied.connect(
                lambda results: tray.notify(
                    "Tlačiareň bola opravená",
                    "\n".join(r.message for r in results),
                )
            )
            watcher.error.connect(lambda message: tray.notify("Chyba pri kontrole tlačiarní", message))
    else:
        main_window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
