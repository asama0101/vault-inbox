from __future__ import annotations

import sys
from pathlib import Path

import pytest
from vault_inbox.extract import (
    ExtractError,
    extract_text,
    is_candidate,
    missing_dependencies,
)

WORD = "Zebracorn"


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return out


def _make(tmp_path: Path, ext: str) -> Path:
    p = tmp_path / f"sample{ext}"
    if ext in (".md", ".txt"):
        p.write_text(f"hello {WORD}", encoding="utf-8")
    elif ext == ".html":
        p.write_text(f"<html><body><p>hello {WORD}</p></body></html>", encoding="utf-8")
    elif ext == ".pdf":
        p.write_bytes(_minimal_pdf(WORD))
    elif ext == ".docx":
        import docx

        d = docx.Document()
        d.add_paragraph("intro")
        t = d.add_table(rows=1, cols=1)
        t.cell(0, 0).text = WORD
        d.save(str(p))
    elif ext == ".xlsx":
        import openpyxl

        wb = openpyxl.Workbook()
        wb.active["A1"] = WORD
        wb.save(str(p))
    elif ext == ".pptx":
        import pptx

        prs = pptx.Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = WORD
        prs.save(str(p))
    return p


@pytest.mark.parametrize(
    "ext", [".md", ".txt", ".html", ".pdf", ".docx", ".xlsx", ".pptx"]
)
def test_extract_each_format_contains_known_word(tmp_path, ext):
    assert WORD in extract_text(_make(tmp_path, ext))


def test_extract_xlsx_puts_each_row_on_its_own_line(tmp_path):
    """One giant line cannot be paged by Read (about 22,000 characters per call)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["品目", 1, 2])
    ws.append([None, None, None])  # an empty row adds no line
    ws.append(["別の品目", None, 3])
    wb.create_sheet().append(["第二シート"])
    p = tmp_path / "a.xlsx"
    wb.save(str(p))
    assert extract_text(p).split("\n") == ["品目 1 2", "別の品目 3", "第二シート"]


def test_extract_long_xlsx_is_many_short_lines(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    for r in range(1000):
        wb.active.append([f"品目{r:04d}"] + list(range(9)))
    p = tmp_path / "big.xlsx"
    wb.save(str(p))
    lines = extract_text(p).split("\n")
    assert len(lines) == 1000
    assert max(len(ln) for ln in lines) < 100


def test_extract_html_puts_each_block_on_its_own_line(tmp_path):
    p = tmp_path / "a.html"
    p.write_text(
        "<html><body><h1>題名</h1><p>一つ目 の\n段落</p>"
        "<ul><li>項目A</li><li>項目B</li></ul>"
        "<p>二つ目<br>改行後</p><script>var x</script></body></html>",
        encoding="utf-8",
    )
    assert extract_text(p).split("\n") == [
        "題名",
        "一つ目 の 段落",
        "項目A",
        "項目B",
        "二つ目",
        "改行後",
    ]


def test_extract_pptx_reads_grouped_shapes_and_speaker_notes(tmp_path):
    import pptx
    from pptx.util import Inches

    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(
        Inches(1), Inches(1), Inches(3), Inches(1)
    ).text_frame.text = "PLAINBOX"
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(
        Inches(1), Inches(3), Inches(3), Inches(1)
    ).text_frame.text = "GROUPEDBOX"
    slide.notes_slide.notes_text_frame.text = "SPEAKERNOTE"
    p = tmp_path / "a.pptx"
    prs.save(str(p))
    text = extract_text(p)
    for word in ("PLAINBOX", "GROUPEDBOX", "SPEAKERNOTE"):
        assert word in text, word


def test_extract_docx_reads_header_and_footer_once(tmp_path):
    import docx

    d = docx.Document()
    d.add_paragraph("BODYTEXT")
    d.sections[0].header.paragraphs[0].text = "HEADERTEXT"
    d.sections[0].footer.paragraphs[0].text = "FOOTERTEXT"
    d.add_section()  # inherits the same header/footer: linked to the previous one
    p = tmp_path / "a.docx"
    d.save(str(p))
    text = extract_text(p)
    for word in ("BODYTEXT", "HEADERTEXT", "FOOTERTEXT"):
        assert word in text, word
    assert text.count("HEADERTEXT") == 1


def test_extract_html_strips_tags(tmp_path):
    text = extract_text(_make(tmp_path, ".html"))
    assert "<" not in text


def test_extract_empty_file_raises_empty(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes(b"")
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "empty"


def test_extract_whitespace_only_raises_empty(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text(" \n\t \n", encoding="utf-8")
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "empty"


@pytest.mark.parametrize("name", ["a.doc", "a.png"])
def test_extract_unsupported_ext(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"x")
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "unsupported"


def test_extract_corrupt_pdf_raises_extract_failed(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf at all")
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason.startswith("extract_failed: ")


def test_extract_cp932_text(tmp_path):
    p = tmp_path / "jp.txt"
    p.write_bytes("日本語のメモ".encode("cp932"))
    assert extract_text(p) == "日本語のメモ"


def test_is_candidate_skips_office_temp_and_hidden(tmp_path):
    assert is_candidate(tmp_path / "a.md")
    assert not is_candidate(tmp_path / "~$a.docx")
    assert not is_candidate(tmp_path / ".hidden.md")


@pytest.mark.parametrize(
    "ext", [".md", ".txt", ".html", ".pdf", ".docx", ".xlsx", ".pptx"]
)
def test_extract_zero_byte_any_format_raises_empty(tmp_path, ext):
    p = tmp_path / f"zero{ext}"
    p.write_bytes(b"")
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "empty"


def test_extract_missing_library_names_the_dependency(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"
    p.write_bytes(_minimal_pdf(WORD))
    monkeypatch.setitem(sys.modules, "pypdf", None)  # makes `import pypdf` fail
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "missing_dependency: pypdf"


def test_extract_missing_library_reports_pip_name(tmp_path, monkeypatch):
    p = tmp_path / "a.docx"
    p.write_bytes(b"not read: the import fails first")
    monkeypatch.setitem(sys.modules, "docx", None)
    with pytest.raises(ExtractError) as e:
        extract_text(p)
    assert e.value.reason == "missing_dependency: python-docx"


def test_missing_dependencies_lists_pip_names(monkeypatch):
    assert missing_dependencies() == []
    monkeypatch.setitem(sys.modules, "docx", None)
    monkeypatch.setitem(sys.modules, "pptx", None)
    assert missing_dependencies() == ["python-docx", "python-pptx"]


def test_extract_missing_file_raises_extract_failed(tmp_path):
    with pytest.raises(ExtractError) as e:
        extract_text(tmp_path / "gone.pdf")
    assert e.value.reason == "extract_failed: FileNotFoundError"
