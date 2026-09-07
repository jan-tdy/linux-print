"""Plotter tab: Silhouette Cameo SVG cut/draw and print-and-cut, over USB.

MIT-licensed, same as the rest of the GUI. The actual cutter protocol runs
in a separate subprocess -- see linuxprint/plotter/vendor/inkscape_silhouette/
NOTICE.md for why (GPL-2.0 vendored driver, MIT app).
"""

from __future__ import annotations

import os
import tempfile

from PyQt6.QtCore import QPointF, Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
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

# CSS/SVG default: 96 px (our raster background's assumed unit, absent
# other information) per inch, 25.4mm per inch.
_DEFAULT_RASTER_DPI = 96.0

_CUT_COLOR = "#e53935"
_DRAW_COLOR = "#333333"
_REGMARK_COLOR = "#1565c0"


def _read_png_dpi(path: str) -> float:
    """Best-effort read of a PNG's own declared DPI (many design tools
    write one, e.g. 300 for print-ready assets); 96 (the CSS/web default)
    when Pillow isn't installed or the file doesn't declare one."""
    try:
        from PIL import Image
    except ImportError:
        return _DEFAULT_RASTER_DPI
    try:
        with Image.open(path) as img:
            dpi = img.info.get("dpi")
            if dpi:
                return float(dpi[0])
    except Exception:
        pass
    return _DEFAULT_RASTER_DPI


