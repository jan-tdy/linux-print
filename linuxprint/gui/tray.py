"""System tray icon: quick status, open the manager window, quit."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def _load_icon() -> QIcon:
    """
    Load the application icon from the bundled SVG asset, falling back to the system printer icon when the asset is unavailable.
    
    Returns:
    	QIcon: The loaded application icon.
    """
    svg = ASSETS_DIR / "jadiv-print-center.svg"
    if svg.exists():
        return QIcon(str(svg))
    return QIcon.fromTheme("printer")


class TrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, app: QApplication) -> None:
        """
        Initialize the system tray icon with its menu and activation handler.
        
        Parameters:
        	main_window: The main application window managed by the tray icon.
        	app (QApplication): The application instance used when quitting.
        """
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
        """Show the main window when the tray icon is clicked or double-clicked."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main_window()

    def show_main_window(self) -> None:
        """
        Display the main window and bring it to the foreground.
        """
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def notify(self, title: str, message: str) -> None:
        """Display an informational tray notification when notifications are enabled."""
        if self.main_window.settings.notifications_enabled:
            self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _quit(self) -> None:
        """Shut down the main window and exit the application."""
        self.main_window.shutdown()
        self.app.quit()
