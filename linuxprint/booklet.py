"""Booklet imposition: turn a normal (one-page-per-sheet) PDF into an
A5 booklet printed 2-up on A4 sheets, in the page order a saddle-stitch
(center-fold, stapled) booklet needs -- so that once the sheets are
printed double-sided, stacked in printing order, folded together in the
middle and stapled through the fold, the pages read 1, 2, 3, ... in
order.

Uses pypdfium2 to rasterize each source page (same rendering path as the
Plotter tab's PDF import -- see gui/plotter_tab.py's
_render_pdf_first_page for why pypdfium2/Pillow rather than PyMuPDF) and
Pillow to compose the two-up A4 sheets and save them as a new multi-page
PDF. Both are optional dependencies (see README's Requirements section),
imported lazily so importing this module -- or computing a layout to show
in the UI before a file is even rasterized -- doesn't require them.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

# ISO 216 paper sizes, mm. A landscape A4 sheet split down the middle
# yields two A5-sized (well, 148.5x210 vs. A5's 148x210 -- close enough
# that no printer/paper-tray rounding matters) halves, which is exactly
# the two-up layout a saddle-stitch A5 booklet needs.
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
A5_WIDTH_MM = A4_HEIGHT_MM / 2
A5_HEIGHT_MM = A4_WIDTH_MM

# One booklet page slot: a 0-based index into the source PDF, or None for
# a blank page padded on at the end (when the source page count isn't a
# multiple of 4).
PageRef = int | None


@dataclass(frozen=True)
class Sheet:
    """One physical A4 sheet: the four source-page slots that land on it,
    two per side."""

    front_left: PageRef
    front_right: PageRef
    back_left: PageRef
    back_right: PageRef


@dataclass(frozen=True)
class BookletLayout:
    source_pages: int
    padded_pages: int
    sheets: list[Sheet]


def compute_layout(source_pages: int) -> BookletLayout:
    """Compute the saddle-stitch imposition order for a source PDF with
    `source_pages` pages.

    Standard formula (the same one tools like pdfbook/psbook use): pad the
    page count up to a multiple of 4 with blanks, then for sheet i
    (0-indexed, i=0 outermost/cover sheet) put pages
    (N-2i, 2i+1) on the front and (2i+2, N-2i-1) on the back, where N is
    the padded page count. Stacking the sheets in that order (sheet 0 on
    top) and folding the whole stack in half at once produces the correct
    1..N reading order.
    """
    if source_pages < 1:
        raise ValueError("The PDF has no pages.")

    remainder = source_pages % 4
    padded = source_pages if remainder == 0 else source_pages + (4 - remainder)
    sheet_count = padded // 4

    def slot(page_number: int) -> PageRef:
        # page_number is 1-based; anything past the real page count is a
        # padded blank page.
        return page_number - 1 if page_number <= source_pages else None

    sheets = [
        Sheet(
            front_left=slot(padded - 2 * i),
            front_right=slot(2 * i + 1),
            back_left=slot(2 * i + 2),
            back_right=slot(padded - 2 * i - 1),
        )
        for i in range(sheet_count)
    ]
    return BookletLayout(source_pages=source_pages, padded_pages=padded, sheets=sheets)


def _render_page_to_image(doc, index: int, dpi: float):
    page = doc[index]
    bitmap = page.render(scale=dpi / 72.0)  # PDF's native unit is 1/72 inch
    return bitmap.to_pil()


def _compose_sheet(left_image, right_image, dpi: float, *, rotate_180: bool = False):
    """Compose one A4 landscape sheet from up to two source-page images
    (either half may be None for a padded blank page), each scaled to fit
    its A5 half while preserving aspect ratio and centered within it."""
    from PIL import Image

    px_per_mm = dpi / 25.4
    sheet_w = round(A4_HEIGHT_MM * px_per_mm)
    sheet_h = round(A4_WIDTH_MM * px_per_mm)
    half_w = sheet_w // 2

    sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
    for image, x_offset in ((left_image, 0), (right_image, half_w)):
        if image is None:
            continue
        scale = min(half_w / image.width, sheet_h / image.height)
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        resized = image.resize(new_size, Image.LANCZOS)
        x = x_offset + (half_w - new_size[0]) // 2
        y = (sheet_h - new_size[1]) // 2
        sheet.paste(resized, (x, y))

    if rotate_180:
        sheet = sheet.rotate(180)
    return sheet


def build_booklet_pdf(
    source_pdf_path: str,
    out_pdf_path: str,
    *,
    dpi: float = 300.0,
    rotate_back: bool = False,
) -> BookletLayout:
    """Render `source_pdf_path` into a booklet-imposed PDF at
    `out_pdf_path`: A4 landscape sheets, two source pages per side, in
    saddle-stitch order (see compute_layout).

    `rotate_back` rotates every back side 180 degrees before saving --
    whether that's needed depends on which physical edge the printer's
    duplex unit flips around (short edge vs. long edge), which varies by
    printer/driver and isn't something this code can know in advance; the
    caller exposes it as a checkbox so a wrong first test page can be
    corrected by toggling it and reprinting, rather than guessing.

    Each composed A4 sheet is written out to its own small single-page PDF
    and immediately discarded from memory, rather than keeping every
    full-resolution sheet image (which at a print-quality DPI adds up fast
    for a long document -- e.g. ~1.2 GiB of raw RGB for a 100-page source
    at 300 DPI) alive at once for a single combined save. The per-sheet
    PDFs are then merged into the final output and cleaned up.

    Requires pypdfium2 and Pillow (imported lazily -- see module
    docstring); raises ImportError if either is missing.
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(source_pdf_path)
    try:
        layout = compute_layout(len(doc))

        def image_for(ref: PageRef):
            return _render_page_to_image(doc, ref, dpi) if ref is not None else None

        sheet_pdf_paths: list[str] = []
        try:
            for sheet in layout.sheets:
                front = _compose_sheet(image_for(sheet.front_left), image_for(sheet.front_right), dpi)
                sheet_pdf_paths.append(_save_single_page_pdf(front, dpi))
                back = _compose_sheet(
                    image_for(sheet.back_left), image_for(sheet.back_right), dpi, rotate_180=rotate_back
                )
                sheet_pdf_paths.append(_save_single_page_pdf(back, dpi))

            _merge_single_page_pdfs(sheet_pdf_paths, out_pdf_path)
        finally:
            for path in sheet_pdf_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
    finally:
        doc.close()

    return layout


def _save_single_page_pdf(image, dpi: float) -> str:
    """Save a single composed sheet as its own one-page PDF in a temp
    file, and return its path -- the caller merges these back together in
    _merge_single_page_pdfs and is responsible for deleting them."""
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="jadiv-print-center-booklet-sheet-")
    os.close(fd)
    image.save(path, format="PDF", resolution=dpi)
    return path


def _merge_single_page_pdfs(pdf_paths: list[str], out_pdf_path: str) -> None:
    """Concatenate the given one-page PDFs, in order, into a single PDF at
    out_pdf_path -- via pypdfium2's own page-import (each source stays a
    compact PDF object, not a decoded-to-pixels image), rather than Pillow,
    which only offers combining already-open, fully in-memory Image
    objects."""
    import pypdfium2 as pdfium

    merged = pdfium.PdfDocument.new()
    try:
        for pdf_path in pdf_paths:
            page_doc = pdfium.PdfDocument(pdf_path)
            try:
                merged.import_pages(page_doc)
            finally:
                page_doc.close()
        merged.save(out_pdf_path)
    finally:
        merged.close()
