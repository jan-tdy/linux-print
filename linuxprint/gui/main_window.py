"""Main application window: Printers / Queue / Log & Settings tabs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import config, cups_cli, discovery, healer, identity, servicectl
from ..cups_cli import CupsToolMissing
from ..watcher import start_watcher_thread
from .add_wizard import AddPrinterDialog
from .widgets import CATEGORY_LABELS, status_item


class MainWindow(QMainWindow):
    def __init__(self, run_watcher: bool = True) -> None:
        """
        Initialize the main window, load settings, build the user interface, and optionally start the printer watcher.
        
        Parameters:
        	run_watcher (bool): Whether to start the background printer watcher and connect its update signals.
        """
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} {config.APP_VERSION}")
        self.resize(*self._initial_window_size(900, 620))

        self.settings = config.load_settings()
        self._installed: dict[str, cups_cli.Printer] = {}
        self._unreachable: dict[str, bool] = {}

        self._build_ui()

        self.thread = None
        self.watcher = None
        if run_watcher:
            self.thread, self.watcher = start_watcher_thread(self.settings)
            self.watcher.printers_updated.connect(self._on_printers_updated)
            self.watcher.unreachable_changed.connect(self._on_unreachable_updated)
            self.watcher.repairs_applied.connect(self._on_repairs_applied)
            self.watcher.log_message.connect(self._append_log)
            self.watcher.error.connect(self._on_watcher_error)

    @staticmethod
    def _initial_window_size(preferred_width: int, preferred_height: int) -> tuple[int, int]:
        """Clamp the preferred startup size to the primary screen's
        available geometry (minus a small margin for window decorations/
        taskbars), so the window never opens taller or wider than the
        monitor it's about to appear on -- a fixed 900x620 could otherwise
        exceed a smaller laptop screen's usable area, leaving the bottom of
        the window (and whatever tab-specific content is anchored there)
        off-screen and unreachable."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return preferred_width, preferred_height
        available = screen.availableGeometry()
        return (
            min(preferred_width, max(available.width() - 40, 320)),
            min(preferred_height, max(available.height() - 80, 240)),
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Hide to tray on close when one is available; otherwise this is
        the user's only exit path, so actually quit instead of leaving a
        hidden, unreachable window with a watcher nothing can stop."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            self.shutdown()
            event.accept()
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def shutdown(self) -> None:
        """
        Stop the background watcher thread and wait up to two seconds for it to finish.
        """
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Builds the main window's tabbed user interface."""
        tabs = QTabWidget()
        tabs.addTab(self._build_printers_tab(), "Printers")
        tabs.addTab(self._build_queue_tab(), "Job queue")
        tabs.addTab(self._build_settings_tab(), "Log & settings")
        tabs.addTab(self._build_plotter_tab(), "Plotter (Cameo)")
        tabs.addTab(self._build_booklet_tab(), "Booklet (A5)")
        self.setCentralWidget(tabs)

    def _build_plotter_tab(self) -> QWidget:
        """
        Build the Plotter tab, or a placeholder explaining what's missing if
        its optional dependencies (pyusb, svgelements) aren't installed.

        Imported here rather than at module load time: PlotterTab pulls in
        svgelements (and, transitively, USB device detection), which are
        only needed for this one tab (see README's Requirements section) --
        a missing optional dependency must not crash printer management,
        which the rest of this app doesn't need it for.
        """
        try:
            from .plotter_tab import PlotterTab
        except ImportError as exc:
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            layout.addWidget(
                QLabel(
                    "The Plotter tab is unavailable -- missing dependency "
                    f"({exc.name or exc}).\n\n"
                    "Install it with:\n"
                    "    python3 -m pip install --user pyusb svgelements defusedxml\n"
                    "and restart the application."
                )
            )
            layout.addStretch(1)
            return placeholder
        return PlotterTab()

    def _build_booklet_tab(self) -> QWidget:
        """
        Build the Booklet tab, or a placeholder explaining what's missing if
        its optional dependencies (pypdfium2, Pillow) aren't installed.

        Imported here rather than at module load time, same reasoning as
        _build_plotter_tab: a missing optional dependency must not crash
        printer management, which doesn't need it.
        """
        try:
            from .booklet_tab import BookletTab
        except ImportError as exc:
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            layout.addWidget(
                QLabel(
                    "The Booklet tab is unavailable -- missing dependency "
                    f"({exc.name or exc}).\n\n"
                    "Install it with:\n"
                    "    python3 -m pip install --user pypdfium2 Pillow\n"
                    "and restart the application."
                )
            )
            layout.addStretch(1)
            return placeholder
        return BookletTab()

    def _build_printers_tab(self) -> QWidget:
        """Builds the printer management tab with a printer table and action controls."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.printers_table = QTableWidget(0, 5)
        self.printers_table.setHorizontalHeaderLabels(["Name", "Status", "Type", "Address (URI)", "Default"])
        self.printers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.printers_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.printers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.printers_table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add printer…")
        add_btn.clicked.connect(self._on_add_printer)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove_printer)
        default_btn = QPushButton("Set as default")
        default_btn.clicked.connect(self._on_set_default)
        enable_btn = QPushButton("Enable")
        enable_btn.clicked.connect(lambda: self._on_set_enabled(True))
        disable_btn = QPushButton("Stop")
        disable_btn.clicked.connect(lambda: self._on_set_enabled(False))
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_printers_now)
        for btn in (add_btn, remove_btn, default_btn, enable_btn, disable_btn, refresh_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    def _build_queue_tab(self) -> QWidget:
        """Builds the queue tab with a job table and controls for managing print jobs.
        
        Returns:
            QWidget: The configured queue tab widget.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setHorizontalHeaderLabels(["Job ID", "Printer", "User", "Detail"])
        self.jobs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.jobs_table)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel job")
        cancel_btn.clicked.connect(self._on_cancel_job)
        hold_btn = QPushButton("Hold")
        hold_btn.clicked.connect(self._on_hold_job)
        release_btn = QPushButton("Release")
        release_btn.clicked.connect(self._on_release_job)
        self.move_combo = QComboBox()
        move_btn = QPushButton("Move to")
        move_btn.clicked.connect(self._on_move_job)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_jobs_now)
        for w in (cancel_btn, hold_btn, release_btn, self.move_combo, move_btn, refresh_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    def _build_settings_tab(self) -> QWidget:
        """
        Builds the settings tab with watcher options, background service controls, and the repair log.
        
        Returns:
        	QWidget: The configured settings tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setSuffix(" s")
        self.interval_spin.setValue(self.settings.check_interval_seconds)
        form.addRow("Check interval:", self.interval_spin)

        self.autoheal_check = QCheckBox("Automatically repair printers after an IP/port change")
        self.autoheal_check.setChecked(self.settings.autoheal_enabled)
        form.addRow(self.autoheal_check)

        self.notify_check = QCheckBox("Show notifications in the system tray")
        self.notify_check.setChecked(self.settings.notifications_enabled)
        form.addRow(self.notify_check)

        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save_settings)
        form.addRow(save_btn)
        layout.addLayout(form)

        layout.addWidget(QLabel("Background service (systemd --user):"))
        self.service_status_label = QLabel("...")
        layout.addWidget(self.service_status_label)
        service_buttons = QHBoxLayout()
        start_btn = QPushButton("Start")
        start_btn.clicked.connect(self._on_service_start)
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._on_service_stop)
        enable_btn = QPushButton("Enable at startup")
        enable_btn.clicked.connect(self._on_service_enable)
        disable_btn = QPushButton("Disable at startup")
        disable_btn.clicked.connect(self._on_service_disable)
        refresh_btn = QPushButton("Refresh status")
        refresh_btn.clicked.connect(self._refresh_service_status)
        for btn in (start_btn, stop_btn, enable_btn, disable_btn, refresh_btn):
            service_buttons.addWidget(btn)
        service_buttons.addStretch(1)
        layout.addLayout(service_buttons)
        self._refresh_service_status()

        layout.addWidget(QLabel("Repair log:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        self._load_log_tail()
        return widget

    # ------------------------------------------------------------------
    # Watcher signal handlers
    # ------------------------------------------------------------------

    def _on_printers_updated(self, printers: dict[str, cups_cli.Printer]) -> None:
        """Update the stored printer data and refresh the printer-related controls."""
        self._installed = printers
        self._render_printers_table()
        self._refresh_move_combo()

    def _on_unreachable_updated(self, unreachable: dict[str, bool]) -> None:
        """Update printer reachability data and refresh the printer table."""
        self._unreachable = unreachable
        self._render_printers_table()

    def _on_repairs_applied(self, results: list[healer.RepairResult]) -> None:
        """Log applied repair results and refresh the printer display."""
        for result in results:
            self._append_log(result.message)
        self._refresh_printers_now()

    def _on_watcher_error(self, message: str) -> None:
        """
        Record a watcher error message in the repair log.
        
        Parameters:
        	message (str): The error message to record.
        """
        self._append_log(f"ERROR: {message}")

    def _append_log(self, message: str) -> None:
        """
        Append a message to the repair log view.
        
        Parameters:
        	message (str): The message to display.
        """
        self.log_view.append(message)

    def _load_log_tail(self) -> None:
        """Load the last 200 lines of the healer log into the log view."""
        if not config.HEALER_LOG_FILE.exists():
            return
        lines = config.HEALER_LOG_FILE.read_text(encoding="utf-8").splitlines()[-200:]
        self.log_view.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Printers tab actions
    # ------------------------------------------------------------------

    def _render_printers_table(self) -> None:
        """Render the installed printers and their current status in the printer table."""
        table = self.printers_table
        table.setRowCount(len(self._installed))
        for row, (name, printer) in enumerate(sorted(self._installed.items())):
            classified = discovery.classify(printer.uri)
            category = classified.category if classified else "other"
            state = printer.state
            if self._unreachable.get(name):
                state = "unreachable"
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, status_item(state))
            table.setItem(row, 2, QTableWidgetItem(CATEGORY_LABELS.get(category, category)))
            table.setItem(row, 3, QTableWidgetItem(printer.uri))
            table.setItem(row, 4, QTableWidgetItem("Yes" if printer.is_default else ""))

    def _selected_printer_name(self) -> str | None:
        """
        Get the name of the selected printer.
        
        Returns:
        	str | None: The selected printer name, or `None` when no printer is selected.
        """
        rows = self.printers_table.selectionModel().selectedRows() if self.printers_table.selectionModel() else []
        if not rows:
            return None
        return self.printers_table.item(rows[0].row(), 0).text()

    def _refresh_printers_now(self) -> None:
        """
        Refresh the installed printer data and update the printer-related controls.
        
        Displays a warning and leaves the current data unchanged when the CUPS tools are unavailable.
        """
        try:
            self._installed = cups_cli.list_printers()
        except CupsToolMissing as exc:
            QMessageBox.warning(self, "CUPS tools missing", str(exc))
            return
        self._render_printers_table()
        self._refresh_move_combo()

    def _on_add_printer(self) -> None:
        """
        Add a printer using the configuration provided by the add-printer dialog.
        
        If the operation fails, displays an error message and leaves printer state unchanged.
        """
        dialog = AddPrinterDialog(self)
        if dialog.exec() != AddPrinterDialog.DialogCode.Accepted:
            return
        device = dialog.selected_device
        name = dialog.queue_name()
        allow_legacy_transport = False
        if cups_cli.requires_legacy_transport_opt_in(device.uri):
            choice = QMessageBox.warning(
                self,
                "Unencrypted printer connection",
                cups_cli.LEGACY_TRANSPORT_WARNING + "\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            allow_legacy_transport = True
        result = cups_cli.add_or_update_printer(
            name,
            device.uri,
            description=dialog.description(),
            location=dialog.location(),
            shared=dialog.shared(),
            set_default=dialog.set_default(),
            allow_legacy_transport=allow_legacy_transport,
        )
        if not result.ok:
            QMessageBox.critical(self, "Adding failed", result.stderr or "Unknown lpadmin error.")
            return
        identity.remember(name, device, legacy_transport_allowed=allow_legacy_transport)
        self._append_log(f"Added printer '{name}' ({device.uri}).")
        self._refresh_printers_now()

    def _on_remove_printer(self) -> None:
        """
        Remove the selected printer after user confirmation.
        """
        name = self._selected_printer_name()
        if not name:
            return
        if QMessageBox.question(self, "Remove", f"Really remove printer '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        result = cups_cli.remove_printer(name)
        if not result.ok:
            QMessageBox.critical(self, "Removal failed", result.stderr or "Unknown lpadmin error.")
            return
        identity.forget(name)
        self._refresh_printers_now()

    def _on_set_default(self) -> None:
        """Set the selected printer as the system default and refresh the printer list."""
        name = self._selected_printer_name()
        if name:
            cups_cli.set_default(name)
            self._refresh_printers_now()

    def _on_set_enabled(self, enabled: bool) -> None:
        """Set the selected printer's enabled state and refresh the printer list.
        
        Parameters:
        	enabled (bool): Whether the selected printer should be enabled.
        """
        name = self._selected_printer_name()
        if name:
            cups_cli.set_enabled(name, enabled)
            self._refresh_printers_now()

    # ------------------------------------------------------------------
    # Queue tab actions
    # ------------------------------------------------------------------

    def _refresh_jobs_now(self) -> None:
        """Refresh the job queue table with the current print jobs."""
        jobs = cups_cli.list_jobs()
        table = self.jobs_table
        table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            table.setItem(row, 0, QTableWidgetItem(job.job_id))
            table.setItem(row, 1, QTableWidgetItem(job.printer))
            table.setItem(row, 2, QTableWidgetItem(job.user))
            table.setItem(row, 3, QTableWidgetItem(job.raw))

    def _refresh_move_combo(self) -> None:
        """
        Refresh the job destination selector with the installed printers.
        
        Preserves the currently selected printer when it remains available.
        """
        current = self.move_combo.currentText()
        self.move_combo.clear()
        self.move_combo.addItems(sorted(self._installed.keys()))
        index = self.move_combo.findText(current)
        if index >= 0:
            self.move_combo.setCurrentIndex(index)

    def _selected_job_id(self) -> str | None:
        """Return the identifier of the currently selected print job.
        
        Returns:
        	str: The selected job identifier, or `None` when no job is selected.
        """
        rows = self.jobs_table.selectionModel().selectedRows() if self.jobs_table.selectionModel() else []
        if not rows:
            return None
        return self.jobs_table.item(rows[0].row(), 0).text()

    def _on_cancel_job(self) -> None:
        """Cancel the selected print job and refresh the job queue."""
        job_id = self._selected_job_id()
        if job_id:
            cups_cli.cancel_job(job_id)
            self._refresh_jobs_now()

    def _on_hold_job(self) -> None:
        """
        Places the selected print job on hold and refreshes the job queue.
        """
        job_id = self._selected_job_id()
        if job_id:
            cups_cli.hold_job(job_id)
            self._refresh_jobs_now()

    def _on_release_job(self) -> None:
        """Release the selected print job and refresh the displayed job queue."""
        job_id = self._selected_job_id()
        if job_id:
            cups_cli.release_job(job_id)
            self._refresh_jobs_now()

    def _on_move_job(self) -> None:
        """Moves the selected print job to the chosen destination printer."""
        job_id = self._selected_job_id()
        destination = self.move_combo.currentText()
        if job_id and destination:
            cups_cli.move_job(job_id, destination)
            self._refresh_jobs_now()

    # ------------------------------------------------------------------
    # Settings tab actions
    # ------------------------------------------------------------------

    def _on_save_settings(self) -> None:
        """
        Save the current monitoring settings and apply them to the active watcher.
        """
        self.settings.check_interval_seconds = self.interval_spin.value()
        self.settings.autoheal_enabled = self.autoheal_check.isChecked()
        self.settings.notifications_enabled = self.notify_check.isChecked()
        config.save_settings(self.settings)
        if self.watcher is not None:
            self.watcher.settings = self.settings
            self.watcher.update_interval(self.settings.check_interval_seconds)
        QMessageBox.information(self, "Saved", "Settings have been saved.")

    def _refresh_service_status(self) -> None:
        """Update the displayed status of the systemd user service."""
        if not servicectl.is_installed():
            self.service_status_label.setText("Service is not installed (run install-service.sh).")
            return
        active = "running" if servicectl.is_active() else "not running"
        enabled = "starts automatically" if servicectl.is_enabled() else "does not start automatically"
        self.service_status_label.setText(f"Status: {active}, {enabled}.")

    def _on_service_start(self) -> None:
        """Start the systemd user service and refresh its displayed status."""
        servicectl.start()
        self._refresh_service_status()

    def _on_service_stop(self) -> None:
        """Stops the systemd user service and refreshes its displayed status."""
        servicectl.stop()
        self._refresh_service_status()

    def _on_service_enable(self) -> None:
        """Enables the systemd user service and refreshes its displayed status."""
        servicectl.enable_now()
        self._refresh_service_status()

    def _on_service_disable(self) -> None:
        """Disable automatic startup of the systemd user service and refresh its displayed status."""
        servicectl.disable_now()
        self._refresh_service_status()
