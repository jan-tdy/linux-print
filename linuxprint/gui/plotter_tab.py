"""Plotter tab: Silhouette Cameo SVG cut/draw and print-and-cut, over USB.

MIT-licensed, same as the rest of the GUI. The actual cutter protocol runs
in a separate subprocess -- see linuxprint/plotter/vendor/inkscape_silhouette/
NOTICE.md for why (GPL-2.0 vendored driver, MIT app).
"""

from __future__ import annotations

import base64
import math
import os
import tempfile

from PyQt6.QtCore import QPointF, Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QLineEdit,
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
from ..plotter.job import DEFAULT_MEDIA_PRESET, MEDIA_PRESETS, PlotJob, RegmarkSettings, ToolPass
from ..plotter.project import Project, ProjectBackgroundImage, load_project, save_project
from ..plotter.svg_import import ParsedSvg, export_svg, parse_svg

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

# Margin kept clear around the registration marks, and the minimum length a
# roll-fed cut is given past the last path -- both in mm.
_REGMARK_MARGIN_MM = 15.0
_ROLL_LENGTH_MARGIN_MM = 20.0

# Shape catalog: display label -> internal kind used by _shape_outline_points.
SHAPE_KINDS: dict[str, str] = {
    "Freehand": "freehand",
    "Square": "square",
    "Circle": "circle",
    "Rectangle": "rectangle",
    "Triangle": "triangle",
}


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
                value = float(dpi[0])
                # A malformed/degenerate pHYs chunk (e.g. 0 pixels-per-unit)
                # would otherwise become a background_dpi of 0, and
                # _render_preview's PREVIEW_PX_PER_MM / (dpi / 25.4) divides
                # by it -- a ZeroDivisionError crash on preview render, not
                # just a wrong-looking image.
                if math.isfinite(value) and value > 0:
                    return value
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
        # Preserve dpi so a later print (via cups_cli.submit_print_job's
        # ppi=...) and the regmark math both agree on this image's
        # physical size -- otherwise CUPS would fall back to its own
        # default DPI, printing at a different physical scale than the
        # rendering above assumed.
        image.save(out_path, format="PNG", dpi=(dpi, dpi))
        return out_path
    finally:
        doc.close()


def _roll_cut_length_mm(points: list[tuple[float, float]]) -> float:
    """Cut length for roll-fed vinyl: there's no fixed sheet height to look
    up, so it's computed from how far down the given points (the design
    actually being processed) reach, plus a margin."""
    max_y = max((y for _, y in points), default=0.0)
    return max(max_y + _ROLL_LENGTH_MARGIN_MM, 50.0)


def _regmark_settings_for_canvas(width_mm: float, height_mm: float, quad: bool) -> RegmarkSettings:
    """Scale the registration-mark layout to fit the given canvas size,
    instead of a fixed page-sized default that a smaller custom image (or a
    roll-vinyl cut, whose length is only known from the design) can't hold.
    """
    margin = _REGMARK_MARGIN_MM
    usable_width = max(width_mm - 2 * margin, regmarks.MARK_SIZE_MM)
    usable_height = max(height_mm - 2 * margin, regmarks.MARK_SIZE_MM)
    return RegmarkSettings(
        enabled=True,
        quad=quad,
        origin_x_mm=margin,
        origin_y_mm=margin,
        width_mm=usable_width,
        length_mm=usable_height,
    )


def _shape_outline_points(kind: str, start: QPointF, end: QPointF) -> list[tuple[float, float]]:
    """Return a closed outline (in the same coordinate space as start/end)
    for dragging out a shape from start to end. "square"/"circle" force a
    1:1 aspect ratio (anchored at start, sized by the larger of dx/dy)."""
    x0, y0 = start.x(), start.y()
    x1, y1 = end.x(), end.y()
    if kind in ("square", "circle"):
        side = max(abs(x1 - x0), abs(y1 - y0))
        x1 = x0 + (side if x1 >= x0 else -side)
        y1 = y0 + (side if y1 >= y0 else -side)
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    if right - left < 1e-6 or bottom - top < 1e-6:
        return []
    if kind == "circle":
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = (right - left) / 2, (bottom - top) / 2
        steps = 48
        return [
            (cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps))
            for i in range(steps + 1)
        ]
    if kind == "triangle":
        mid_x = (left + right) / 2
        return [(mid_x, top), (left, bottom), (right, bottom), (mid_x, top)]
    # square and rectangle share the same 4-corner outline
    return [(left, top), (right, top), (right, bottom), (left, bottom), (left, top)]


