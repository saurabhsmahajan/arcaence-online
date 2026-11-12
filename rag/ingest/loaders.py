import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
import zipfile
import xml.etree.ElementTree as ET
from openpyxl import load_workbook
import os

import pypdfium2 as pdfium
import pytesseract
from dotenv import load_dotenv
from PIL import Image, ImageOps


@dataclass
class Unit:
    text: str
    section_ref: str | None = None
    page: int | None = None
    is_ocr: bool = False


def load_markdown(path: Path) -> list[Unit]:
    text = path.read_text(encoding="utf-8")
    units: list[Unit] = []
    current_ref: str | None = None
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            units.append(Unit(text=body, section_ref=current_ref))

    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            flush()
            current_ref = m.group(1).strip()
            buf = [line]
        else:
            buf.append(line)
    flush()
    return units


def load_pdf_text(path: Path) -> list[Unit]:
    reader = PdfReader(str(path))
    units: list[Unit] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            units.append(Unit(text=text, page=page_number))
    return units

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _run_text(run) -> str:
    if run.find(f"{W}rPr/{W}vanish") is not None:
        return ""  # hidden text
    parts = []
    for el in run:
        if el.tag == f"{W}t":
            parts.append(el.text or "")
        elif el.tag == f"{W}tab":
            parts.append("\t")
    return "".join(parts)


def _paragraph_text(p) -> str:
    out = []

    def walk(node):
        for child in node:
            if child.tag == f"{W}del":
                continue  # tracked deletion: drop
            if child.tag == f"{W}r":
                out.append(_run_text(child))
            else:
                walk(child)  # w:ins, w:hyperlink and so on

    walk(p)
    return "".join(out).strip()


def load_docx(path: Path) -> list[Unit]:
    xml = zipfile.ZipFile(path).read("word/document.xml")
    root = ET.fromstring(xml)
    units: list[Unit] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush():
        if buffer:
            units.append(Unit(text="\n".join(buffer), section_ref=heading))
            buffer.clear()

    for p in root.iter(f"{W}p"):
        text = _paragraph_text(p)
        if not text:
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        style_id = style.get(f"{W}val", "") if style is not None else ""
        if style_id.startswith(("Heading", "Title")):
            flush()
            heading = text
        else:
            buffer.append(text)
    flush()
    return units

def load_xlsx(path: Path, header_rows: tuple[int, ...] = (3, 4)) -> list[Unit]:
    wb = load_workbook(path, data_only=True)
    units: list[Unit] = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            print(f"  [skipped hidden sheet '{ws.title}' in {path.name}]")
            continue

        # fill merged cells, but only inside the header rows
        for rng in list(ws.merged_cells.ranges):
            if rng.min_row in header_rows:
                value = ws.cell(rng.min_row, rng.min_col).value
                ws.unmerge_cells(str(rng))
                for row in ws.iter_rows(
                    min_row=rng.min_row, max_row=rng.max_row,
                    min_col=rng.min_col, max_col=rng.max_col,
                ):
                    for cell in row:
                        cell.value = value

        # one label per column, e.g. "Monthly EUR"
        labels = {}
        for col in range(2, ws.max_column + 1):
            parts = [
                str(ws.cell(r, col).value)
                for r in header_rows
                if ws.cell(r, col).value is not None
            ]
            labels[col] = " ".join(parts)

        for r in range(1, ws.max_row + 1):
            if r in header_rows:
                continue
            first = ws.cell(r, 1).value
            if first is None:
                continue
            pairs = [
                f"{labels[c]} {ws.cell(r, c).value}"
                for c in range(2, ws.max_column + 1)
                if ws.cell(r, c).value is not None
            ]
            text = f"{first}: " + "; ".join(pairs) if pairs else str(first)
            units.append(Unit(text=text, section_ref=ws.title))
    return units

load_dotenv()
if os.getenv("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")


def _ocr_image(img) -> str:
    return pytesseract.image_to_string(ImageOps.grayscale(img), lang="eng").strip()


def load_pdf_ocr(path: Path) -> list[Unit]:
    pdf = pdfium.PdfDocument(str(path))
    units: list[Unit] = []
    for i in range(len(pdf)):
        img = pdf[i].render(scale=300 / 72).to_pil()
        text = _ocr_image(img)
        if text:
            units.append(Unit(text=text, page=i + 1, is_ocr=True))
    return units


def load_pdf_auto(path: Path) -> list[Unit]:
    units = load_pdf_text(path)
    return units if units else load_pdf_ocr(path)


def load_image_ocr(path: Path) -> list[Unit]:
    text = _ocr_image(ImageOps.exif_transpose(Image.open(path)))
    return [Unit(text=text, is_ocr=True)] if text else []

LOADERS = {
    "md": load_markdown,
    "pdf": load_pdf_auto,
    "docx": load_docx,
    "xlsx": load_xlsx,
    "jpg": load_image_ocr,
    "jpeg": load_image_ocr,
    "png": load_image_ocr,
}