"""The Swap Engine — deterministic recipe transformation.

Given a recipe and a health goal, it proposes ingredient substitutions from
the curated rules, recomputes each candidate with the Nutrition Engine, and
keeps only swaps that genuinely improve the goal metric. No LLM, no guessing:
every number comes from the engine, every swap is justified by a real delta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml
from rapidfuzz import fuzz

from . import aliases, data_access, nutrition_engine as ne, resolver
from .nutrition_engine import RecipeItem, RecipeNutrition
from .schema import ROOT

RULES_PATH = ROOT / "swap_rules.yaml"

# goal -> list of objectives (nutrient key, sign). sign -1 = lower is better,
# +1 = higher is better. A swap is kept only if it improves at least one
# objective and worsens none -- so composite goals (diabetic_friendly = less
# sugar AND more fibre) accept swaps that help any objective.
GOAL_OBJECTIVES: dict[str, list[tuple[str, int]]] = {
    # deficiency-targeted boosts (India's biggest gaps: protein, iron, calcium)
    "higher_protein":    [("protein_g", +1)],
    "iron_boost":        [("iron_mg", +1)],
    "calcium_boost":     [("calcium_mg", +1)],
    "higher_fibre":      [("fibre_g", +1)],
    # lifestyle-disease oriented goals
    "diabetic_friendly": [("sugar_g", -1), ("fibre_g", +1)],
    "lower_calorie":     [("kcal", -1)],
    "lower_sugar":       [("sugar_g", -1)],
    "lower_sodium":      [("sodium_mg", -1)],
    "lower_fat":         [("fat_g", -1)],
}

GOALS = list(GOAL_OBJECTIVES.keys())

# Goals shown as "healthier variations" side-by-side for a recipe. Ordered to
# lead with the deficiency boosts that matter most for the Indian population.
DEFAULT_VARIANT_GOALS = [
    "higher_protein", "iron_boost", "calcium_boost",
    "higher_fibre", "diabetic_friendly",
]


@dataclass
class Swap:
    kind: str                       # 'substitution' | 'reduction' | 'addition'
    original_name: str
    replacement: RecipeItem
    replacement_name: str
    qty_factor: float
    metric: str
    before_val: float
    after_val: float
    reason: str | None
    original: RecipeItem | None = None

    @property
    def is_reduction(self) -> bool:
        return self.kind == "reduction"

    @property
    def is_addition(self) -> bool:
        return self.kind == "addition"


@dataclass
class Transformation:
    goal: str
    before: RecipeNutrition
    after: RecipeNutrition
    swaps: list[Swap] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def delta(self, key: str) -> float:
        return round(self.after.totals.get(key, 0) - self.before.totals.get(key, 0), 2)


@lru_cache(maxsize=1)
def _rules() -> dict:
    if not RULES_PATH.exists():
        return {}
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _rule_matches(rule: dict, item: RecipeItem) -> bool:
    """Does this rule's `from` describe the recipe item?

    Keyword match (not id equality): every significant word of `from` (after
    alias expansion) must appear in the item's name or aliases. This is robust
    to the resolver mapping 'sugar' and 'sugar white' to different specific
    entries, while still NOT matching e.g. atta when the rule targets 'refined
    wheat flour' (the word 'refined' won't be present)."""
    if not rule.get("from"):
        return False  # addition-only rule, handled separately
    ing = data_access.get(item.ingredient_id)
    if ing is None:
        return False
    hay = re.split(r"[ ,|]+", f"{ing.name} {ing.aliases or ''}".lower())
    key = aliases.expand(rule["from"].strip().lower())
    for kt in (t for t in re.split(r"[ ,]+", key) if t):
        if not any(kt == h or (len(kt) >= 4 and kt in h)
                   or fuzz.ratio(kt, h) >= 88 for h in hay):
            return False
    return True


def _make_candidate(item: RecipeItem, rule: dict):
    """Return (candidate_item, replacement_name, reason) or (None, reason, _)
    when the replacement can't be resolved."""
    factor = float(rule.get("qty_factor", 1.0))
    reason = rule.get("note")
    to_name = rule.get("to")

    if to_name:
        rr = resolver.resolve(to_name)
        # Safety: a replacement must match a real ingredient *exactly* (by name
        # or alias). Fuzzy is not trusted here -- it once mapped 'besan' to a
        # vegetable. A bad/missing target is skipped loudly, never swapped in.
        if not rr.ok or rr.method not in ("exact", "alias"):
            return None, to_name, reason
        cand = RecipeItem(rr.ingredient.id, item.qty * factor, item.unit,
                          display_name=rr.ingredient.name)
        return cand, rr.ingredient.name, reason

    # reduction: same ingredient, smaller quantity
    ing = data_access.get(item.ingredient_id)
    name = ing.name if ing else item.display_name or item.ingredient_id
    cand = RecipeItem(item.ingredient_id, item.qty * factor, item.unit,
                      display_name=item.display_name)
    return cand, name, reason


def _line_value(item: RecipeItem, metric: str) -> float:
    return ne.compute([item]).totals.get(metric, 0.0)


