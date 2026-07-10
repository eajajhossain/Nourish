"""Seed recipe library — real Indian dishes WITH ingredient lists.

The public Indian dish dataset has nutrition totals but no ingredients, so it
can't be transformed. This small curated library gives users recipes to pick
and transform out of the box (the "select from existing recipes" path).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .schema import ROOT

RECIPES_JSON = ROOT / "data" / "curated" / "recipes.json"


@dataclass
class SeedRecipe:
    name: str
    cuisine: str
    ingredients: list[dict]  # {name, qty, unit}

    def as_text(self) -> str:
        return "\n".join(
            f"{self._fmt(i['qty'])} {i['unit']} {i['name']}"
            for i in self.ingredients
        )

    @staticmethod
    def _fmt(q: float) -> str:
        return str(int(q)) if float(q).is_integer() else str(q)


@lru_cache(maxsize=1)
def all_recipes() -> list[SeedRecipe]:
    if not RECIPES_JSON.exists():
        return []
    data = json.loads(RECIPES_JSON.read_text(encoding="utf-8"))
    return [SeedRecipe(r["name"], r.get("cuisine", ""), r["ingredients"])
            for r in data]


def get(name: str) -> SeedRecipe | None:
    for r in all_recipes():
        if r.name == name:
            return r
    return None


def names() -> list[str]:
    return [r.name for r in all_recipes()]
