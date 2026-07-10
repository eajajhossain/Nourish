"""Traditional (vector) RAG — Chroma index over the project's knowledge.

Complements vectorless.py: fuzzy name matching can't answer "which dal has
the most iron?" or find a dish described rather than named. The index holds:

  * every dish row phrased as a sentence (nutrition facts stay searchable)
  * the curated recipes with their ingredient lists
  * text chunks of the IFCT 2017 PDF (Indian Food Composition Tables)

Build once:   python -m nourish.agent.build_index
Storage:      data/processed/chroma/

Embeddings: MiniLM-L6-v2 either way — via the HuggingFace Inference API when
EMBEDDING_API_KEY is set (no local model download), else Chroma's bundled
local ONNX copy. Build and query must use the same source, so both paths go
through _embedding_function().
"""
from __future__ import annotations

import json
import time
import urllib.request
from functools import lru_cache

from ..schema import PROCESSED, ROOT
from . import config

CHROMA_DIR = PROCESSED / "chroma"
COLLECTION = "nourish_knowledge"
IFCT_PDF = ROOT / "IFCT2017.pdf"
CSV_SOURCE = ROOT / "Indian_Food_Nutrition_Processed.csv"

_HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_HF_URLS = (
    f"https://router.huggingface.co/hf-inference/models/{_HF_MODEL}/pipeline/feature-extraction",
    f"https://api-inference.huggingface.co/pipeline/feature-extraction/{_HF_MODEL}",
)


def _hf_embed(texts: list[str]) -> list[list[float]]:
    """Embed via the HF Inference API, retrying while the model warms up."""
    last_err: Exception | None = None
    for url in _HF_URLS:
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"inputs": texts}).encode("utf-8"),
                    headers={"Authorization": f"Bearer {config.EMBEDDING_API_KEY}",
                             "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 503:          # model loading — wait and retry
                    time.sleep(8)
                    continue
                break                      # other HTTP error: try next URL
            except Exception as e:
                last_err = e
                break
    raise RuntimeError(f"HF embedding API failed: {last_err}")


def _embedding_function():
    """HF-API embedder when the key is set, else None (Chroma's local ONNX)."""
    if not config.EMBEDDING_API_KEY:
        return None
    from chromadb import Documents, EmbeddingFunction, Embeddings

    class HFApiEmbedding(EmbeddingFunction):
        def __call__(self, input: Documents) -> Embeddings:
            return _hf_embed(list(input))

        @staticmethod
        def name() -> str:
            return "nourish-hf-api"

    return HFApiEmbedding()


def _get_or_create(client):
    ef = _embedding_function()
    if ef is not None:
        return client.get_or_create_collection(COLLECTION, embedding_function=ef)
    return client.get_or_create_collection(COLLECTION)


@lru_cache(maxsize=1)
def _collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _get_or_create(client)


def ready() -> bool:
    try:
        return _collection().count() > 0
    except Exception:
        return False


def search(query: str, k: int = 4) -> list[dict]:
    """Return up to k {text, source, score} hits; [] if index not built."""
    if not ready():
        return []
    res = _collection().query(query_texts=[query], n_results=k)
    out = []
    for text, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                                res["distances"][0]):
        out.append({"text": text, "source": (meta or {}).get("source", "?"),
                    "score": round(1 - dist, 3)})
    return out


# ------------------------------------------------------------------ build
def _dish_docs() -> tuple[list[str], list[dict], list[str]]:
    from .vectorless import _dishes
    docs, metas, ids = [], [], []
    for i, (name, row) in enumerate(_dishes().items()):
        parts = [f"{name} — Indian dish, per serving:"]
        labels = {"kcal": "energy kcal", "protein_g": "protein g",
                  "carb_g": "carbohydrate g", "fat_g": "fat g",
                  "sugar_g": "sugar g", "fibre_g": "fibre g",
                  "sodium_mg": "sodium mg", "calcium_mg": "calcium mg",
                  "iron_mg": "iron mg", "vitc_mg": "vitamin C mg",
                  "folate_ug": "folate µg"}
        for k, label in labels.items():
            v = row.get(k)
            if v is not None:
                parts.append(f"{label} {v}")
        docs.append(", ".join(parts))
        metas.append({"source": "dish database"})
        ids.append(f"dish-{i}")
    return docs, metas, ids


def _recipe_docs() -> tuple[list[str], list[dict], list[str]]:
    from .. import recipes as seed
    docs, metas, ids = [], [], []
    for i, r in enumerate(seed.all_recipes()):
        docs.append(f"Recipe: {r.name} ({r.cuisine}). Ingredients: "
                    + "; ".join(f"{x['qty']:g} {x['unit']} {x['name']}"
                                for x in r.ingredients))
        metas.append({"source": "curated recipes"})
        ids.append(f"recipe-{i}")
    return docs, metas, ids


def _pdf_docs(max_pages: int | None = None) -> tuple[list[str], list[dict], list[str]]:
    import pdfplumber
    docs, metas, ids = [], [], []
    if not IFCT_PDF.exists():
        return docs, metas, ids
    with pdfplumber.open(IFCT_PDF) as pdf:
        pages = pdf.pages[:max_pages] if max_pages else pdf.pages
        for pno, page in enumerate(pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) < 120:
                continue
            for j in range(0, len(text), 1100):
                chunk = text[j:j + 1300]  # 200-char overlap
                docs.append(chunk)
                metas.append({"source": f"IFCT 2017 p.{pno}"})
                ids.append(f"ifct-{pno}-{j}")
    return docs, metas, ids


def build(include_pdf: bool = True, verbose: bool = True) -> int:
    """(Re)build the whole index. Returns document count."""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = _get_or_create(client)

    batches = [_dish_docs(), _recipe_docs()]
    if include_pdf:
        batches.append(_pdf_docs())

    total = 0
    for docs, metas, ids in batches:
        for i in range(0, len(docs), 100):
            col.add(documents=docs[i:i + 100], metadatas=metas[i:i + 100],
                    ids=ids[i:i + 100])
            total += len(docs[i:i + 100])
            if verbose:
                print(f"  indexed {total} documents...", end="\r")
    if verbose:
        print(f"\nDone — {total} documents in {CHROMA_DIR}")
    _collection.cache_clear()
    return total
