import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ingest.loaders import LOADERS, Unit

CORPUS = Path(__file__).resolve().parents[2] / "corpus"


@dataclass
class Record:
    doc_id: str
    path: Path
    source_type: str
    status: str
    authority_rank: int
    units: list[Unit]
    text: str
    text_hash: str
    is_ocr: bool
    notes: list[str] = field(default_factory=list)


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def build_records() -> list[Record]:
    records: list[Record] = []
    with open(CORPUS / "manifest.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = CORPUS / row["path"]
            loader = LOADERS[path.suffix.lstrip(".").lower()]
            units = loader(path)
            text = normalize_text("\n".join(u.text for u in units))
            is_ocr = any(u.is_ocr for u in units)

            notes = []
            if not units:
                notes.append("no text extracted")
            if is_ocr:
                notes.append("OCR text, may contain errors")
            if row["status"] != "approved":
                notes.append(f"not authoritative ({row['status']})")

            records.append(
                Record(
                    doc_id=row["doc_id"],
                    path=path,
                    source_type=row["source_type"],
                    status=row["status"],
                    authority_rank=int(row["authority_rank"]),
                    units=units,
                    text=text,
                    text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    is_ocr=is_ocr,
                    notes=notes,
                )
            )
    return records