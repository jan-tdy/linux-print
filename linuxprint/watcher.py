"""Background watcher: periodically re-discovers printers and asks the
healer to repair any that drifted, independent of whether the main window is
open. Runs on a QTimer inside a dedicated QThread so it never blocks the UI.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from . import config, cups_cli, discovery, healer, identity


class Watcher(QObject):
    """Lives inside its own QThread. All slots run on that thread."""

    printers_updated = pyqtSignal(dict)  # name -> Printer
    discovered_updated = pyqtSignal(list)  # list[DiscoveredPrinter]
    repairs_applied = pyqtSignal(list)  # list[RepairResult]
    unreachable_changed = pyqtSignal(dict)  # name -> bool (True = unreachable)
    log_message = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, settings: config.Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or config.load_settings()
        self._timer: QTimer | None = None

    def start(self) -> None:
        self._timer = QTimer()
        self._timer.setInterval(max(5, self.settings.check_interval_seconds) * 1000)
        self._timer.timeout.connect(self.run_cycle)
        self._timer.start()
        self.run_cycle()

    def update_interval(self, seconds: int) -> None:
        if self._timer is not None:
            self._timer.setInterval(max(5, seconds) * 1000)

    def run_cycle(self) -> None:
        try:
            self._run_cycle()
        except cups_cli.CupsToolMissing as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # defensive: never let the watcher die silently
            self.error.emit(f"Neočakávaná chyba pri kontrole tlačiarní: {exc}")

    def _run_cycle(self) -> None:
        installed = cups_cli.list_printers()
        self.printers_updated.emit(installed)

        discovered = discovery.discover_all()
        self.discovered_updated.emit(discovered)

        unreachable: dict[str, bool] = {}
        for name, printer in installed.items():
            classified = discovery.classify(printer.uri)
            if classified and classified.category == "network-ip" and classified.host:
                unreachable[name] = not healer.is_host_reachable(classified.host, classified.port or 631)
        self.unreachable_changed.emit(unreachable)

        if not self.settings.autoheal_enabled:
            return

        identities = identity.load_map()
        repairs = healer.plan_repairs(installed, discovered, identities)
        if not repairs:
            return
        results = healer.apply_repairs(repairs)
        for result in results:
            healer.append_log(result.message)
            self.log_message.emit(result.message)
        self.repairs_applied.emit(results)


def start_watcher_thread(settings: config.Settings | None = None) -> tuple[QThread, Watcher]:
    """Create and start a Watcher on its own thread. Caller must keep both
    the returned thread and watcher alive (e.g. as attributes on a QObject
    that outlives them) or Qt will garbage-collect and stop them."""
    thread = QThread()
    watcher = Watcher(settings)
    watcher.moveToThread(thread)
    thread.started.connect(watcher.start)
    thread.start()
    return thread, watcher
