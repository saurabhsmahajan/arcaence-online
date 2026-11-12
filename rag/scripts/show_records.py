from ingest.normalize import build_records

print(f"{'doc_id':<22}{'status':<12}{'rank':<6}{'units':<7}{'chars':<7}{'ocr':<6}{'hash':<10}notes")
for r in build_records():
    print(
        f"{r.doc_id:<22}{r.status:<12}{r.authority_rank:<6}{len(r.units):<7}"
        f"{len(r.text):<7}{str(r.is_ocr):<6}{r.text_hash[:8]:<10}{'; '.join(r.notes)}"
    )