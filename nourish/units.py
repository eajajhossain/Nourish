"""Convert a (quantity, unit) pair to grams.

This is deliberately deterministic and explicit. Three kinds of unit:

  * mass    (g, kg, mg)         -> exact
  * volume  (ml, cup, tbsp, ...)-> grams via ingredient density (default 1.0)
  * count   (piece, medium, ...)-> grams via a typical-weight table

Every approximate conversion returns a human-readable note so the engine can
surface "assumed 1 cup = 240 ml at density 0.92" to the user. Numbers here are
documented approximations, refine per ingredient as needed.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- exact mass ------------------------------------------------------------
MASS_TO_G = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gm": 1.0, "gms": 1.0,
    "kg": 1000.0, "kilogram": 1000.0,
    "mg": 0.001,
}

# --- volume -> millilitres -------------------------------------------------
VOLUME_TO_ML = {
    "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0,
    "l": 1000.0, "litre": 1000.0, "liter": 1000.0,
    "tsp": 5.0, "teaspoon": 5.0,
    "tbsp": 15.0, "tablespoon": 15.0,
    "cup": 240.0, "cups": 240.0,
    "katori": 150.0,   # standard Indian small bowl
    "glass": 200.0,
}

# --- count units (need a typical weight per item) --------------------------
COUNT_UNITS = {
    "piece", "pieces", "pc", "pcs", "no", "nos", "whole", "unit",
    "small", "medium", "large", "",
}

# density in g/ml, matched by substring of the ingredient name (first hit wins)
DENSITY_OVERRIDES = {
    "oil": 0.92, "ghee": 0.91, "butter": 0.91, "honey": 1.42,
    "milk": 1.03, "curd": 1.03, "yogurt": 1.03, "yoghurt": 1.03, "cream": 1.01,
    "sugar": 0.85, "jaggery": 0.90, "syrup": 1.33,
    "flour": 0.53, "atta": 0.53, "maida": 0.53, "besan": 0.52,
    "rice": 0.85, "water": 1.0,
}
DEFAULT_DENSITY = 1.0

# typical edible weight per item in grams, matched by substring (first hit)
COUNT_WEIGHTS = {
    "egg": 50.0,
    "onion": 110.0, "potato": 150.0, "tomato": 100.0,
    "garlic": 3.0, "clove": 3.0, "green chilli": 5.0, "chilli": 5.0,
    "banana": 120.0, "apple": 180.0, "lemon": 60.0, "lime": 45.0,
    "roti": 40.0, "chapati": 40.0, "phulka": 35.0, "paratha": 80.0,
    "bread slice": 25.0, "slice": 25.0, "idli": 40.0, "dosa": 80.0,
}
DEFAULT_COUNT_WEIGHT = 100.0


@dataclass
class Conversion:
    grams: float
    note: str | None = None   # populated when an assumption was made


def _match(name: str | None, table: dict[str, float]) -> tuple[float, str] | None:
    if not name:
        return None
    low = name.lower()
    for key, val in table.items():
        if key in low:
            return val, key
    return None


def _density(name: str | None) -> tuple[float, bool]:
    hit = _match(name, DENSITY_OVERRIDES)
    if hit:
        return hit[0], True
    return DEFAULT_DENSITY, False


def _count_weight(name: str | None) -> tuple[float, bool]:
    hit = _match(name, COUNT_WEIGHTS)
    if hit:
        return hit[0], True
    return DEFAULT_COUNT_WEIGHT, False


def to_grams(qty: float, unit: str, ingredient_name: str | None = None) -> Conversion:
    """Convert qty of `unit` to grams. Never raises; unknown units are
    treated as grams with a warning note."""
    u = (unit or "").strip().lower()

    if u in MASS_TO_G:
        return Conversion(qty * MASS_TO_G[u])

    if u in VOLUME_TO_ML:
        ml = qty * VOLUME_TO_ML[u]
        dens, known = _density(ingredient_name)
        note = None
        if not known:
            note = f"assumed density {dens:g} g/ml for {u}"
        return Conversion(ml * dens, note)

    if u in COUNT_UNITS:
        wt, known = _count_weight(ingredient_name)
        label = u or "piece"
        if known:
            note = f"assumed 1 {label} ≈ {wt:g} g"
        else:
            note = f"unknown item weight; assumed 1 {label} ≈ {wt:g} g"
        return Conversion(qty * wt, note)

    # Unknown unit -> treat the number as grams, but flag it.
    return Conversion(qty, f"unrecognised unit '{unit}'; treated as grams")
