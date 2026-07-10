"""Orchestration — wire the whole transform together.

    free-text recipe + goal
      -> parse (LLM or deterministic)
      -> resolve ingredients
      -> compute baseline nutrition
      -> swap for the goal + recompute
      -> phrase the result

The engine owns every number end-to-end; the LLM only parses text in and
phrases text out.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import health_insights, parsing, phrasing, resolver, swap_engine
from .nutrition_engine import RecipeItem, RecipeNutrition
from .parsing import ParsedItem
from .swap_engine import DEFAULT_VARIANT_GOALS, Transformation


@dataclass
class RecipeResult:
    goal: str
    parsed: list[ParsedItem]
    resolution: list[tuple[str, str | None, float, bool]]  # query, match, score, ok
    transformation: Transformation
    insights: list[str]
    narrative: str


@dataclass
class Variant:
    goal: str
    transformation: Transformation
    insights: list[str]


@dataclass
class VariantsResult:
    parsed: list[ParsedItem]
    resolution: list[tuple[str, str | None, float, bool]]
    baseline: RecipeNutrition
    variants: list[Variant]


def transform_recipe(text: str, goal: str, dish: str | None = None) -> RecipeResult:
    parsed = parsing.parse_recipe(text)

    rows: list[tuple[str, float, str]] = []
    resolution: list[tuple[str, str | None, float, bool]] = []
    for p in parsed:
        r = resolver.resolve(p.name)
        match = r.ingredient.name if r.ingredient else None
        resolution.append((p.name, match, r.score, r.ok))
        rows.append((p.name, p.qty, p.unit))

    t = swap_engine.transform_by_name(rows, goal)
    insights = health_insights.insights_for_transformation(t)
    narrative = phrasing.phrase_transformation(t, dish=dish, insights=insights)
    return RecipeResult(goal, parsed, resolution, t, insights, narrative)


def _resolve_rows(parsed: list[ParsedItem]):
    rows, resolution, items = [], [], []
    for p in parsed:
        r = resolver.resolve(p.name)
        resolution.append((p.name, r.ingredient.name if r.ingredient else None,
                           r.score, r.ok))
        rows.append((p.name, p.qty, p.unit))
        if r.ingredient is not None:
            items.append(RecipeItem(r.ingredient.id, p.qty, p.unit,
                                    display_name=p.name))
    return rows, resolution, items


def make_variants(text: str, goals: list[str] | None = None,
                  only_changed: bool = True) -> VariantsResult:
    """Generate several healthier variations of one recipe, across dimensions.

    Returns only variants that actually changed something (unless
    only_changed=False), so the UI never shows an empty 'variant'."""
    goals = goals or DEFAULT_VARIANT_GOALS
    parsed = parsing.parse_recipe(text)
    _rows, resolution, items = _resolve_rows(parsed)

    baseline = swap_engine.ne.compute(items)
    variants: list[Variant] = []
    for g in goals:
        t = swap_engine.transform(items, g)
        if only_changed and not t.swaps:
            continue
        variants.append(Variant(g, t, health_insights.insights_for_transformation(t)))
    return VariantsResult(parsed, resolution, baseline, variants)


if __name__ == "__main__":
    recipe = """
    2 cups refined wheat flour
    2 tbsp ghee
    3 tsp sugar
    1 cup milk
    salt to taste
    """
    res = transform_recipe(recipe, "diabetic_friendly", dish="sweet paratha")
    print("=== parsed ===")
    for p in res.parsed:
        print(f"  {p.qty:>5} {p.unit:6} {p.name}")
    print("\n=== resolution ===")
    for q, m, sc, ok in res.resolution:
        print(f"  {q:24} -> {m or '—':30} [{sc}]{'' if ok else '  LOW'}")
    print("\n=== narrative ===")
    print(res.narrative)
