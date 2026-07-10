"""Grounded diet-chart generator.

Builds a one-day meal plan from the real dish database, sized to the user's
calorie target and filtered by their conditions and diet preference. The
numbers come from here; the LLM only presents the chart and adds context.
Deliberately deterministic so the same profile always gets the same chart.
"""
from __future__ import annotations

import re

from . import profile as prof
from .vectorless import _dishes

MEALS = [("Breakfast", 0.25), ("Lunch", 0.35), ("Evening snack", 0.10),
         ("Dinner", 0.30)]

_NONVEG = re.compile(r"chicken|mutton|fish|prawn|shrimp|keema|egg|meat|crab",
                     re.I)
# table entries that are ingredients/condiments rather than servable dishes
_NOT_A_DISH = re.compile(r"powder|premix|paste|seasoning|chutney|pickle|"
                         r"achar|murabba|concentrate|squash|supari|mouth "
                         r"freshener|papad", re.I)
_EGG = re.compile(r"egg", re.I)
_MEAL_HINTS = {
    "Breakfast": re.compile(r"idli|dosa|poha|upma|paratha|chilla|cheela|"
                            r"uttapam|sandwich|oats|daliya|porridge|milk|"
                            r"paneer bhurji|sprout", re.I),
    "Lunch": re.compile(r"dal|rice|roti|chapati|sabzi|curry|rajma|chole|"
                        r"sambar|kadhi|pulao|khichdi|biryani|saag", re.I),
    "Evening snack": re.compile(r"chaat|bhel|dhokla|tikki|salad|chana|"
                                r"makhana|nuts|sprout|soup|tea|buttermilk|"
                                r"lassi|fruit", re.I),
    "Dinner": re.compile(r"dal|roti|chapati|sabzi|curry|khichdi|soup|"
                         r"paneer|vegetable|palak|lauki|tinda", re.I),
}


def _condition_flags(p: dict) -> set[str]:
    text = f"{p.get('conditions') or ''} {p.get('condition_details') or ''}".lower()
    flags = set()
    if re.search(r"diabet|sugar|glyc", text):
        flags.add("diabetes")
    if re.search(r"hypertension|blood pressure|\bbp\b", text):
        flags.add("hypertension")
    if re.search(r"anemi|anaemi|iron|haemoglobin|hemoglobin", text):
        flags.add("anemia")
    if re.search(r"cholesterol|cardiac|heart|lipid", text):
        flags.add("heart")
    if re.search(r"kidney|renal", text):
        flags.add("kidney")
    b = prof.bmi(p)
    if b and prof.bmi_band(b) in ("overweight", "obese"):
        flags.add("weight_loss")
    if b and prof.bmi_band(b) == "underweight":
        flags.add("weight_gain")
    return flags


def _allowed(name: str, diet: str) -> bool:
    if diet in ("vegetarian", "vegan") and _NONVEG.search(name):
        return False
    if diet == "eggetarian" and _NONVEG.search(name) and not _EGG.search(name):
        return False
    return True


def _score(row: dict, flags: set[str]) -> float:
    """Higher = better fit for this user. Simple, explainable weights."""
    s = (row.get("protein_g") or 0) * 2 + (row.get("fibre_g") or 0) * 1.5
    if "diabetes" in flags:
        s -= (row.get("sugar_g") or 0) * 4
    if "hypertension" in flags or "kidney" in flags:
        s -= (row.get("sodium_mg") or 0) / 80
    if "anemia" in flags:
        s += (row.get("iron_mg") or 0) * 6
    if "heart" in flags or "weight_loss" in flags:
        s -= (row.get("fat_g") or 0) * 1.2
    return s


def build_chart(p: dict | None = None) -> dict:
    """Return a structured one-day plan: meals, dishes, portions, totals."""
    p = p or prof.get() or {}
    target = prof.daily_calories(p) or 2000
    flags = _condition_flags(p)
    if "weight_loss" in flags:
        target = int(target * 0.85)   # gentle deficit
    if "weight_gain" in flags:
        target = int(target * 1.10)
    diet = p.get("diet_pref") or "vegetarian"

    dishes = [{"name": n, **row} for n, row in _dishes().items()
              if (row.get("kcal") or 0) > 20 and _allowed(n, diet)
              and not _NOT_A_DISH.search(n)]

    plan, used = [], set()
    day_totals = {"kcal": 0.0, "protein_g": 0.0, "fibre_g": 0.0,
                  "sugar_g": 0.0, "sodium_mg": 0.0, "iron_mg": 0.0}
    for meal, share in MEALS:
        budget = target * share
        hint = _MEAL_HINTS[meal]
        pool = [d for d in dishes if hint.search(d["name"]) and d["name"] not in used]
        if len(pool) < 3:
            pool += [d for d in dishes if d["name"] not in used]
        pool.sort(key=lambda d: _score(d, flags), reverse=True)

        picks, kcal_sum = [], 0.0
        for d in pool[:40]:
            if len(picks) >= (2 if meal == "Evening snack" else 3):
                break
            if kcal_sum + (d["kcal"] or 0) > budget * 1.25 and picks:
                continue
            servings = 1.0
            if d["kcal"] and d["kcal"] < budget * 0.2:
                servings = round(min(2.0, (budget * 0.35) / d["kcal"]) * 2) / 2
            picks.append({
                "dish": d["name"], "servings": servings,
                "kcal": round((d["kcal"] or 0) * servings),
                "protein_g": round((d["protein_g"] or 0) * servings, 1),
                "fibre_g": round((d["fibre_g"] or 0) * servings, 1),
            })
            used.add(d["name"])
            kcal_sum += (d["kcal"] or 0) * servings
            for k in day_totals:
                day_totals[k] += (d.get(k) or 0) * servings
            if kcal_sum >= budget * 0.9:
                break
        plan.append({"meal": meal, "kcal_budget": round(budget),
                     "dishes": picks, "kcal_actual": round(kcal_sum)})

    return {
        "for": p.get("name") or "you",
        "daily_target_kcal": target,
        "adjusted_for": sorted(flags) or ["general fitness"],
        "diet_preference": diet,
        "meals": plan,
        "day_totals": {k: round(v, 1) for k, v in day_totals.items()},
        "note": ("Portions are per typical serving from the dish database. "
                 "This is a suggestion, not a medical prescription."),
    }
