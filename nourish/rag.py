"""Optional semantic fallback for ingredient matching.

Uses local sentence-transformer embeddings (free, CPU) over ingredient names.
This is an OPTIONAL enhancement: if sentence-transformers isn't installed the
resolver simply skips it and relies on exact/alias/fuzzy matching. Nothing in
the core depends on it.

Enable by installing:  pip install sentence-transformers
"""
from __future__ import annotations

from functools import lru_cache

from . import data_access

_MODEL_NAME = "all-MiniLM-L6-v2"


def available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _index():
    """Build (model, embeddings, ids) once. Returns None if unavailable."""
    if not available():
        return None
    from sentence_transformers import SentenceTransformer
    import numpy as np  # noqa: F401  (sentence-transformers pulls numpy)

    model = SentenceTransformer(_MODEL_NAME)
    ings = data_access.all_ingredients()
    texts = [i.name for i in ings]
    ids = [i.id for i in ings]
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return model, emb, ids


def search(query: str, k: int = 3) -> list[tuple[str, float]]:
    """Return up to k (ingredient_id, score 0-100) by cosine similarity."""
    idx = _index()
    if idx is None:
        return []
    model, emb, ids = idx
    q = model.encode([query], normalize_embeddings=True, show_progress_bar=False)
    sims = (emb @ q[0])  # cosine, since normalized
    order = sims.argsort()[::-1][:k]
    return [(ids[i], round(float(sims[i]) * 100, 1)) for i in order]
