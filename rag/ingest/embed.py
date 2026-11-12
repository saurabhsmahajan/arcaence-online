import numpy as np
from fastembed import TextEmbedding

from ingest.chunk import chunk_record
from ingest.normalize import build_records

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384 dimensions
_model = None


def get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(MODEL_NAME)
    return _model


def embedding_text(chunk) -> str:
    """The text we embed: the section gives the clause its context."""
    if chunk.section_ref:
        return f"{chunk.section_ref}. {chunk.content}"
    return chunk.content


def embed_chunks(chunks) -> list[list[float]]:
    texts = [embedding_text(c) for c in chunks]
    return [v.tolist() for v in get_model().embed(texts)]


def embed_query(question: str) -> list[float]:
    return next(iter(get_model().query_embed(question))).tolist()


if __name__ == "__main__":
    record = next(r for r in build_records() if r.doc_id == "tos_v3")
    chunks = chunk_record(record)
    vectors = np.array(embed_chunks(chunks))
    print(f"embedded {len(chunks)} chunks, dimensions = {vectors.shape[1]}")

    for question in ["How long do I have to ask for a refund?",
                     "Can you restrict my account during a bank dispute?"]:
        q = np.array(embed_query(question))
        scores = vectors @ q / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))
        print(f"\n{question}")
        for i in np.argsort(-scores)[:3]:
            c = chunks[i]
            print(f"  {scores[i]:.3f}  id={c.clause_id}  {c.content[:70]}")