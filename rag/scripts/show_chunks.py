import sys

from ingest.chunk import chunk_record
from ingest.normalize import build_records

doc_id = sys.argv[1]
only_unnumbered = "--unnumbered" in sys.argv
full = "--full" in sys.argv

for record in build_records():
    if record.doc_id != doc_id:
        continue
    for c in chunk_record(record):
        if only_unnumbered and c.clause_id:
            continue
        print(f"[{c.chunk_index:2}] id={str(c.clause_id):5} len={len(c.content):4} "
              f"page={c.page} ocr={c.is_ocr} sec={str(c.section_ref)[:30]!r}")
        print(f"     {c.content if full else c.content[:110]}")