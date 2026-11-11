import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from ingest.loaders import LOADERS

CORPUS = Path(__file__).resolve().parents[2] / "corpus"


def main() -> None:
    load_dotenv()
    with open(CORPUS / "manifest.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    insert into documents
                      (doc_id, filename, source_type, file_format, version,
                       status, authority_rank, effective_date)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (doc_id) do update set
                      filename = excluded.filename,
                      source_type = excluded.source_type,
                      file_format = excluded.file_format,
                      version = excluded.version,
                      status = excluded.status,
                      authority_rank = excluded.authority_rank,
                      effective_date = excluded.effective_date
                    """,
                    (
                        r["doc_id"],
                        Path(r["path"]).name,
                        r["source_type"],
                        r["file_format"],
                        r["version"] or None,
                        r["status"],
                        int(r["authority_rank"]),
                        r["effective_date"] or None,
                    ),
                )
        conn.commit()

        print("documents table:")
        with conn.cursor() as cur:
            cur.execute(
                "select doc_id, status, authority_rank from documents "
                "order by authority_rank, doc_id"
            )
            for row in cur.fetchall():
                print("  ", row)

    print("\nloader check:")
    for r in rows:
        loader = LOADERS.get(r["file_format"])
        if loader is None:
            print(f"  {r['doc_id']:22} no loader yet for .{r['file_format']}")
            continue
        units = loader(CORPUS / r["path"])
        chars = sum(len(u.text) for u in units)
        note = "" if units else "  <- no text found, needs OCR"
        print(f"  {r['doc_id']:22} {len(units):3} units, {chars:6} chars{note}")


if __name__ == "__main__":
    main()