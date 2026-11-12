from itertools import combinations

from ingest.normalize import Record


def shingles(text: str, n: int = 4) -> set[str]:
    words = text.split()
    return {" ".join(words[i : i + n]) for i in range(max(len(words) - n + 1, 0))}


def compare(records: list[Record], n: int = 4) -> list[dict]:
    sh = {r.doc_id: shingles(r.text, n) for r in records}
    out = []
    for a, b in combinations(records, 2):
        sa, sb = sh[a.doc_id], sh[b.doc_id]
        if not sa or not sb:
            continue
        inter = len(sa & sb)
        out.append(
            {
                "a": a.doc_id,
                "b": b.doc_id,
                "exact": a.text_hash == b.text_hash,
                "jaccard": inter / len(sa | sb),
                "containment": inter / min(len(sa), len(sb)),
            }
        )
    return sorted(out, key=lambda d: -d["containment"])