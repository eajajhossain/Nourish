"""Read-only access to the canonical ingredient store.

The whole table is small (~775 rows), so we load it once into memory.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache

from .schema import INGREDIENTS_DB, NUTRIENT_KEYS


@dataclass(frozen=True)
class Ingredient:
    id: str
    name: str
    source: str
    category: str | None
    nutrients: dict[str, float | None]  # canonical per-100g, may contain None
    aliases: str | None = None

    def per100(self, key: str) -> float | None:
        return self.nutrients.get(key)


@dataclass
class _Store:
    by_id: dict[str, Ingredient] = field(default_factory=dict)

    @property
    def all(self) -> list[Ingredient]:
        return list(self.by_id.values())


@lru_cache(maxsize=1)
def _store() -> _Store:
    if not INGREDIENTS_DB.exists():
        raise FileNotFoundError(
            f"{INGREDIENTS_DB} not found. Run: python -m etl.build_all"
        )
    conn = sqlite3.connect(INGREDIENTS_DB)
    conn.row_factory = sqlite3.Row
    store = _Store()
    for r in conn.execute("SELECT * FROM ingredients"):
        ing = Ingredient(
            id=r["id"],
            name=r["name"],
            source=r["source"],
            category=r["category"],
            aliases=r["aliases"],
            nutrients={k: r[k] for k in NUTRIENT_KEYS},
        )
        store.by_id[ing.id] = ing
    conn.close()
    return store


def get(ingredient_id: str) -> Ingredient | None:
    return _store().by_id.get(ingredient_id)


def all_ingredients() -> list[Ingredient]:
    return _store().all


def find_by_name(query: str, limit: int = 5) -> list[Ingredient]:
    """Crude case-insensitive substring search.

    A placeholder until the Phase-2 resolver (fuzzy + semantic) lands; handy
    for demos and tests. Exact-name matches are returned first.
    """
    q = query.strip().lower()
    exact = [i for i in all_ingredients() if i.name.lower() == q]
    partial = [
        i for i in all_ingredients()
        if q in i.name.lower() and i.name.lower() != q
    ]
    return (exact + partial)[:limit]
