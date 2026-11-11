import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class Unit:
    text: str
    section_ref: str | None = None
    page: int | None = None


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


LOADERS = {
    "md": load_markdown,
    "pdf": load_pdf_text,
}