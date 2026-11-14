from functools import lru_cache
from typing import Sequence

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)

def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return 384-dimensional embeddings when the optional local model is installed.

    Missing packages/model weights are deliberately non-fatal: retrieval falls back to
    deterministic lexical ranking instead of pretending semantic indexing happened.
    """
    if not texts: return []
    try:
        vectors = _model().encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in vector] for vector in vectors]
    except Exception:
        return None