def _text_outline_paths(text: str, height_mm: float) -> list[list[tuple[float, float]]]:
    """Turn a text string into closed outline paths (one per glyph contour,
    including inner contours like the hole in an "O"), scaled to the given
    cap height in mm, anchored with its top-left corner at the origin.

    Uses QPainterPath.addText's own font outline (glyphs, not just their
    bounding boxes), flattened into polylines via toSubpathPolygons -- this
    keeps text a plain vector path like everything else in this tool, so it
    merges straight into the same cut_paths/draw_paths a cutter reads.
    """
    font = QFont("Sans Serif")
    font.setPointSizeF(100.0)  # arbitrary reference size; only used to compute a scale factor
    outline = QPainterPath()
    outline.addText(0, 0, font, text)
    bounds = outline.boundingRect()
    if bounds.height() <= 0:
        return []
    scale = height_mm / bounds.height()
    paths: list[list[tuple[float, float]]] = []
    for polygon in outline.toSubpathPolygons():
        path = [
            ((polygon.at(i).x() - bounds.left()) * scale, (polygon.at(i).y() - bounds.top()) * scale)
            for i in range(polygon.count())
        ]
        if len(path) >= 2:
            paths.append(path)
    return paths


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
    user place a freehand polyline, drag out a catalog shape, or place a
    text outline directly on the canvas. Outside a draw mode it behaves
    like a plain QGraphicsView (pan/zoom untouched)."""

    def __init__(self, scene: QGraphicsScene, owner: "PlotterTab") -> None:
        super().__init__(scene)
        self._owner = owner
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._owner.tool == "freehand":
                self._owner._on_canvas_click(scene_pos)
            elif self._owner.tool == "text":
                self._owner._on_text_click(scene_pos)
            else:
                self._owner._on_shape_press(scene_pos)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._owner.tool == "freehand" and self._owner._drawing_points:
                self._owner._on_canvas_move(scene_pos)
                return
            if self._owner.tool not in ("freehand", "text") and self._owner._shape_start is not None:
                self._owner._on_shape_move(scene_pos)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self._owner.draw_mode is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self._owner.tool not in ("freehand", "text")
            and self._owner._shape_start is not None
        ):
            self._owner._on_shape_release(self.mapToScene(event.position().toPoint()))
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._owner.draw_mode is not None and self._owner.tool == "freehand":
            self._owner._finish_drawing()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._owner.draw_mode is not None:
            if event.key() == Qt.Key.Key_Escape:
                self._owner._cancel_drawing()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._owner.tool == "freehand":
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
        # "pen" (which line list a committed shape goes into); tool picks
        # the interaction style within a draw mode -- "freehand" (click
        # multiple points), a shape catalog kind (drag out a bounding box),
        # or "text" (single click places a pre-typed text outline).
        # _drawn_shapes is a simple undo stack of (mode, path_mm) for shapes
        # already committed into self.parsed.
        self.draw_mode: str | None = None
        self.tool: str = "freehand"
        self._drawing_points: list[QPointF] = []
        self._drawing_path_item: QGraphicsPathItem | None = None
        self._shape_start: QPointF | None = None
        self._shape_preview_item: QGraphicsPathItem | None = None
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
        load_btn = QPushButton("Load SVG…")
        load_btn.clicked.connect(self._on_load_svg)
        top_row.addWidget(load_btn)
        load_image_btn = QPushButton("Load image (PNG/PDF)…")
        load_image_btn.clicked.connect(self._on_load_image)
        top_row.addWidget(load_image_btn)
        save_project_btn = QPushButton("Save project…")
        save_project_btn.clicked.connect(self._on_save_project)
        top_row.addWidget(save_project_btn)
        open_project_btn = QPushButton("Open project…")
        open_project_btn.clicked.connect(self._on_open_project)
        top_row.addWidget(open_project_btn)
        self.file_label = QLabel("No file")
        top_row.addWidget(self.file_label, 1)
        self.device_label = QLabel("Detecting device…")
        refresh_device_btn = QPushButton("Refresh device")
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

        settings_group = QGroupBox("Cut settings")
        form = QFormLayout(settings_group)

        self.media_combo = QComboBox()
        self.media_combo.addItems(sorted(MEDIA_PRESETS.keys()))
        self.media_combo.currentTextChanged.connect(self._on_media_changed)
        form.addRow("Media:", self.media_combo)

        self.roll_width_spin = QDoubleSpinBox()
        self.roll_width_spin.setRange(50.0, 1600.0)
        self.roll_width_spin.setValue(304.8)
        self.roll_width_spin.setSuffix(" mm")
        self.roll_width_spin.setEnabled(False)
        form.addRow("Roll width (if 'roll_vinyl'):", self.roll_width_spin)

        self.pressure_spin = QSpinBox()
        self.pressure_spin.setRange(1, 33)
        self.pressure_spin.setValue(27)
        form.addRow("Blade pressure:", self.pressure_spin)

        self.speed_spin = QSpinBox()
        # Cameo 4/5 (PRODUCT_LINE_CAMEO4 in the vendored driver) accepts
        # speed 1-30; only older pre-Cameo-3 devices clamp to 1-10.
        self.speed_spin.setRange(1, 30)
        self.speed_spin.setValue(10)
        form.addRow("Speed:", self.speed_spin)

        self.pen_pressure_spin = QSpinBox()
        self.pen_pressure_spin.setRange(1, 33)
        self.pen_pressure_spin.setValue(18)
        form.addRow("Pen pressure:", self.pen_pressure_spin)

        controls_layout.addWidget(settings_group)

        draw_group = QGroupBox("Drawing tool")
        draw_layout = QVBoxLayout(draw_group)
        draw_layout.addWidget(
            QLabel(
                "Freehand: click to add points, double-click/Enter to finish, Esc cancels.\n"
                "A shape below is drawn by dragging instead (square/circle keep a 1:1 ratio)."
            )
        )
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_none_btn = QPushButton("Select / pan")
        self.mode_none_btn.setCheckable(True)
        self.mode_none_btn.setChecked(True)
        self.mode_cut_btn = QPushButton("Draw cut")
        self.mode_cut_btn.setCheckable(True)
        self.mode_pen_btn = QPushButton("Draw pen")
        self.mode_pen_btn.setCheckable(True)
        for btn in (self.mode_none_btn, self.mode_cut_btn, self.mode_pen_btn):
            self.mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self.mode_none_btn.clicked.connect(lambda: self._on_set_draw_mode(None))
        self.mode_cut_btn.clicked.connect(lambda: self._on_set_draw_mode("cut"))
        self.mode_pen_btn.clicked.connect(lambda: self._on_set_draw_mode("pen"))
        draw_layout.addLayout(mode_row)

        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape:"))
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(list(SHAPE_KINDS.keys()))
        self.shape_combo.currentTextChanged.connect(self._on_shape_kind_changed)
        shape_row.addWidget(self.shape_combo, 1)
        draw_layout.addLayout(shape_row)

        edit_row = QHBoxLayout()
        undo_btn = QPushButton("Undo")
        undo_btn.clicked.connect(self._on_undo_shape)
        edit_row.addWidget(undo_btn)
        clear_btn = QPushButton("Clear drawing")
        clear_btn.clicked.connect(self._on_clear_drawing)
        edit_row.addWidget(clear_btn)
        draw_layout.addLayout(edit_row)
        controls_layout.addWidget(draw_group)

        text_group = QGroupBox("Text")
        text_layout = QFormLayout(text_group)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Text to cut/draw")
        text_layout.addRow("Text:", self.text_input)
        self.text_height_spin = QDoubleSpinBox()
        self.text_height_spin.setRange(2.0, 500.0)
        self.text_height_spin.setValue(20.0)
        self.text_height_spin.setSuffix(" mm")
        text_layout.addRow("Height:", self.text_height_spin)
        add_text_btn = QPushButton("Add text (click on canvas)")
        add_text_btn.clicked.connect(self._on_add_text_clicked)
        text_layout.addRow(add_text_btn)
        controls_layout.addWidget(text_group)

        regmark_group = QGroupBox("Print & cut (registration marks)")
        regmark_layout = QFormLayout(regmark_group)
        self.regmark_check = QCheckBox("Use registration marks")
        self.regmark_check.toggled.connect(self._render_preview)
        regmark_layout.addRow(self.regmark_check)
        self.quad_check = QCheckBox("4 marks (corners)")
        self.quad_check.toggled.connect(self._render_preview)
        regmark_layout.addRow(self.quad_check)
        self.printer_combo = QComboBox()
        regmark_layout.addRow("Printer:", self.printer_combo)
        controls_layout.addWidget(regmark_group)

        buttons_group = QGroupBox("Actions")
        buttons_layout = QVBoxLayout(buttons_group)
        self.cut_btn = QPushButton("Cut (red lines)")
        self.cut_btn.clicked.connect(self._on_cut)
        buttons_layout.addWidget(self.cut_btn)
        self.draw_btn = QPushButton("Draw with pen (other lines)")
        self.draw_btn.clicked.connect(self._on_draw)
        buttons_layout.addWidget(self.draw_btn)
        self.cut_and_draw_btn = QPushButton("Cut + draw (both tools)")
        self.cut_and_draw_btn.clicked.connect(self._on_cut_and_draw)
        buttons_layout.addWidget(self.cut_and_draw_btn)
        self.print_btn = QPushButton("Print…")
        self.print_btn.clicked.connect(self._on_print_only)
        buttons_layout.addWidget(self.print_btn)
        controls_layout.addWidget(buttons_group)

        controls_layout.addStretch(1)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        layout.addWidget(QLabel("Plotter log:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        layout.addWidget(self.log_view)

        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self.cut_btn, self.draw_btn, self.cut_and_draw_btn, self.print_btn):
            btn.setEnabled(enabled)

    def _on_media_changed(self, text: str) -> None:
        self.roll_width_spin.setEnabled(text == "roll_vinyl")

    # ------------------------------------------------------------------
    # SVG / image loading + preview
    # ------------------------------------------------------------------

    def _on_load_svg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load SVG", "", "SVG files (*.svg)")
        if not path:
            return
        try:
            self.parsed = parse_svg(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error loading SVG", str(exc))
            return
        self.svg_path = path
        self.background_image_path = None
        self._drawn_shapes = []
        self._update_file_label()
        self._render_preview()
        self._set_actions_enabled(True)

    def _on_load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load image", "", "Images (*.png *.pdf)")
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
                        "Missing dependency",
                        f"PDF import requires pypdfium2 and Pillow ({exc}). Install:\n"
                        "    python3 -m pip install --user pypdfium2 Pillow",
                    )
                    return
                self.background_image_path = png_path
                self.background_dpi = 200.0
            elif ext == ".png":
                self.background_image_path = path
                self.background_dpi = _read_png_dpi(path)
            else:
                QMessageBox.critical(self, "Unsupported format", "Only .png and .pdf files are supported.")
                return
        except Exception as exc:
            QMessageBox.critical(self, "Error loading image", str(exc))
            return

        # The image becomes what print-and-cut prints; any existing
        # cut/draw paths (from an earlier SVG import or hand-drawn) are
        # kept, since they describe what the cutter does, independent of
        # what gets printed.
        self.svg_path = None
        self.file_label.setText(f"{os.path.basename(path)}  (image to print -- prepare cut lines manually)")
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
            name = "No file"
        self.file_label.setText(f"{name}  ({cut_count} cut lines, {draw_count} draw lines)")

    def _current_canvas_size_mm(self) -> tuple[float, float]:
        """Physical size of whatever is actually being printed/cut, in mm:
        the background raster's size at its own DPI, the imported SVG's own
        declared size, or (with neither) the current media preset's sheet
        size -- used to scale the registration-mark layout to fit, instead
        of a fixed A4-sized default that a small custom image can't hold.

        roll_vinyl is checked first and unconditionally: it has no fixed
        sheet size of its own (MEDIA_PRESETS only holds a nominal
        placeholder for it), so the real size is always the configured roll
        width and the design's own height, never a background/SVG size."""
        if self.media_combo.currentText() == "roll_vinyl":
            all_points = (
                [point for path in (*self.parsed.cut_paths, *self.parsed.draw_paths) for point in path]
                if self.parsed is not None
                else []
            )
            return self.roll_width_spin.value(), _roll_cut_length_mm(all_points)
        if self.background_image_path is not None:
            pixmap = QPixmap(self.background_image_path)
            if not pixmap.isNull() and self.background_dpi > 0:
                px_per_mm = self.background_dpi / 25.4
                return pixmap.width() / px_per_mm, pixmap.height() / px_per_mm
        if self.parsed is not None and self.parsed.width_mm > 0 and self.parsed.height_mm > 0:
            return self.parsed.width_mm, self.parsed.height_mm
        _cuttingmat, width_mm, height_mm = MEDIA_PRESETS.get(
            self.media_combo.currentText(), MEDIA_PRESETS[DEFAULT_MEDIA_PRESET]
        )
        return width_mm, height_mm

    def _regmark_settings(self) -> RegmarkSettings:
        """Build the registration-mark layout actually used for both the
        preview overlay and the real print/cut steps, scaled to the current
        canvas size rather than a fixed page size -- a small custom image
        would otherwise be smaller than the marks' fixed default layout."""
        if not self.regmark_check.isChecked():
            return RegmarkSettings(enabled=False)
        width_mm, height_mm = self._current_canvas_size_mm()
        return _regmark_settings_for_canvas(width_mm, height_mm, quad=self.quad_check.isChecked())

    def _render_preview(self) -> None:
        self.scene.clear()
        # scene.clear() just deleted the QGraphicsItem the in-progress
        # drawing/shape was using, if any -- the block below makes a fresh
        # one when there's a drawing or shape drag in progress.
        self._drawing_path_item = None
        self._shape_preview_item = None

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
        using the same settings the real print/cut steps compute -- so the
        layout can be checked before committing paper/material to it."""
        settings = self._regmark_settings()
        if not settings.enabled:
            return
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
    # Manual drawing: freehand lines, catalog shapes, text
    # ------------------------------------------------------------------

    def _on_set_draw_mode(self, mode: str | None) -> None:
        self._cancel_drawing()
        self.draw_mode = mode
        if mode is not None:
            self.view.setFocus()

    def _on_shape_kind_changed(self, label: str) -> None:
        self._cancel_drawing()
        self.tool = SHAPE_KINDS.get(label, "freehand")

    def _drawing_pen(self) -> QPen:
        color = _CUT_COLOR if self.draw_mode == "cut" else _DRAW_COLOR
        pen = QPen(QColor(color))
        pen.setWidthF(0.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _commit_path(self, path_mm: list[tuple[float, float]]) -> None:
        if self.parsed is None:
            self.parsed = ParsedSvg()
        target = self.parsed.cut_paths if self.draw_mode == "cut" else self.parsed.draw_paths
        target.append(path_mm)
        self._drawn_shapes.append((self.draw_mode, path_mm))
        self._update_file_label()
        self._render_preview()
        self._set_actions_enabled(True)

    # -- freehand polyline --

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
        self._drawing_points = []
        if self._drawing_path_item is not None:
            self.scene.removeItem(self._drawing_path_item)
            self._drawing_path_item = None
        self._commit_path(path_mm)

    # -- catalog shapes (drag to size) --

    def _on_shape_press(self, scene_pos: QPointF) -> None:
        self._shape_start = scene_pos

    def _on_shape_move(self, scene_pos: QPointF) -> None:
        if self._shape_start is None:
            return
        points = _shape_outline_points(self.tool, self._shape_start, scene_pos)
        path = QPainterPath()
        if points:
            path.moveTo(points[0][0], points[0][1])
            for x, y in points[1:]:
                path.lineTo(x, y)
        if self._shape_preview_item is None:
            item = QGraphicsPathItem(path)
            item.setPen(self._drawing_pen())
            item.setZValue(10)
            self.scene.addItem(item)
            self._shape_preview_item = item
        else:
            self._shape_preview_item.setPath(path)

    def _on_shape_release(self, scene_pos: QPointF) -> None:
        if self._shape_start is None:
            return
        points = _shape_outline_points(self.tool, self._shape_start, scene_pos)
        self._shape_start = None
        if self._shape_preview_item is not None:
            self.scene.removeItem(self._shape_preview_item)
            self._shape_preview_item = None
        if len(points) < 3:
            return
        path_mm = [(x / PREVIEW_PX_PER_MM, y / PREVIEW_PX_PER_MM) for x, y in points]
        self._commit_path(path_mm)

    # -- text --

    def _on_add_text_clicked(self) -> None:
        if self.draw_mode is None:
            QMessageBox.information(self, "Choose a mode", "First choose 'Draw cut' or 'Draw pen'.")
            return
        if not self.text_input.text().strip():
            QMessageBox.information(self, "Missing text", "Enter the text to add.")
            return
        self.tool = "text"
        self.view.setFocus()

    def _on_text_click(self, scene_pos: QPointF) -> None:
        text = self.text_input.text().strip()
        if text:
            origin_mm = (scene_pos.x() / PREVIEW_PX_PER_MM, scene_pos.y() / PREVIEW_PX_PER_MM)
            if self.parsed is None:
                self.parsed = ParsedSvg()
            target = self.parsed.cut_paths if self.draw_mode == "cut" else self.parsed.draw_paths
            for glyph_path in _text_outline_paths(text, self.text_height_spin.value()):
                path_mm = [(origin_mm[0] + x, origin_mm[1] + y) for x, y in glyph_path]
                target.append(path_mm)
                self._drawn_shapes.append((self.draw_mode, path_mm))
            self._update_file_label()
            self._render_preview()
            self._set_actions_enabled(True)
        self.tool = "freehand"
        self.shape_combo.setCurrentText("Freehand")

    # -- shared cancel/undo/clear --

    def _cancel_drawing(self) -> None:
        self._drawing_points = []
        if self._drawing_path_item is not None:
            self.scene.removeItem(self._drawing_path_item)
            self._drawing_path_item = None
        self._shape_start = None
        if self._shape_preview_item is not None:
            self.scene.removeItem(self._shape_preview_item)
            self._shape_preview_item = None
        if self.tool == "text":
            self.tool = "freehand"
            self.shape_combo.setCurrentText("Freehand")

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
            QMessageBox.question(self, "Clear drawing", "Really delete all hand-drawn lines?")
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
    # Project save/load
    # ------------------------------------------------------------------

    def _on_save_project(self) -> None:
        if self.parsed is None and self.background_image_path is None:
            QMessageBox.information(self, "Nothing to save", "Load or draw something first.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save project", "", "Jadiv Print Center project (*.jpcp);;SVG file (*.svg)"
        )
        if not path:
            return
        want_svg = path.lower().endswith(".svg") or (
            not path.lower().endswith(".jpcp") and "svg" in selected_filter.lower()
        )
        try:
            if want_svg:
                if not path.lower().endswith(".svg"):
                    path += ".svg"
                export_svg(self.parsed or ParsedSvg(), path)
            else:
                if not path.lower().endswith(".jpcp"):
                    path += ".jpcp"
                background = None
                if self.background_image_path is not None:
                    with open(self.background_image_path, "rb") as fh:
                        background = ProjectBackgroundImage(
                            dpi=self.background_dpi, data_base64=base64.b64encode(fh.read()).decode("ascii")
                        )
                project = Project(
                    cut_paths=(self.parsed.cut_paths if self.parsed else []),
                    draw_paths=(self.parsed.draw_paths if self.parsed else []),
                    media_preset=self.media_combo.currentText(),
                    pressure=self.pressure_spin.value(),
                    speed=self.speed_spin.value(),
                    pen_pressure=self.pen_pressure_spin.value(),
                    regmark_enabled=self.regmark_check.isChecked(),
                    regmark_quad=self.quad_check.isChecked(),
                    roll_width_mm=self.roll_width_spin.value(),
                    background=background,
                )
                save_project(project, path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.log_view.append(f"Project saved: {os.path.basename(path)}")

    def _on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "Jadiv Print Center project (*.jpcp)")
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error opening project", str(exc))
            return

        self.parsed = ParsedSvg(cut_paths=project.cut_paths, draw_paths=project.draw_paths)
        self.svg_path = None
        self._drawn_shapes = []

        if project.background is not None:
            fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="jadiv-print-center-project-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(base64.b64decode(project.background.data_base64))
            self.background_image_path = tmp_path
            self.background_dpi = project.background.dpi
        else:
            self.background_image_path = None
            self.background_dpi = _DEFAULT_RASTER_DPI

        index = self.media_combo.findText(project.media_preset)
        if index >= 0:
            self.media_combo.setCurrentIndex(index)
        self.pressure_spin.setValue(project.pressure)
        self.speed_spin.setValue(project.speed)
        self.pen_pressure_spin.setValue(project.pen_pressure)
        self.regmark_check.setChecked(project.regmark_enabled)
        self.quad_check.setChecked(project.regmark_quad)
        self.roll_width_spin.setValue(project.roll_width_mm)

        self._update_file_label()
        self._render_preview()
        self._set_actions_enabled(True)
        self.log_view.append(f"Project loaded: {os.path.basename(path)}")

    # ------------------------------------------------------------------
    # Device / printer status
    # ------------------------------------------------------------------

    def _refresh_device_status(self) -> None:
        status = detect.detect_cameo()
        if status.connected:
            self.device_label.setText(f"Connected: {status.name}")
        elif status.error:
            self.device_label.setText(f"Device: {status.error}")
        else:
            self.device_label.setText("Device not found (check USB cable)")

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
            QMessageBox.information(self, "Nothing to process", "The SVG contains no lines of this type.")
            return None

        media_preset = self.media_combo.currentText()
        media_width_mm: float | None = None
        media_height_mm: float | None = None
        if media_preset == "roll_vinyl":
            # Matless/roll-fed vinyl has no fixed sheet size: use the
            # configured roll width, and let the cut length follow the
            # actual design instead of a guessed fixed sheet height. Uses
            # only this job's own passes (e.g. a cut-only job ignores pen
            # paths that extend further down) -- _current_canvas_size_mm
            # uses the whole design instead, since that's what's shown in
            # the shared preview regardless of which job is about to run.
            media_width_mm = self.roll_width_spin.value()
            all_points = [point for p in passes for path in p.paths for point in path]
            media_height_mm = _roll_cut_length_mm(all_points)

        # _regmark_settings() itself already resolves roll_vinyl's marks
        # against the roll width and the whole design's height (see
        # _current_canvas_size_mm), so the marks on the physical cut agree
        # with what the registration-mark preview showed beforehand.
        regmark_settings = self._regmark_settings() if regmark else RegmarkSettings(enabled=False)
        return PlotJob(
            passes=passes,
            media_preset=media_preset,
            media_width_mm=media_width_mm,
            media_height_mm=media_height_mm,
            regmark=regmark_settings,
        )

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
        lines.append(f"Media: {job.media_preset} ({width_mm:.0f} x {height_mm:.0f} mm)")
        if job.media_preset == "roll_vinyl":
            lines.append("(roll length is auto-fit to the design + 20mm margin)")
        for p in job.passes:
            tool_label = "Blade" if p.tool == "blade" else "Pen"
            lines.append(f"{tool_label}: {len(p.paths)} lines, speed {p.speed}, pressure {p.pressure}")
        if job.regmark.enabled:
            lines.append("Registration marks: on" + (" (4 corners)" if job.regmark.quad else ""))
        lines.append("")
        lines.append("Send job to device?")
        return QMessageBox.question(self, title, "\n".join(lines)) == QMessageBox.StandardButton.Yes

    def _run_job(self, job: PlotJob) -> None:
        self.log_view.append(f"Running job ({len(job.passes)} passes)…")
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
            self.log_view.append(f"Pass {event.index}: tool {event.tool}")
        elif event.kind == "pass_done":
            self.log_view.append(f"Pass {event.index} done")

    def _on_plot_finished(self, event: PlotEvent) -> None:
        self._set_actions_enabled(True)
        if event.kind == "error":
            self.log_view.append(f"ERROR: {event.message}")
            QMessageBox.critical(self, "Cutting failed", event.message or "Unknown plotter error.")
        else:
            self.log_view.append("Done.")

    def _on_plot_failed(self, message: str) -> None:
        self._set_actions_enabled(True)
        self.log_view.append(f"ERROR: {message}")
        QMessageBox.critical(self, "Cutting failed", message)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_cut(self) -> None:
        job = self._build_job(include_cut=True, include_draw=False, regmark=self.regmark_check.isChecked())
        if job is not None and self._confirm_job(job, "Cut"):
            self._run_job(job)

    def _on_draw(self) -> None:
        job = self._build_job(include_cut=False, include_draw=True, regmark=self.regmark_check.isChecked())
        if job is not None and self._confirm_job(job, "Draw with pen"):
            self._run_job(job)

    def _on_cut_and_draw(self) -> None:
        job = self._build_job(include_cut=True, include_draw=True, regmark=self.regmark_check.isChecked())
        if job is not None and self._confirm_job(job, "Cut + draw"):
            self._run_job(job)

    def _on_print_only(self) -> None:
        """Print the design (with registration marks when enabled) to a
        regular printer -- a separate step from cutting, so a sheet can be
        reprinted or a cut retried independently instead of always chaining
        the two together."""
        if self.svg_path is None and self.background_image_path is None:
            QMessageBox.information(self, "Nothing to print", "Load or draw an SVG/PNG/PDF first.")
            return
        printer = self.printer_combo.currentText()
        if not printer:
            QMessageBox.information(self, "No printer selected", "Choose a printer for the print step.")
            return

        regmark_settings = self._regmark_settings()
        message = "This prints the design"
        if regmark_settings.enabled:
            message += " with registration marks"
        message += ". Print now?"
        if QMessageBox.question(self, "Print", message) != QMessageBox.StandardButton.Yes:
            return

        ppi: int | None = None
        try:
            if self.background_image_path is not None:
                if regmark_settings.enabled:
                    merged_path = regmarks.merge_raster_with_regmarks(
                        self.background_image_path, regmark_settings, dpi=self.background_dpi
                    )
                else:
                    merged_path = self.background_image_path
                # Tell CUPS explicitly what DPI this raster was produced
                # at -- otherwise it falls back to any (possibly
                # different) DPI embedded in the file or its own default,
                # printing at the wrong physical scale.
                ppi = round(self.background_dpi)
            elif self.svg_path is not None:
                merged_path = (
                    regmarks.merge_svg_with_regmarks(self.svg_path, regmark_settings)
                    if regmark_settings.enabled
                    else self.svg_path
                )
            else:
                return
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Missing dependency",
                f"Printing a raster image with registration marks requires Pillow ({exc}).\n"
                "Install: python3 -m pip install --user Pillow",
            )
            return
        except ValueError as exc:
            QMessageBox.critical(self, "Image is too small", str(exc))
            return

        result = cups_cli.submit_print_job(printer, merged_path, title="Jadiv Print Center - print", ppi=ppi)
        # submit_print_job runs `lp` to completion (it's a synchronous
        # subprocess call), and CUPS copies/spools the file as part of that
        # same call -- so once it returns, a merged_path that isn't the
        # user's own original artwork is a temp file this function created
        # and is done with, regardless of whether the submission succeeded.
        if merged_path not in (self.background_image_path, self.svg_path):
            try:
                os.remove(merged_path)
            except OSError:
                pass
        if not result.ok:
            QMessageBox.critical(self, "Print failed", result.stderr or "Unknown lp error.")
            return
        self.log_view.append("Print job sent.")
