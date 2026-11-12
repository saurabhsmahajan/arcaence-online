import re
from dataclasses import dataclass

from ingest.normalize import build_records

# Clause numbers: "2.2" (digits) or "B.1" (schedule style), at the start of a line
CLAUSE_RE = re.compile(r"^\**\s*(\d+(?:\.\d+)+|[A-Z]\.\d+)\s*\**\s*(.*)$")
# PDF text arrives as one flat line, so schedule clauses are found inline
LETTER_CLAUSE_RE = re.compile(r"(?<!\w)(?=[A-Z]\.\d+\s)")
SCHEDULE_RE = re.compile(r"(?=Schedule [A-Z]: )")
# Prices live in the plans_fees table, never in the vector store
PRICE_TABLE_RE = re.compile(r"Plan\s+Price\s+per\s+month.*?(?=Prices\s+exclude\s+tax)", re.S)
MAX_CHARS = 1200
HEADING_ONLY_CHARS = 40


@dataclass
class Chunk:
    doc_id: str
    chunk_index: int
    content: str
    section_ref: str | None
    page: int | None
    clause_id: str | None
    is_ocr: bool


def _clean(text: str) -> str:
    return " ".join(text.replace("**", "").lstrip("# ").split())


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Split on sentence ends, packing greedily up to the limit."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def _sections(unit) -> list[tuple[str | None, str]]:
    """Split a flat PDF page into schedules; other units pass through."""
    if unit.section_ref is None and "Schedule " in unit.text:
        out = []
        for part in SCHEDULE_RE.split(unit.text):
            if not part.strip():
                continue
            m = re.match(r"(Schedule [A-Z]):", part)
            out.append((m.group(1) if m else None, part))
        return out
    return [(unit.section_ref, unit.text)]


def _pieces(text: str) -> list[tuple[str | None, str]]:
    """Return (clause_id, text) pieces for one section."""
    text = PRICE_TABLE_RE.sub("", text)
    clauses: list[tuple[str | None, list[str]]] = []
    for line in text.splitlines():
        for segment in LETTER_CLAUSE_RE.split(line):
            stripped = segment.strip()
            # Skip blanks, rules and section headings (the heading is kept in section_ref)
            if not stripped or stripped == "---" or stripped.startswith("##"):
                continue
            m = CLAUSE_RE.match(stripped)
            if m:
                clauses.append((m.group(1), [stripped]))
            elif clauses:
                clauses[-1][1].append(stripped)
            else:
                clauses.append((None, [stripped]))
    if not clauses:
        return []
    # Unnumbered text: pack paragraphs together instead of one chunk per line
    if all(cid is None for cid, _ in clauses):
        return [(None, _clean(" ".join(" ".join(lines) for _, lines in clauses)))]
    pieces = [(cid, _clean(" ".join(lines))) for cid, lines in clauses]
    # Drop a bare heading that sits in front of numbered clauses
    return [(cid, t) for cid, t in pieces
            if cid is not None or len(t) > HEADING_ONLY_CHARS]


def chunk_record(record) -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in record.units:
        for section_ref, section_text in _sections(unit):
            for clause_id, text in _pieces(section_text):
                if not text:
                    continue
                for part in _split_long(text):
                    chunks.append(Chunk(
                        doc_id=record.doc_id,
                        chunk_index=len(chunks),
                        content=part,
                        section_ref=section_ref,
                        page=unit.page,
                        clause_id=None if unit.is_ocr else clause_id,
                        is_ocr=unit.is_ocr,
                    ))
    return chunks


if __name__ == "__main__":
    for record in build_records():
        chunks = chunk_record(record)
        numbered = sum(1 for c in chunks if c.clause_id)
        print(f"{record.doc_id:22} chunks={len(chunks):3} with_clause_id={numbered:3}")