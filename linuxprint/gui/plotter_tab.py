"""Plotter tab: Silhouette Cameo SVG cut/draw and print-and-cut, over USB.

MIT-licensed, same as the rest of the GUI. The actual cutter protocol runs
in a separate subprocess -- see linuxprint/plotter/vendor/inkscape_silhouette/
NOTICE.md for why (GPL-2.0 vendored driver, MIT app).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import cups_cli
from ..plotter import detect, regmarks
from ..plotter.device_cli import PlotEvent, run_job
from ..plotter.job import MEDIA_PRESETS, PlotJob, RegmarkSettings, ToolPass
from ..plotter.svg_import import ParsedSvg, parse_svg

# Display scale for the preview canvas; mm map straight onto scene units
# multiplied by this factor (both share a top-left, y-down origin, so no
# flip is needed -- see svg_import.py's module docstring).
PREVIEW_PX_PER_MM = 3.0


class _PlotWorker(QObject):
    # Note: not named "event" -- that shadows QObject.event() and breaks
    # PyQt's own event dispatch in confusing ways.
    progress = pyqtSignal(object)  # PlotEvent
    finished = pyqtSignal(object)  # PlotEvent (the final one)
    failed = pyqtSignal(str)

    def __init__(self, job: PlotJob) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            final = run_job(self.job, on_event=self.progress.emit)
        except Exception as exc:  # subprocess/plumbing failure, not a device error
            self.failed.emit(str(exc))
            return
        self.finished.emit(final)


class PlotterTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.parsed: ParsedSvg | None = None
        self.svg_path: str | None = None
        self._thread: QThread | None = None
        self._worker: _PlotWorker | None = None

        self._build_ui()
        self._refresh_device_status()
        self._refresh_printers()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        load_btn = QPushButton("Načítať SVG…")
        load_btn.clicked.connect(self._on_load_svg)
        self.file_label = QLabel("Žiadny súbor")
        top_row.addWidget(load_btn)
        top_row.addWidget(self.file_label, 1)
        self.device_label = QLabel("Zisťujem zariadenie…")
        refresh_device_btn = QPushButton("Obnoviť zariadenie")
        refresh_device_btn.clicked.connect(self._refresh_device_status)
        top_row.addWidget(self.device_label)
        top_row.addWidget(refresh_device_btn)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())
        splitter.addWidget(self.view)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)

        settings_group = QGroupBox("Nastavenia rezu")
        form = QFormLayout(settings_group)

        self.media_combo = QComboBox()
        self.media_combo.addItems(sorted(MEDIA_PRESETS.keys()))
        form.addRow("Médium:", self.media_combo)

        self.pressure_spin = QSpinBox()
        self.pressure_spin.setRange(1, 33)
        self.pressure_spin.setValue(27)
        form.addRow("Tlak čepele:", self.pressure_spin)

        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(1, 10)
        self.speed_spin.setValue(10)
        form.addRow("Rýchlosť:", self.speed_spin)

        self.pen_pressure_spin = QSpinBox()
        self.pen_pressure_spin.setRange(1, 33)
        self.pen_pressure_spin.setValue(18)
        form.addRow("Tlak pera:", self.pen_pressure_spin)

        controls_layout.addWidget(settings_group)

        regmark_group = QGroupBox("Tlač a rez (registračné značky)")
        regmark_layout = QFormLayout(regmark_group)
        self.regmark_check = QCheckBox("Použiť registračné značky")
        regmark_layout.addRow(self.regmark_check)
        self.quad_check = QCheckBox("4 značky (rohy)")
        regmark_layout.addRow(self.quad_check)
        self.printer_combo = QComboBox()
        regmark_layout.addRow("Tlačiareň:", self.printer_combo)
        controls_layout.addWidget(regmark_group)

        buttons_group = QGroupBox("Akcie")
        buttons_layout = QVBoxLayout(buttons_group)
        self.cut_btn = QPushButton("Vyrezať (červené čiary)")
        self.cut_btn.clicked.connect(self._on_cut)
        buttons_layout.addWidget(self.cut_btn)
        self.draw_btn = QPushButton("Nakresliť perom (ostatné čiary)")
        self.draw_btn.clicked.connect(self._on_draw)
        buttons_layout.addWidget(self.draw_btn)
        self.print_and_cut_btn = QPushButton("Tlač a rez…")
        self.print_and_cut_btn.clicked.connect(self._on_print_and_cut)
        buttons_layout.addWidget(self.print_and_cut_btn)
        controls_layout.addWidget(buttons_group)

        controls_layout.addStretch(1)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        layout.addWidget(QLabel("Denník plotra:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        layout.addWidget(self.log_view)

        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self.cut_btn, self.draw_btn, self.print_and_cut_btn):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # SVG loading + preview
    # ------------------------------------------------------------------

    def _on_load_svg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Načítať SVG", "", "SVG súbory (*.svg)")
        if not path:
            return
        try:
            self.parsed = parse_svg(path)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba pri načítaní SVG", str(exc))
            return
        self.svg_path = path
        self.file_label.setText(
            f"{os.path.basename(path)}  "
            f"({len(self.parsed.cut_paths)} rez. čiar, {len(self.parsed.draw_paths)} kresliacich čiar)"
        )
        self._render_preview()
        self._set_actions_enabled(True)

    def _render_preview(self) -> None:
        self.scene.clear()
        if self.parsed is None:
            return
        cut_pen = QPen(QColor("#e53935"))
        cut_pen.setWidthF(0.5)
        draw_pen = QPen(QColor("#333333"))
        draw_pen.setWidthF(0.5)
        for pen, paths in ((cut_pen, self.parsed.cut_paths), (draw_pen, self.parsed.draw_paths)):
            for path in paths:
                if len(path) < 2:
                    continue
                painter_path = QPainterPath()
                painter_path.moveTo(path[0][0] * PREVIEW_PX_PER_MM, path[0][1] * PREVIEW_PX_PER_MM)
                for x, y in path[1:]:
                    painter_path.lineTo(x * PREVIEW_PX_PER_MM, y * PREVIEW_PX_PER_MM)
                item = QGraphicsPathItem(painter_path)
                item.setPen(pen)
                self.scene.addItem(item)
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Device / printer status
    # ------------------------------------------------------------------

    def _refresh_device_status(self) -> None:
        status = detect.detect_cameo()
        if status.connected:
            self.device_label.setText(f"Pripojené: {status.name}")
        elif status.error:
            self.device_label.setText(f"Zariadenie: {status.error}")
        else:
            self.device_label.setText("Zariadenie nenájdené (skontroluj USB kábel)")

    def _refresh_printers(self) -> None:
        self.printer_combo.clear()
        try:
            printers = cups_cli.list_printers()
        except cups_cli.CupsToolMissing:
            return
        self.printer_combo.addItems(sorted(printers.keys()))

    # ------------------------------------------------------------------
    # Job building + running
    # ------------------------------------------------------------------

    def _build_job(self, *, include_cut: bool, include_draw: bool, regmark: bool) -> PlotJob | None:
        if self.parsed is None:
            return None
        passes: list[ToolPass] = []
        if include_cut and self.parsed.cut_paths:
            passes.append(
                ToolPass(
                    tool="blade",
                    paths=self.parsed.cut_paths,
                    speed=self.speed_spin.value(),
                    pressure=self.pressure_spin.value(),
                )
            )
        if include_draw and self.parsed.draw_paths:
            passes.append(
                ToolPass(
                    tool="pen",
                    paths=self.parsed.draw_paths,
                    speed=self.speed_spin.value(),
                    pressure=self.pen_pressure_spin.value(),
                )
            )
        if not passes:
            QMessageBox.information(self, "Nič na spracovanie", "SVG neobsahuje žiadne čiary tohto typu.")
            return None

        regmark_settings = RegmarkSettings(enabled=regmark, quad=self.quad_check.isChecked())
        return PlotJob(passes=passes, media_preset=self.media_combo.currentText(), regmark=regmark_settings)

    def _run_job(self, job: PlotJob) -> None:
        self.log_view.append(f"Spúšťam úlohu ({len(job.passes)} prechodov)…")
        self._set_actions_enabled(False)

        self._thread = QThread()
        self._worker = _PlotWorker(job)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_plot_event)
        self._worker.finished.connect(self._on_plot_finished)
        self._worker.failed.connect(self._on_plot_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_plot_event(self, event: PlotEvent) -> None:
        if event.kind == "pass_started":
            self.log_view.append(f"Prechod {event.index}: nástroj {event.tool}")
        elif event.kind == "pass_done":
            self.log_view.append(f"Prechod {event.index} dokončený")

    def _on_plot_finished(self, event: PlotEvent) -> None:
        self._set_actions_enabled(True)
        if event.kind == "error":
            self.log_view.append(f"CHYBA: {event.message}")
            QMessageBox.critical(self, "Rezanie zlyhalo", event.message or "Neznáma chyba plotra.")
        else:
            self.log_view.append("Hotovo.")

    def _on_plot_failed(self, message: str) -> None:
        self._set_actions_enabled(True)
        self.log_view.append(f"CHYBA: {message}")
        QMessageBox.critical(self, "Rezanie zlyhalo", message)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_cut(self) -> None:
        job = self._build_job(include_cut=True, include_draw=False, regmark=False)
        if job is not None:
            self._run_job(job)

    def _on_draw(self) -> None:
        job = self._build_job(include_cut=False, include_draw=True, regmark=False)
        if job is not None:
            self._run_job(job)

    def _on_print_and_cut(self) -> None:
        if self.parsed is None or self.svg_path is None:
            return
        printer = self.printer_combo.currentText()
        if not printer:
            QMessageBox.information(self, "Chýba tlačiareň", "Vyber tlačiareň pre krok tlače.")
            return
        if QMessageBox.question(
            self,
            "Tlač a rez",
            "Najprv sa vytlačí návrh s registračnými značkami. Po vytlačení vlož "
            "list na rezaciu podložku (zarovnaný podľa značiek) a pokračuj rezaním.\n\n"
            "Vytlačiť teraz?",
        ) != QMessageBox.StandardButton.Yes:
            return

        regmark_settings = RegmarkSettings(enabled=True, quad=self.quad_check.isChecked())
        merged_path = regmarks.merge_svg_with_regmarks(self.svg_path, regmark_settings)
        result = cups_cli.submit_print_job(printer, merged_path, title="Jadiv Print Center - tlač a rez")
        if not result.ok:
            QMessageBox.critical(self, "Tlač zlyhala", result.stderr or "Neznáma chyba lp.")
            return

        if QMessageBox.question(
            self,
            "Pokračovať rezom",
            "List je vytlačený. Po umiestnení na rezaciu podložku pokračuj rezom "
            "(zariadenie samo nájde registračné značky).",
        ) != QMessageBox.StandardButton.Yes:
            return

        job = self._build_job(include_cut=True, include_draw=False, regmark=True)
        if job is not None:
            self._run_job(job)
