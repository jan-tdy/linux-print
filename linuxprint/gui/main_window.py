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
from .plotter_tab import PlotterTab
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
        self.resize(900, 620)

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
        tabs.addTab(self._build_printers_tab(), "Tlačiarne")
        tabs.addTab(self._build_queue_tab(), "Front úloh")
        tabs.addTab(self._build_settings_tab(), "Denník a nastavenia")
        tabs.addTab(PlotterTab(), "Plotter (Cameo)")
        self.setCentralWidget(tabs)

    def _build_printers_tab(self) -> QWidget:
        """Builds the printer management tab with a printer table and action controls."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.printers_table = QTableWidget(0, 5)
        self.printers_table.setHorizontalHeaderLabels(["Názov", "Stav", "Typ", "Adresa (URI)", "Predvolená"])
        self.printers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.printers_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.printers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.printers_table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Pridať tlačiareň…")
        add_btn.clicked.connect(self._on_add_printer)
        remove_btn = QPushButton("Odstrániť")
        remove_btn.clicked.connect(self._on_remove_printer)
        default_btn = QPushButton("Nastaviť ako predvolenú")
        default_btn.clicked.connect(self._on_set_default)
        enable_btn = QPushButton("Povoliť")
        enable_btn.clicked.connect(lambda: self._on_set_enabled(True))
        disable_btn = QPushButton("Zastaviť")
        disable_btn.clicked.connect(lambda: self._on_set_enabled(False))
        refresh_btn = QPushButton("Obnoviť")
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
        self.jobs_table.setHorizontalHeaderLabels(["ID úlohy", "Tlačiareň", "Používateľ", "Detail"])
        self.jobs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.jobs_table)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Zrušiť úlohu")
        cancel_btn.clicked.connect(self._on_cancel_job)
        hold_btn = QPushButton("Pozastaviť")
        hold_btn.clicked.connect(self._on_hold_job)
        release_btn = QPushButton("Pokračovať")
        release_btn.clicked.connect(self._on_release_job)
        self.move_combo = QComboBox()
        move_btn = QPushButton("Presunúť na")
        move_btn.clicked.connect(self._on_move_job)
        refresh_btn = QPushButton("Obnoviť")
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
        form.addRow("Interval kontroly:", self.interval_spin)

        self.autoheal_check = QCheckBox("Automaticky opravovať tlačiarne po zmene IP/portu")
        self.autoheal_check.setChecked(self.settings.autoheal_enabled)
        form.addRow(self.autoheal_check)

        self.notify_check = QCheckBox("Zobrazovať upozornenia v systémovej lište")
        self.notify_check.setChecked(self.settings.notifications_enabled)
        form.addRow(self.notify_check)

        save_btn = QPushButton("Uložiť nastavenia")
        save_btn.clicked.connect(self._on_save_settings)
        form.addRow(save_btn)
        layout.addLayout(form)

        layout.addWidget(QLabel("Služba na pozadí (systemd --user):"))
        self.service_status_label = QLabel("...")
        layout.addWidget(self.service_status_label)
        service_buttons = QHBoxLayout()
        start_btn = QPushButton("Spustiť")
        start_btn.clicked.connect(self._on_service_start)
        stop_btn = QPushButton("Zastaviť")
        stop_btn.clicked.connect(self._on_service_stop)
        enable_btn = QPushButton("Povoliť pri štarte")
        enable_btn.clicked.connect(self._on_service_enable)
        disable_btn = QPushButton("Zakázať pri štarte")
        disable_btn.clicked.connect(self._on_service_disable)
        refresh_btn = QPushButton("Obnoviť stav")
        refresh_btn.clicked.connect(self._refresh_service_status)
        for btn in (start_btn, stop_btn, enable_btn, disable_btn, refresh_btn):
            service_buttons.addWidget(btn)
        service_buttons.addStretch(1)
        layout.addLayout(service_buttons)
        self._refresh_service_status()

        layout.addWidget(QLabel("Denník opráv:"))
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
        self._append_log(f"CHYBA: {message}")

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
            table.setItem(row, 4, QTableWidgetItem("Áno" if printer.is_default else ""))

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
            QMessageBox.warning(self, "CUPS nástroje chýbajú", str(exc))
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
                "Nešifrované pripojenie tlačiarne",
                cups_cli.LEGACY_TRANSPORT_WARNING + "\n\nChceš napriek tomu pokračovať?",
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
            QMessageBox.critical(self, "Pridanie zlyhalo", result.stderr or "Neznáma chyba lpadmin.")
            return
        identity.remember(name, device, legacy_transport_allowed=allow_legacy_transport)
        self._append_log(f"Pridaná tlačiareň '{name}' ({device.uri}).")
        self._refresh_printers_now()

    def _on_remove_printer(self) -> None:
        """
        Remove the selected printer after user confirmation.
        """
        name = self._selected_printer_name()
        if not name:
            return
        if QMessageBox.question(self, "Odstrániť", f"Naozaj odstrániť tlačiareň '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        result = cups_cli.remove_printer(name)
        if not result.ok:
            QMessageBox.critical(self, "Odstránenie zlyhalo", result.stderr or "Neznáma chyba lpadmin.")
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
        QMessageBox.information(self, "Uložené", "Nastavenia boli uložené.")

    def _refresh_service_status(self) -> None:
        """Update the displayed status of the systemd user service."""
        if not servicectl.is_installed():
            self.service_status_label.setText("Služba nie je nainštalovaná (spusti install-service.sh).")
            return
        active = "beží" if servicectl.is_active() else "nebeží"
        enabled = "spúšťa sa automaticky" if servicectl.is_enabled() else "nespúšťa sa automaticky"
        self.service_status_label.setText(f"Stav: {active}, {enabled}.")

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
