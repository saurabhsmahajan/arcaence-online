"""Turns a question into the 384 numbers the database compares with. Same model as the ingestion in rag/."""
import config

_model = None


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # imported here so the offline tests need no model

        _model = TextEmbedding(config.EMBED_MODEL)
    return _model


def embed_query(question: str) -> list[float]:
    return next(iter(get_model().query_embed(question))).tolist()
