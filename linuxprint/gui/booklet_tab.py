"""Booklet tab: turn a PDF into an A5 booklet imposed 2-up on A4 sheets,
in saddle-stitch (center-fold, stapled) page order.

Rendering (pypdfium2 + Pillow) lives in linuxprint/booklet.py; this file
is just the PyQt6 wiring -- load a PDF, show the computed sheet layout,
export the imposed PDF, or send it straight to a printer with the right
duplex option.
"""

from __future__ import annotations

import os
import tempfile

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import cups_cli
from ..booklet import BookletLayout, build_booklet_pdf, compute_layout

_DUPLEX_OPTIONS: dict[str, str] = {
    "Short edge (usual for landscape/booklet pages)": "two-sided-short-edge",
    "Long edge": "two-sided-long-edge",
}


class BookletTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.source_pdf_path: str | None = None
        self.source_page_count: int | None = None
        self._build_ui()
        self._refresh_printers()
        self._update_layout_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        load_btn = QPushButton("Load PDF…")
        load_btn.clicked.connect(self._on_load_pdf)
        top_row.addWidget(load_btn)
        self.file_label = QLabel("No file loaded")
        top_row.addWidget(self.file_label, 1)
        outer_layout.addLayout(top_row)

        # The settings/actions column below can grow tall (several group
        # boxes stacked), so it's wrapped in a scroll area -- otherwise Qt
        # would refuse to shrink the main window below the sum of their
        # minimum heights, which can exceed a smaller monitor's usable
        # screen space (see main_window.py's _initial_window_size and the
        # same fix applied to the Plotter tab).
        content = QWidget()
        content_layout = QVBoxLayout(content)

        explanation = QLabel(
            "Loads a normal, single-page-per-sheet PDF and re-lays it out as an "
            "A5 booklet printed 2-up on A4 sheets, in saddle-stitch order: print "
            "double-sided, stack the sheets in the order they come out of the "
            "printer, fold the whole stack in half once, and staple through the "
            "fold. Pages then read 1, 2, 3, ... in order."
        )
        explanation.setWordWrap(True)
        content_layout.addWidget(explanation)

        layout_group = QGroupBox("Layout")
        layout_form = QFormLayout(layout_group)
        self.layout_label = QLabel("-")
        layout_form.addRow("Sheets needed:", self.layout_label)
        content_layout.addWidget(layout_group)

        settings_group = QGroupBox("Rendering")
        settings_form = QFormLayout(settings_group)
        self.dpi_spin = QDoubleSpinBox()
        self.dpi_spin.setRange(72.0, 600.0)
        self.dpi_spin.setDecimals(0)
        self.dpi_spin.setValue(300.0)
        self.dpi_spin.setSuffix(" dpi")
        settings_form.addRow("Rendering resolution:", self.dpi_spin)
        content_layout.addWidget(settings_group)

        print_group = QGroupBox("Duplex printing")
        print_form = QFormLayout(print_group)
        self.duplex_combo = QComboBox()
        self.duplex_combo.addItems(list(_DUPLEX_OPTIONS.keys()))
        print_form.addRow("Flip on:", self.duplex_combo)
        self.rotate_back_check = QCheckBox(
            "Rotate back sides 180° (toggle this if a test booklet comes out upside-down on the inside)"
        )
        print_form.addRow(self.rotate_back_check)
        self.printer_combo = QComboBox()
        print_form.addRow("Printer:", self.printer_combo)
        refresh_printers_btn = QPushButton("Refresh printers")
        refresh_printers_btn.clicked.connect(self._refresh_printers)
        print_form.addRow(refresh_printers_btn)
        content_layout.addWidget(print_group)

        buttons_group = QGroupBox("Actions")
        buttons_layout = QVBoxLayout(buttons_group)
        self.export_btn = QPushButton("Export booklet PDF…")
        self.export_btn.clicked.connect(self._on_export)
        buttons_layout.addWidget(self.export_btn)
        self.print_btn = QPushButton("Print booklet…")
        self.print_btn.clicked.connect(self._on_print)
        buttons_layout.addWidget(self.print_btn)
        content_layout.addWidget(buttons_group)

        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        outer_layout.addWidget(QLabel("Log:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(100)
        outer_layout.addWidget(self.log_view)

        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self.export_btn, self.print_btn):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # PDF loading
    # ------------------------------------------------------------------

    def _on_load_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Missing dependency",
                f"The Booklet tab requires pypdfium2 and Pillow ({exc}). Install:\n"
                "    python3 -m pip install --user pypdfium2 Pillow",
            )
            return
        try:
            doc = pdfium.PdfDocument(path)
            try:
                page_count = len(doc)
            finally:
                doc.close()
        except Exception as exc:
            QMessageBox.critical(self, "Error loading PDF", str(exc))
            return

        self.source_pdf_path = path
        self.source_page_count = page_count
        self.file_label.setText(f"{os.path.basename(path)} ({page_count} page{'s' if page_count != 1 else ''})")
        self._update_layout_preview()
        self._set_actions_enabled(True)

    def _update_layout_preview(self) -> None:
        if self.source_page_count is None:
            self.layout_label.setText("-")
            return
        layout: BookletLayout = compute_layout(self.source_page_count)
        blanks = layout.padded_pages - layout.source_pages
        text = f"{len(layout.sheets)} A4 sheet{'s' if len(layout.sheets) != 1 else ''}, double-sided"
        if blanks:
            text += f" ({blanks} blank page{'s' if blanks != 1 else ''} padded on at the end)"
        self.layout_label.setText(text)

    # ------------------------------------------------------------------
    # Printer list
    # ------------------------------------------------------------------

    def _refresh_printers(self) -> None:
        self.printer_combo.clear()
        try:
            printers = cups_cli.list_printers()
        except cups_cli.CupsToolMissing:
            return
        self.printer_combo.addItems(sorted(printers.keys()))

    # ------------------------------------------------------------------
    # Build the imposed PDF
    # ------------------------------------------------------------------

    def _build_booklet(self, out_path: str) -> bool:
        """Run build_booklet_pdf, reporting errors via a message box.
        Returns True on success."""
        if self.source_pdf_path is None:
            return False
        try:
            layout = build_booklet_pdf(
                self.source_pdf_path,
                out_path,
                dpi=self.dpi_spin.value(),
                rotate_back=self.rotate_back_check.isChecked(),
            )
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Missing dependency",
                f"Building the booklet requires pypdfium2 and Pillow ({exc}). Install:\n"
                "    python3 -m pip install --user pypdfium2 Pillow",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(self, "Error building booklet", str(exc))
            return False
        self.log_view.append(f"Built booklet: {len(layout.sheets)} sheet(s), {layout.padded_pages} page slots.")
        return True

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        if self.source_pdf_path is None:
            return
        default_name = os.path.splitext(os.path.basename(self.source_pdf_path))[0] + "-booklet.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export booklet PDF", default_name, "PDF files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self._build_booklet(path):
            self.log_view.append(f"Exported: {path}")

    def _on_print(self) -> None:
        if self.source_pdf_path is None:
            return
        printer = self.printer_combo.currentText()
        if not printer:
            QMessageBox.information(self, "No printer selected", "Choose a printer to print to.")
            return
        if (
            QMessageBox.question(self, "Print booklet", f"Print the booklet on '{printer}' now?")
            != QMessageBox.StandardButton.Yes
        ):
            return

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="jadiv-print-center-booklet-")
        os.close(fd)
        try:
            if not self._build_booklet(tmp_path):
                return
            sides = _DUPLEX_OPTIONS[self.duplex_combo.currentText()]
            result = cups_cli.submit_print_job(
                printer,
                tmp_path,
                title="Jadiv Print Center - booklet",
                options={"sides": sides},
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not result.ok:
            QMessageBox.critical(self, "Print failed", result.stderr or "Unknown lp error.")
            return
        self.log_view.append("Booklet print job sent.")
