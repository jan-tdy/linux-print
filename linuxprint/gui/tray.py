"""System tray icon: quick status, open the manager window, quit."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def _load_icon() -> QIcon:
    svg = ASSETS_DIR / "jadiv-print-center.svg"
    if svg.exists():
        return QIcon(str(svg))
    return QIcon.fromTheme("printer")


class TrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, app: QApplication) -> None:
        super().__init__(_load_icon())
        self.main_window = main_window
        self.app = app
        self.setToolTip("Jadiv Print Center")

        menu = QMenu()
        open_action = QAction("Otvoriť správcu tlačiarní", self)
        open_action.triggered.connect(self.show_main_window)
        menu.addAction(open_action)
        menu.addSeparator()
        quit_action = QAction("Ukončiť", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main_window()

    def show_main_window(self) -> None:
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def notify(self, title: str, message: str) -> None:
        if self.main_window.settings.notifications_enabled:
            self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _quit(self) -> None:
        self.main_window.shutdown()
        self.app.quit()
