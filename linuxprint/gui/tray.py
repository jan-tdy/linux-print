"""System tray icon: quick status, open the manager window, quit."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

# Sizes covering the tray/panel icon requests typical desktop environments
# make (GNOME/KDE/XFCE panels ask 16-48px; HiDPI panels ask for more).
_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128)


def _load_icon() -> QIcon:
    """Load the application icon from the bundled SVG asset, falling back to
    the system printer icon when the asset is unavailable or can't be
    rendered."""
    svg = ASSETS_DIR / "jadiv-print-center.svg"
    if svg.exists():
        icon = _render_svg_icon(svg)
        if icon is not None:
            return icon
    return QIcon.fromTheme("printer")


def _render_svg_icon(svg_path: Path) -> QIcon | None:
    """Rasterize the SVG into a QIcon ourselves via QSvgRenderer, instead of
    the simpler `QIcon(str(svg_path))`.

    That simpler form depends on Qt's separate SVG *icon engine* plugin
    being installed -- on Debian/Ubuntu this is a distinct apt package
    (python3-pyqt6.qtsvg) from the main python3-pyqt6 one the README's apt
    fallback mentions -- and when it's missing, QIcon doesn't raise or
    return a null icon; it silently produces an icon that looks fine
    in-widget but renders as blank in an actual system tray (a known
    StatusNotifierItem/XEmbed quirk with vector icon engines on several
    desktop shells). Rendering to fixed-size QPixmaps ourselves only needs
    the QtSvg module (part of the main PyQt6 wheel/apt package) to be
    importable, not that separate icon-engine plugin.
    """
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        return None
    icon = QIcon()
    for size in _ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


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
        open_action = QAction("Open printer manager", self)
        open_action.triggered.connect(self.show_main_window)
        menu.addAction(open_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
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
