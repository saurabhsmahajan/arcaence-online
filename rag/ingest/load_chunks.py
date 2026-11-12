import os

import psycopg
from dotenv import load_dotenv

from ingest.chunk import chunk_record
from ingest.embed import embed_chunks
from ingest.normalize import build_records

load_dotenv()


def to_vector(values) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in values) + "]"


def main() -> None:
    records = build_records()
    chunks = [c for r in records for c in chunk_record(r)]
    vectors = embed_chunks(chunks)
    doc_ids = [r.doc_id for r in records]

    registry = {
        (c.clause_id, c.doc_id): c.section_ref or ""
        for c in chunks if c.clause_id
    }

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from chunks where doc_id = any(%s)", (doc_ids,))
            cur.execute("delete from clause_registry where doc_id = any(%s)", (doc_ids,))
            cur.executemany(
                "insert into clause_registry (clause_id, doc_id, section_ref) "
                "values (%s, %s, %s)",
                [(cid, did, sref) for (cid, did), sref in registry.items()],
            )
            cur.executemany(
                "insert into chunks (doc_id, chunk_index, content, section_ref, "
                "page, clause_id, is_ocr, embedding) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                [
                    (c.doc_id, c.chunk_index, c.content, c.section_ref, c.page,
                     c.clause_id, c.is_ocr, to_vector(v))
                    for c, v in zip(chunks, vectors)
                ],
            )
    print(f"loaded {len(chunks)} chunks and {len(registry)} registry rows "
          f"for {len(doc_ids)} documents")


if __name__ == "__main__":
    main()