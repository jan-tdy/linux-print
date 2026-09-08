import pytest

from linuxprint.booklet import A4_HEIGHT_MM, A4_WIDTH_MM, Sheet, build_booklet_pdf, compute_layout


def test_compute_layout_rejects_empty_pdf():
    with pytest.raises(ValueError):
        compute_layout(0)


def test_compute_layout_single_sheet_no_padding():
    # 4 pages == exactly 1 sheet, no blank padding needed. Front holds the
    # outside cover (page 4 on the left, page 1 on the right); back holds
    # the center spread (page 2 left, page 3 right) -- the classic 4-page
    # saddle-stitch booklet.
    layout = compute_layout(4)
    assert layout.padded_pages == 4
    assert layout.sheets == [Sheet(front_left=3, front_right=0, back_left=1, back_right=2)]


def test_compute_layout_pads_to_multiple_of_four():
    # 10 pages pads to 12 (2 blanks), giving 3 sheets. The blanks land as
    # the very first and very last slots (padded (11,12) -> 0-based (10,11)
    # are None), which is where a real booklet's would-be trailing blank
    # pages belong.
    layout = compute_layout(10)
    assert layout.padded_pages == 12
    assert len(layout.sheets) == 3
    assert layout.sheets[0].front_left is None
    assert layout.sheets[0].back_right is None
    # every real source page (0..9) appears in exactly one slot
    seen = [
        ref
        for sheet in layout.sheets
        for ref in (sheet.front_left, sheet.front_right, sheet.back_left, sheet.back_right)
        if ref is not None
    ]
    assert sorted(seen) == list(range(10))


def test_compute_layout_two_sheets_matches_standard_imposition():
    # 8 pages, 2 sheets. Sheet 0 (outermost) carries the front/back cover
    # pair (8,1) and the pair just inside it (2,7); sheet 1 (innermost)
    # carries (6,3) and (4,5) -- the well-known psbook/pdfbook imposition
    # order for a saddle-stitch booklet.
    layout = compute_layout(8)
    assert layout.sheets == [
        Sheet(front_left=7, front_right=0, back_left=1, back_right=6),
        Sheet(front_left=5, front_right=2, back_left=3, back_right=4),
    ]


def test_build_booklet_pdf_produces_a4_landscape_sheets(tmp_path):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from PIL import Image
    import pypdfium2 as pdfium

    src_path = tmp_path / "source.pdf"
    pages = [Image.new("RGB", (400, 566), "white") for _ in range(6)]  # ~A5 at 72dpi
    pages[0].save(src_path, save_all=True, append_images=pages[1:])

    out_path = tmp_path / "booklet.pdf"
    layout = build_booklet_pdf(str(src_path), str(out_path), dpi=100.0)

    # 6 pages pad to 8 -> 2 sheets -> 4 printed sides.
    assert layout.padded_pages == 8
    assert len(layout.sheets) == 2

    doc = pdfium.PdfDocument(str(out_path))
    try:
        assert len(doc) == 4
        for i in range(len(doc)):
            width_pt, height_pt = doc[i].get_size()
            assert width_pt / 72 * 25.4 == pytest.approx(A4_HEIGHT_MM, abs=1.0)
            assert height_pt / 72 * 25.4 == pytest.approx(A4_WIDTH_MM, abs=1.0)
    finally:
        doc.close()


def test_build_booklet_pdf_rotate_back_flips_back_sides(tmp_path):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from PIL import Image

    src_path = tmp_path / "source.pdf"
    pages = [Image.new("RGB", (400, 566), "white") for _ in range(4)]
    pages[0].save(src_path, save_all=True, append_images=pages[1:])

    out_a = tmp_path / "no_rotate.pdf"
    out_b = tmp_path / "rotate.pdf"
    build_booklet_pdf(str(src_path), str(out_a), dpi=80.0, rotate_back=False)
    build_booklet_pdf(str(src_path), str(out_b), dpi=80.0, rotate_back=True)

    assert out_a.read_bytes() != out_b.read_bytes()
