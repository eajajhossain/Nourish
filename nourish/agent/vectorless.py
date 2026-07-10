"""Vector-less RAG — direct retrieval from the structured SQLite stores.

No embeddings, no index: the dish table is small enough that fuzzy string
matching over names IS the retrieval step, and the row itself is the grounded
answer. This is always tried before the vector store or the web, because when
it hits, it is exact.

Sources:
  data/processed/recipes.db  (1,014 Indian dishes, per-serving nutrition)
  data/curated/recipes.json  (curated dishes WITH ingredient lists)
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from .. import recipes as seed_recipes
from ..schema import RECIPES_DB

CONFIDENT = 82  # fuzzy score at/above which the DB answer is trusted


def _match_score(query: str, name: str) -> float:
    """WRatio alone misses DB names like 'Potato parantha/paratha (Aloo ka
    parantha/paratha)' for the query 'aloo paratha'; token_set_ratio nails
    those (all query tokens present) but over-matches short names, so blend
    the two with a small penalty on the set score. default_process strips
    punctuation so 'parantha/paratha' and '(aloo' tokenise properly."""
    return max(fuzz.WRatio(query, name, processor=default_process),
               fuzz.token_set_ratio(query, name, processor=default_process) - 2)


@lru_cache(maxsize=1)
def _dishes() -> dict[str, dict]:
    """name -> nutrition row, loaded once."""
    conn = sqlite3.connect(RECIPES_DB)
    conn.row_factory = sqlite3.Row
    rows = {r["dish_name"]: dict(r) for r in conn.execute("SELECT * FROM dishes")}
    conn.close()
    return rows


def find_dish(query: str, limit: int = 5) -> list[dict]:
    """Fuzzy-match a dish name. Returns [{name, score, nutrition, ingredients?}]."""
    scored = sorted(((_match_score(query, n), n) for n in _dishes()),
                    reverse=True)
    out = []
    for score, name in scored[:limit]:
        if score < 60:
            continue
        row = dict(_dishes()[name])
        row.pop("dish_name", None)
        out.append({"name": name, "score": round(score, 1), "nutrition": row})
    # curated recipes carry ingredient lists; borrow nutrition from the
    # closest DB row so a curated top hit still has numbers
    for r in seed_recipes.all_recipes():
        score = _match_score(query, r.name)
        if score >= 75 and not any(h["name"] == r.name for h in out):
            db_score, db_name = max(
                ((_match_score(r.name, n), n) for n in _dishes()),
                default=(0, None))
            nutrition = None
            if db_name and db_score >= 85:
                nutrition = dict(_dishes()[db_name])
                nutrition.pop("dish_name", None)
                nutrition["from_db_entry"] = db_name
            out.append({"name": r.name, "score": round(score, 1),
                        "nutrition": nutrition, "ingredients": r.ingredients})
    out.sort(key=lambda h: h["score"], reverse=True)
    return out[:limit]


def confident_hit(query: str) -> dict | None:
    """The single best match if it's trustworthy, else None (caller falls
    back to the vector store / web)."""
    hits = find_dish(query, limit=1)
    if hits and hits[0]["score"] >= CONFIDENT:
        return hits[0]
    return None
