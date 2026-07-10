"""Health insights — grounded benefits, cautions, and improvement tips.

All statements are derived deterministically from the engine's numbers:
  * static flags   threshold rules (health_rules.yaml) on the recipe profile
  * improvements   beneficial before->after changes from a transformation

Nothing here invents a health claim; every line traces to a real value. The
LLM (if enabled) only rewords these in phrasing.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from .schema import NUTRIENT_COLUMNS, ROOT
from .swap_engine import Transformation

RULES_PATH = ROOT / "health_rules.yaml"

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}
_COND = re.compile(r"^\s*(\w+)\s*(>=|<=|==|>|<)\s*([\d.]+)\s*$")

# nutrient -> +1 if higher is healthier, -1 if lower is healthier (for tips)
_GOOD_DIRECTION = {
    "kcal": -1, "fat_g": -1, "sugar_g": -1, "sodium_mg": -1,
    "protein_g": +1, "fibre_g": +1, "calcium_mg": +1, "iron_mg": +1,
    "vitc_mg": +1,
}
# minimum absolute change worth mentioning, per nutrient
_MIN_DELTA = {
    "kcal": 25, "fat_g": 2, "sugar_g": 2, "sodium_mg": 50,
    "protein_g": 2, "fibre_g": 2, "calcium_mg": 30, "iron_mg": 1, "vitc_mg": 5,
}


@dataclass
class Insight:
    text: str
    kind: str   # benefit | caution | improvement


@lru_cache(maxsize=1)
def _rules() -> dict:
    if not RULES_PATH.exists():
        return {}
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _holds(cond: str, profile: dict[str, float]) -> bool:
    m = _COND.match(cond)
    if not m:
        return False
    key, op, num = m.group(1), m.group(2), float(m.group(3))
    val = profile.get(key)
    if val is None:
        return False
    return _OPS[op](val, num)


def analyze(profile: dict[str, float]) -> list[Insight]:
    """Static benefit/caution flags for a single nutrient profile."""
    rules = _rules()
    out: list[Insight] = []
    seen: set[str] = set()
    for kind in ("benefits", "cautions"):
        for rule in rules.get(kind, []):
            if _holds(rule.get("if", ""), profile):
                text = rule["text"]
                # de-dup overlapping tiers (e.g. high vs good protein)
                if text not in seen:
                    out.append(Insight(text, kind[:-1]))  # benefit / caution
                    seen.add(text)
    # keep only the strongest protein tier if both fired
    return _dedupe_tiers(out)


def _dedupe_tiers(items: list[Insight]) -> list[Insight]:
    texts = [i.text for i in items]
    if "High in protein - helps keep you full" in texts:
        items = [i for i in items if i.text != "Good source of protein"]
    return items


def improvements(t: Transformation) -> list[Insight]:
    """Beneficial before->after changes from a transformation."""
    out: list[Insight] = []
    for key, direction in _GOOD_DIRECTION.items():
        before = t.before.totals.get(key, 0.0)
        after = t.after.totals.get(key, 0.0)
        change = after - before
        if abs(change) < _MIN_DELTA.get(key, 0):
            continue
        if change * direction <= 0:
            continue  # not in the healthy direction
        label, unit = NUTRIENT_COLUMNS[key]
        verb = "up" if direction > 0 else "down"
        out.append(Insight(
            f"{label} {verb}: {before} -> {after} {unit} "
            f"({'+' if change >= 0 else ''}{round(change, 1)})",
            "improvement",
        ))
    return out


def insights_for_transformation(t: Transformation) -> list[str]:
    """Improvement tips (from the swaps) + benefits/cautions for the result.
    Returns plain strings ready for the phrasing layer."""
    lines = [i.text for i in improvements(t)]
    lines += [i.text for i in analyze(t.after.totals)]
    return lines