def _render_pdf_first_page(pdf_path: str, dpi: float = 200.0) -> str:
    """Render a PDF's first page to a temp PNG file and return its path.

    Uses pypdfium2 (BSD-3-Clause/Apache-2.0, both permissive -- imported
    directly into this MIT-licensed process, unlike the vendored GPL-2.0
    cutter driver which runs in its own subprocess for exactly this
    reason). PyMuPDF was deliberately not used here: despite being a
    common choice for this, it's dual-licensed under AGPL-3.0 or a paid
    Artifex commercial license, neither of which this app can adopt for a
    plain in-process import.

    An optional dependency of this one import path, not needed for
    PNG/SVG artwork -- raises ImportError if missing.
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[0]
        bitmap = page.render(scale=dpi / 72.0)  # PDF's native unit is 1/72 inch
        image = bitmap.to_pil()
        fd, out_path = tempfile.mkstemp(suffix=".png", prefix="jadiv-print-center-pdf-")
        os.close(fd)
        image.save(out_path, format="PNG")
        return out_path
    finally:
        doc.close()


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


class _DrawingView(QGraphicsView):
    """QGraphicsView that, while the owning tab is in a draw mode, lets the
    user click to place polyline points directly on the canvas. Outside a
    draw mode it behaves like a plain QGraphicsView (pan/zoom untouched)."""

    def __init__(self, scene: QGraphicsScene, owner: "PlotterTab") -> None:
        super().__init__(scene)
        self._owner = owner
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None and event.button() == Qt.MouseButton.LeftButton:
            self._owner._on_canvas_click(self.mapToScene(event.position().toPoint()))
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None and self._owner._drawing_points:
            self._owner._on_canvas_move(self.mapToScene(event.position().toPoint()))
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None:
            self._owner._finish_drawing()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._owner.draw_mode is not None:
            if event.key() == Qt.Key.Key_Escape:
                self._owner._cancel_drawing()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._owner._finish_drawing()
                return
        super().keyPressEvent(event)


class PlotterTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.parsed: ParsedSvg | None = None
        self.svg_path: str | None = None
        self.background_image_path: str | None = None
        self.background_dpi: float = _DEFAULT_RASTER_DPI
        self._thread: QThread | None = None
        self._worker: _PlotWorker | None = None

        # Manual drawing state: draw_mode is None ("select/pan"), "cut" or
        # "pen"; _drawing_points accumulates the in-progress polyline (in
        # scene coordinates) between clicks; _drawn_shapes is a simple undo
        # stack of (mode, path_mm) for shapes already committed into
        # self.parsed.
        self.draw_mode: str | None = None
        self._drawing_points: list[QPointF] = []
        self._drawing_path_item: QGraphicsPathItem | None = None
        self._drawn_shapes: list[tuple[str, list[tuple[float, float]]]] = []

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
        top_row.addWidget(load_btn)
        load_image_btn = QPushButton("Načítať obrázok (PNG/PDF)…")
        load_image_btn.clicked.connect(self._on_load_image)
        top_row.addWidget(load_image_btn)
        self.file_label = QLabel("Žiadny súbor")
        top_row.addWidget(self.file_label, 1)
        self.device_label = QLabel("Zisťujem zariadenie…")
        refresh_device_btn = QPushButton("Obnoviť zariadenie")
        refresh_device_btn.clicked.connect(self._refresh_device_status)
        top_row.addWidget(self.device_label)
        top_row.addWidget(refresh_device_btn)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.scene = QGraphicsScene()
        # Always a white drawing surface, regardless of the desktop's Qt
        # palette: on a dark system theme (common on Kubuntu), an
        # unstyled QGraphicsView paints its background from the dark
        # palette, so the preview looked like a solid black panel with
        # nothing on it -- especially since the pen-path color below is a
        # dark gray that all but disappears against a dark background.
        self.scene.setBackgroundBrush(QColor("#ffffff"))
        self.view = _DrawingView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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
        # Cameo 4/5 (PRODUCT_LINE_CAMEO4 in the vendored driver) accepts
        # speed 1-30; only older pre-Cameo-3 devices clamp to 1-10.
        self.speed_spin.setRange(1, 30)
        self.speed_spin.setValue(10)
        form.addRow("Rýchlosť:", self.speed_spin)

        self.pen_pressure_spin = QSpinBox()
        self.pen_pressure_spin.setRange(1, 33)
        self.pen_pressure_spin.setValue(18)
        form.addRow("Tlak pera:", self.pen_pressure_spin)

        controls_layout.addWidget(settings_group)

        draw_group = QGroupBox("Kresliaci nástroj")
        draw_layout = QVBoxLayout(draw_group)
        draw_layout.addWidget(QLabel("Klikaním pridávaj body, dvojklikom/Enter dokonči čiaru, Esc zruší."))
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_none_btn = QPushButton("Vybrať / posúvať")
        self.mode_none_btn.setCheckable(True)
        self.mode_none_btn.setChecked(True)
        self.mode_cut_btn = QPushButton("Kresliť rez")
        self.mode_cut_btn.setCheckable(True)
        self.mode_pen_btn = QPushButton("Kresliť pero")
        self.mode_pen_btn.setCheckable(True)
        for btn in (self.mode_none_btn, self.mode_cut_btn, self.mode_pen_btn):
            self.mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self.mode_none_btn.clicked.connect(lambda: self._on_set_draw_mode(None))
        self.mode_cut_btn.clicked.connect(lambda: self._on_set_draw_mode("cut"))
        self.mode_pen_btn.clicked.connect(lambda: self._on_set_draw_mode("pen"))
        draw_layout.addLayout(mode_row)
        edit_row = QHBoxLayout()
        undo_btn = QPushButton("Späť")
        undo_btn.clicked.connect(self._on_undo_shape)
        edit_row.addWidget(undo_btn)
        clear_btn = QPushButton("Vymazať kresbu")
        clear_btn.clicked.connect(self._on_clear_drawing)
        edit_row.addWidget(clear_btn)
        draw_layout.addLayout(edit_row)
        controls_layout.addWidget(draw_group)

        regmark_group = QGroupBox("Tlač a rez (registračné značky)")
        regmark_layout = QFormLayout(regmark_group)
        self.regmark_check = QCheckBox("Použiť registračné značky")
        self.regmark_check.toggled.connect(self._render_preview)
        regmark_layout.addRow(self.regmark_check)
        self.quad_check = QCheckBox("4 značky (rohy)")
        self.quad_check.toggled.connect(self._render_preview)
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
    # SVG / image loading + preview
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
        self.background_image_path = None
        self._drawn_shapes = []
        self._update_file_label()
        self._render_preview()
        self._set_actions_enabled(True)

    def _on_load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Načítať obrázok", "", "Obrázky (*.png *.pdf)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".pdf":
                try:
                    png_path = _render_pdf_first_page(path)
                except ImportError as exc:
                    QMessageBox.critical(
                        self,
                        "Chýba závislosť",
                        f"Import PDF vyžaduje pypdfium2 a Pillow ({exc}). Nainštaluj:\n"
                        "    python3 -m pip install --user pypdfium2 Pillow",
                    )
                    return
                self.background_image_path = png_path
                self.background_dpi = 200.0
            elif ext == ".png":
                self.background_image_path = path
                self.background_dpi = _read_png_dpi(path)
            else:
                QMessageBox.critical(self, "Nepodporovaný formát", "Podporované sú iba súbory .png a .pdf.")
                return
        except Exception as exc:
            QMessageBox.critical(self, "Chyba pri načítaní obrázka", str(exc))
            return

        # The image becomes what print-and-cut prints; any existing
        # cut/draw paths (from an earlier SVG import or hand-drawn) are
        # kept, since they describe what the cutter does, independent of
        # what gets printed.
        self.svg_path = None
        self.file_label.setText(f"{os.path.basename(path)}  (obrázok na tlač -- rezacie čiary priprav ručne)")
        self._render_preview()
        self._set_actions_enabled(True)

    def _update_file_label(self) -> None:
        if self.parsed is None:
            cut_count = draw_count = 0
        else:
            cut_count = len(self.parsed.cut_paths)
            draw_count = len(self.parsed.draw_paths)
        if self.svg_path:
            name = os.path.basename(self.svg_path)
        elif self.background_image_path:
            name = os.path.basename(self.background_image_path)
        else:
            name = "Žiadny súbor"
        self.file_label.setText(f"{name}  ({cut_count} rez. čiar, {draw_count} kresliacich čiar)")

    def _render_preview(self) -> None:
        self.scene.clear()
        # scene.clear() just deleted the QGraphicsItem the in-progress
        # drawing was using, if any -- _refresh_drawing_item() below makes
        # a fresh one when there's a drawing in progress.
        self._drawing_path_item = None

        if self.background_image_path is not None:
            pixmap = QPixmap(self.background_image_path)
            if not pixmap.isNull():
                bg_item = QGraphicsPixmapItem(pixmap)
                scale = PREVIEW_PX_PER_MM / (self.background_dpi / 25.4)
                bg_item.setScale(scale)
                bg_item.setZValue(-10)
                self.scene.addItem(bg_item)

        if self.parsed is not None:
            cut_pen = QPen(QColor(_CUT_COLOR))
            cut_pen.setWidthF(0.6)
            draw_pen = QPen(QColor(_DRAW_COLOR))
            draw_pen.setWidthF(0.6)
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

        if self.regmark_check.isChecked():
            self._render_regmark_overlay()

        if self._drawing_points:
            self._refresh_drawing_item()

        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _render_regmark_overlay(self) -> None:
        """Show where the registration-mark squares will actually print,
        using the same default RegmarkSettings placement print-and-cut
        itself uses -- so the layout can be checked before committing
        paper/material to it."""
        settings = RegmarkSettings(enabled=True, quad=self.quad_check.isChecked())
        pen = QPen(QColor(_REGMARK_COLOR))
        pen.setWidthF(0.6)
        brush = QBrush(QColor(_REGMARK_COLOR))
        brush.setStyle(Qt.BrushStyle.Dense6Pattern)
        size = regmarks.MARK_SIZE_MM * PREVIEW_PX_PER_MM
        for x_mm, y_mm in regmarks.regmark_points_mm(settings):
            rect_item = QGraphicsRectItem(x_mm * PREVIEW_PX_PER_MM, y_mm * PREVIEW_PX_PER_MM, size, size)
            rect_item.setPen(pen)
            rect_item.setBrush(brush)
            self.scene.addItem(rect_item)

    # ------------------------------------------------------------------
    # Manual line drawing
    # ------------------------------------------------------------------

    def _on_set_draw_mode(self, mode: str | None) -> None:
        self._cancel_drawing()
        self.draw_mode = mode
        if mode is not None:
            self.view.setFocus()

    def _drawing_pen(self) -> QPen:
        color = _CUT_COLOR if self.draw_mode == "cut" else _DRAW_COLOR
        pen = QPen(QColor(color))
        pen.setWidthF(0.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _refresh_drawing_item(self) -> None:
        if self._drawing_path_item is not None:
            self.scene.removeItem(self._drawing_path_item)
            self._drawing_path_item = None
        if not self._drawing_points:
            return
        path = QPainterPath()
        path.moveTo(self._drawing_points[0])
        for point in self._drawing_points[1:]:
            path.lineTo(point)
        item = QGraphicsPathItem(path)
        item.setPen(self._drawing_pen())
        item.setZValue(10)
        self.scene.addItem(item)
        self._drawing_path_item = item

    def _on_canvas_click(self, scene_pos: QPointF) -> None:
        self._drawing_points.append(scene_pos)
        self._refresh_drawing_item()

    def _on_canvas_move(self, scene_pos: QPointF) -> None:
        if not self._drawing_points:
            return
        path = QPainterPath()
        path.moveTo(self._drawing_points[0])
        for point in self._drawing_points[1:]:
            path.lineTo(point)
        path.lineTo(scene_pos)
        if self._drawing_path_item is None:
            item = QGraphicsPathItem(path)
            item.setPen(self._drawing_pen())
            item.setZValue(10)
            self.scene.addItem(item)
            self._drawing_path_item = item
        else:
            self._drawing_path_item.setPath(path)

    def _finish_drawing(self) -> None:
        if len(self._drawing_points) < 2:
            self._cancel_drawing()
            return
        path_mm = [(p.x() / PREVIEW_PX_PER_MM, p.y() / PREVIEW_PX_PER_MM) for p in self._drawing_points]
        if self.parsed is None:
            self.parsed = ParsedSvg()
        if self.draw_mode == "cut":
            self.parsed.cut_paths.append(path_mm)
        else:
            self.parsed.draw_paths.append(path_mm)
        self._drawn_shapes.append((self.draw_mode, path_mm))

        self._drawing_points = []
        if self._drawing_path_item is not None:
            self.scene.removeItem(self._drawing_path_item)
            self._drawing_path_item = None

        self._update_file_label()
        self._render_preview()
        self._set_actions_enabled(True)

    def _cancel_drawing(self) -> None:
        self._drawing_points = []
        if self._drawing_path_item is not None:
            self.scene.removeItem(self._drawing_path_item)
            self._drawing_path_item = None

    def _on_undo_shape(self) -> None:
        if not self._drawn_shapes or self.parsed is None:
            return
        kind, path_mm = self._drawn_shapes.pop()
        target = self.parsed.cut_paths if kind == "cut" else self.parsed.draw_paths
        if path_mm in target:
            target.remove(path_mm)
        self._update_file_label()
        self._render_preview()

    def _on_clear_drawing(self) -> None:
        if not self._drawn_shapes or self.parsed is None:
            return
        if (
            QMessageBox.question(self, "Vymazať kresbu", "Naozaj vymazať všetky ručne nakreslené čiary?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        for kind, path_mm in self._drawn_shapes:
            target = self.parsed.cut_paths if kind == "cut" else self.parsed.draw_paths
            if path_mm in target:
                target.remove(path_mm)
        self._drawn_shapes = []
        self._update_file_label()
        self._render_preview()

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

    def _confirm_job(self, job: PlotJob, title: str, extra_message: str = "") -> bool:
        """Show a summary of what's about to be sent to the physical
        cutter (media, path counts, speed/pressure, regmarks) and ask for
        confirmation -- cutting is irreversible and wastes material if the
        wrong settings go out."""
        _cuttingmat, width_mm, height_mm = job.resolved_media()
        lines: list[str] = []
        if extra_message:
            lines.append(extra_message)
            lines.append("")
        lines.append(f"Médium: {job.media_preset} ({width_mm:.0f} x {height_mm:.0f} mm)")
        for p in job.passes:
            tool_label = "Čepeľ" if p.tool == "blade" else "Pero"
            lines.append(f"{tool_label}: {len(p.paths)} čiar, rýchlosť {p.speed}, tlak {p.pressure}")
        if job.regmark.enabled:
            lines.append("Registračné značky: zapnuté" + (" (4 rohy)" if job.regmark.quad else ""))
        lines.append("")
        lines.append("Odoslať úlohu na zariadenie?")
        return QMessageBox.question(self, title, "\n".join(lines)) == QMessageBox.StandardButton.Yes

    def _run_job(self, job: PlotJob) -> None:
        self.log_view.append(f"Spúšťam úlohu ({len(job.passes)} prechodov)…")
        self._set_actions_enabled(False)

        thread = QThread()
        worker = _PlotWorker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_plot_event)
        worker.finished.connect(self._on_plot_finished)
        worker.failed.connect(self._on_plot_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._on_thread_finished(thread, worker))
        thread.finished.connect(thread.deleteLater)

        # Keep references so they aren't garbage-collected mid-job, but a
        # second job started before this one's thread fully quits must not
        # let this call's cleanup tear down the newer thread/worker -- see
        # _on_thread_finished's identity check.
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_thread_finished(self, thread: QThread, worker: "_PlotWorker") -> None:
        if self._thread is thread and self._worker is worker:
            self._thread = None
            self._worker = None

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
        if job is not None and self._confirm_job(job, "Vyrezať"):
            self._run_job(job)

    def _on_draw(self) -> None:
        job = self._build_job(include_cut=False, include_draw=True, regmark=False)
        if job is not None and self._confirm_job(job, "Nakresliť perom"):
            self._run_job(job)

    def _on_print_and_cut(self) -> None:
        if self.svg_path is None and self.background_image_path is None:
            return
        printer = self.printer_combo.currentText()
        if not printer:
            QMessageBox.information(self, "Chýba tlačiareň", "Vyber tlačiareň pre krok tlače.")
            return
        if (
            QMessageBox.question(
                self,
                "Tlač a rez",
                "Najprv sa vytlačí návrh s registračnými značkami. Po vytlačení vlož "
                "list na rezaciu podložku (zarovnaný podľa značiek) a pokračuj rezaním.\n\n"
                "Vytlačiť teraz?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        regmark_settings = RegmarkSettings(enabled=True, quad=self.quad_check.isChecked())
        try:
            if self.background_image_path is not None:
                merged_path = regmarks.merge_raster_with_regmarks(
                    self.background_image_path, regmark_settings, dpi=self.background_dpi
                )
            else:
                merged_path = regmarks.merge_svg_with_regmarks(self.svg_path, regmark_settings)
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Chýba závislosť",
                f"Tlač obrázka s registračnými značkami vyžaduje Pillow ({exc}).\n"
                "Nainštaluj: python3 -m pip install --user Pillow",
            )
            return

        result = cups_cli.submit_print_job(printer, merged_path, title="Jadiv Print Center - tlač a rez")
        if not result.ok:
            QMessageBox.critical(self, "Tlač zlyhala", result.stderr or "Neznáma chyba lp.")
            return

        job = self._build_job(include_cut=True, include_draw=False, regmark=True)
        if job is None:
            return
        if not self._confirm_job(
            job,
            "Pokračovať rezom",
            extra_message=(
                "List je vytlačený. Po umiestnení na rezaciu podložku pokračuj rezom "
                "(zariadenie samo nájde registračné značky)."
            ),
        ):
            return
        self._run_job(job)
