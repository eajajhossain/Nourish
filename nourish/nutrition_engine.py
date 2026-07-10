"""The Nutrition Engine — deterministic, no LLM.

Given a recipe as a list of (ingredient, quantity, unit), it converts each
line to grams, scales the ingredient's per-100g profile, and sums everything
into a recipe total. Missing nutrient values are skipped and reported, never
guessed.

This module owns numbers. Nothing here ever calls a language model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import data_access, units
from .data_access import Ingredient
from .schema import NUTRIENT_KEYS


@dataclass
class RecipeItem:
    """One line of a recipe."""
    ingredient_id: str
    qty: float
    unit: str
    display_name: str | None = None  # what the user typed/sees


@dataclass
class LineResult:
    item: RecipeItem
    ingredient: Ingredient
    grams: float
    nutrients: dict[str, float]      # scaled to `grams`
    notes: list[str] = field(default_factory=list)


@dataclass
class RecipeNutrition:
    totals: dict[str, float]
    lines: list[LineResult]
    warnings: list[str] = field(default_factory=list)


def empty_profile() -> dict[str, float]:
    return {k: 0.0 for k in NUTRIENT_KEYS}


def scale_profile(per100: dict[str, float | None], grams: float) -> tuple[dict[str, float], list[str]]:
    """Scale a per-100g profile to `grams`. Returns (scaled, missing_keys).

    Pure function: the heart of the engine, trivially testable.
    """
    factor = grams / 100.0
    scaled: dict[str, float] = {}
    missing: list[str] = []
    for k in NUTRIENT_KEYS:
        v = per100.get(k)
        if v is None:
            missing.append(k)
            continue
        scaled[k] = round(v * factor, 3)
    return scaled, missing


def compute(items: list[RecipeItem]) -> RecipeNutrition:
    """Compute total nutrition for a list of resolved recipe items."""
    totals = empty_profile()
    lines: list[LineResult] = []
    warnings: list[str] = []

    for item in items:
        ing = data_access.get(item.ingredient_id)
        if ing is None:
            warnings.append(
                f"ingredient '{item.ingredient_id}' not found — line skipped"
            )
            continue

        conv = units.to_grams(item.qty, item.unit, ing.name)
        scaled, missing = scale_profile(ing.nutrients, conv.grams)

        notes: list[str] = []
        if conv.note:
            notes.append(conv.note)
        if missing:
            labels = ", ".join(missing)
            notes.append(f"no data for: {labels}")
            warnings.append(
                f"{ing.name}: missing {labels} (treated as 0 in totals)"
            )

        for k, v in scaled.items():
            totals[k] += v

        lines.append(
            LineResult(item=item, ingredient=ing, grams=round(conv.grams, 2),
                       nutrients=scaled, notes=notes)
        )

    totals = {k: round(v, 2) for k, v in totals.items()}
    return RecipeNutrition(totals=totals, lines=lines, warnings=warnings)


# --- convenience: resolve free-text names then compute ---------------------
def compute_by_name(rows: list[tuple[str, float, str]]) -> RecipeNutrition:
    """Build a recipe from (name, qty, unit) tuples, resolving each name with
    the Phase-2 resolver. Unmatched names are skipped; low-confidence matches
    are used but flagged so the caller (and user) can see the uncertainty."""
    from . import resolver  # local import keeps engine independent of resolver

    items: list[RecipeItem] = []
    warnings: list[str] = []
    for name, qty, unit in rows:
        r = resolver.resolve(name)
        if r.ingredient is None:
            warnings.append(f"no ingredient matched '{name}' — skipped")
            continue
        if not r.ok:
            warnings.append(
                f"'{name}' -> '{r.ingredient.name}' is low confidence "
                f"({r.method} {r.score}); please verify"
            )
        items.append(
            RecipeItem(ingredient_id=r.ingredient.id, qty=qty, unit=unit,
                       display_name=name)
        )
    result = compute(items)
    result.warnings = warnings + result.warnings
    return result


if __name__ == "__main__":
    # Tiny demo using ingredients known to exist in the store.
    demo = [
        ("Bajra", 80, "g"),
        ("Barley", 50, "g"),
        ("Maize, dry", 40, "g"),
    ]
    res = compute_by_name(demo)
    print("=== Nourish nutrition engine demo ===")
    for ln in res.lines:
        print(f"  {ln.ingredient.name[:28]:30} {ln.grams:6.1f} g  "
              f"-> {ln.nutrients.get('kcal', 0):6.1f} kcal")
    print("  " + "-" * 48)
    t = res.totals
    print(f"  {'TOTAL':30} {'':8}    {t['kcal']:6.1f} kcal | "
          f"protein {t['protein_g']}g | carb {t['carb_g']}g | "
          f"fat {t['fat_g']}g | fibre {t['fibre_g']}g")
    for w in res.warnings:
        print("  ! ", w)
