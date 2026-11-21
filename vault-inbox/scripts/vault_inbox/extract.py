from __future__ import annotations

import importlib.util
from html.parser import HTMLParser
from pathlib import Path

from .frontmatter import strip_managed
from .indexmd import is_generated
from .vault import SUPPORTED_EXTS

# import name -> pip package name, for the formats that need a library
_DEPENDENCIES = {
    "pypdf": "pypdf",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "pptx": "python-pptx",
}


class ExtractError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_candidate(path: Path) -> bool:
    """A name we write (or wrote before) is never a material."""
    return not (
        path.name.startswith("~$")
        or path.name.startswith(".")
        or is_generated(path.name)
    )


def missing_dependencies() -> list[str]:
    """pip names of the extraction libraries that cannot be imported."""
    return [
        pip
        for mod, pip in _DEPENDENCIES.items()
        if importlib.util.find_spec(mod) is None
    ]


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932")


_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "hr", "li", "ul", "ol", "tr", "table", "section", "article"}
    | {"header", "footer", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            # a line break inside the text is not a block boundary
            self.parts.append(" ".join(data.split()))


def _html(path: Path) -> str:
    parser = _TextParser()
    parser.feed(_read_text(path))
    # One line per block: Read cannot page through a single very long line.
    lines = (" ".join(ln.split()) for ln in " ".join(parser.parts).split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("encrypted")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    for section in doc.sections:
        for part in (section.header, section.footer):
            if not part.is_linked_to_previous:  # a linked one repeats the previous text
                parts.extend(p.text for p in part.paragraphs)
    return "\n".join(parts)


def _xlsx(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        lines = []  # one line per row: Read cannot page through a single long line
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                line = " ".join(str(v) for v in row if v is not None)
                if line.strip():
                    lines.append(line)
        return "\n".join(lines)
    finally:
        wb.close()


def _pptx_shape_texts(shapes) -> list[str]:
    parts = []
    for shape in shapes:
        if shape.has_text_frame:
            parts.append(shape.text_frame.text)
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                parts.extend(cell.text for cell in row.cells)
        if hasattr(shape, "shapes"):  # a group: its shapes are not in slide.shapes
            parts.extend(_pptx_shape_texts(shape.shapes))
    return parts


def _pptx(path: Path) -> str:
    import pptx

    parts = []
    for slide in pptx.Presentation(str(path)).slides:
        parts.extend(_pptx_shape_texts(slide.shapes))
        if slide.has_notes_slide:
            parts.append(slide.notes_slide.notes_text_frame.text)
    return "\n".join(parts)


_READERS = {
    ".md": _read_text,
    ".txt": _read_text,
    ".html": _html,
    ".pdf": _pdf,
    ".docx": _docx,
    ".xlsx": _xlsx,
    ".pptx": _pptx,
}


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ExtractError("unsupported")
    try:
        if path.stat().st_size == 0:
            raise ExtractError("empty")
        text = _READERS[ext](path)
    except ExtractError:
        raise
    except ImportError as e:
        name = _DEPENDENCIES.get(e.name, e.name)  # same pip name as `status` reports
        raise ExtractError(f"missing_dependency: {name}") from e
    except Exception as e:  # noqa: BLE001 - 壊れた入力はすべて理由付きで報告する
        raise ExtractError(f"extract_failed: {type(e).__name__}") from e
    if ext == ".md":
        text = strip_managed(text)
    if not text.strip():
        raise ExtractError("empty")
    return text