def _evaluate(item: RecipeItem, cand: RecipeItem,
              objectives: list[tuple[str, int]]) -> bool:
    """A candidate is accepted if it improves >=1 objective and worsens none."""
    improved = False
    for metric, sign in objectives:
        diff = (_line_value(cand, metric) - _line_value(item, metric)) * sign
        if diff > 1e-6:
            improved = True
        elif diff < -1e-6:
            return False  # worsens an objective -> reject
    return improved


def _evaluate_addition(cand: RecipeItem,
                       objectives: list[tuple[str, int]]) -> bool:
    """Accept an added booster if it raises a 'higher is better' objective and
    doesn't add to any 'lower is better' objective."""
    improved = False
    for metric, sign in objectives:
        v = _line_value(cand, metric)
        if sign > 0 and v > 1e-6:
            improved = True
        if sign < 0 and v > 1e-6:
            return False  # adding would worsen a reduction goal
    return improved


def transform(items: list[RecipeItem], goal: str) -> Transformation:
    if goal not in GOAL_OBJECTIVES:
        raise ValueError(f"unknown goal '{goal}'. options: {', '.join(GOALS)}")
    objectives = GOAL_OBJECTIVES[goal]
    metric = objectives[0][0]  # primary, for the Swap record
    before = ne.compute(items)

    rules = _rules().get(goal, [])

    new_items: list[RecipeItem] = []
    swaps: list[Swap] = []
    notes: list[str] = []

    for item in items:
        applied = False
        for rule in rules:
            if not _rule_matches(rule, item):
                continue
            cand, repl_name, reason = _make_candidate(item, rule)
            if cand is None:
                notes.append(
                    f"could not apply '{rule.get('note') or rule['from']}': "
                    f"replacement '{repl_name}' not in database"
                )
                continue
            if _evaluate(item, cand, objectives):
                b = _line_value(item, metric)
                a = _line_value(cand, metric)
                orig = data_access.get(item.ingredient_id)
                kind = ("reduction"
                        if cand.ingredient_id == item.ingredient_id
                        else "substitution")
                swaps.append(Swap(
                    kind=kind, original=item,
                    original_name=(orig.name if orig else item.display_name or ""),
                    replacement=cand, replacement_name=repl_name,
                    qty_factor=float(rule.get("qty_factor", 1.0)),
                    metric=metric, before_val=round(b, 2), after_val=round(a, 2),
                    reason=reason,
                ))
                new_items.append(cand)
                applied = True
                break
        if not applied:
            new_items.append(item)

    # additions: booster sides/garnishes for the goal (e.g. sprinkle sesame).
    present = {it.ingredient_id for it in new_items}
    for rule in rules:
        add_name = rule.get("add")
        if not add_name:
            continue
        rr = resolver.resolve(add_name)
        if not rr.ok or rr.method not in ("exact", "alias"):
            notes.append(f"could not add '{add_name}': not in database")
            continue
        if rr.ingredient.id in present:
            continue  # already in the recipe
        cand = RecipeItem(rr.ingredient.id, float(rule.get("qty", 1)),
                          rule.get("unit", "g"), display_name=rr.ingredient.name)
        if not _evaluate_addition(cand, objectives):
            continue
        swaps.append(Swap(
            kind="addition", original=None, original_name="",
            replacement=cand, replacement_name=rr.ingredient.name,
            qty_factor=1.0, metric=metric, before_val=0.0,
            after_val=round(_line_value(cand, metric), 2), reason=rule.get("note"),
        ))
        new_items.append(cand)
        present.add(rr.ingredient.id)

    after = ne.compute(new_items)
    return Transformation(goal, before, after, swaps, notes)


def transform_by_name(rows: list[tuple[str, float, str]], goal: str) -> Transformation:
    """Resolve free-text (name, qty, unit) rows, then transform for `goal`."""
    items: list[RecipeItem] = []
    for name, qty, unit in rows:
        r = resolver.resolve(name)
        if r.ingredient is not None:
            items.append(RecipeItem(r.ingredient.id, qty, unit, display_name=name))
    return transform(items, goal)


if __name__ == "__main__":
    recipe = [
        ("refined wheat flour", 150, "g"),
        ("ghee", 2, "tbsp"),
        ("sugar", 3, "tsp"),
        ("salt", 1, "tsp"),
    ]
    for goal in ["lower_calorie", "higher_fibre", "diabetic_friendly"]:
        t = transform_by_name(recipe, goal)
        print(f"\n=== goal: {goal} ===")
        print(f"  BEFORE: {t.before.totals['kcal']} kcal | "
              f"fibre {t.before.totals['fibre_g']}g | sugar {t.before.totals['sugar_g']}g")
        for s in t.swaps:
            kind = "use less" if s.is_reduction else f"-> {s.replacement_name}"
            print(f"   - {s.original_name} {kind}  ({s.reason})")
        print(f"  AFTER:  {t.after.totals['kcal']} kcal | "
              f"fibre {t.after.totals['fibre_g']}g | sugar {t.after.totals['sugar_g']}g  "
              f"[d_kcal {t.delta('kcal')}]")
        for n in t.notes:
            print("   !", n)
