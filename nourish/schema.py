"""Single source of truth for paths and the canonical nutrient schema.

Both the ETL (build-time) and the engine (run-time) conform to this.
All nutrient values are per 100 g of edible portion.
"""
from __future__ import annotations

from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
INGREDIENTS_DB = PROCESSED / "ingredients.db"
RECIPES_DB = PROCESSED / "recipes.db"

# --- Canonical nutrient schema ---------------------------------------------
# column name -> (human label, unit)
NUTRIENT_COLUMNS = {
    "kcal":       ("Energy", "kcal"),
    "protein_g":  ("Protein", "g"),
    "carb_g":     ("Carbohydrate", "g"),
    "fat_g":      ("Total fat", "g"),
    "fibre_g":    ("Dietary fibre", "g"),
    "sugar_g":    ("Total sugar", "g"),
    "sodium_mg":  ("Sodium", "mg"),
    "calcium_mg": ("Calcium", "mg"),
    "iron_mg":    ("Iron", "mg"),
    "vitc_mg":    ("Vitamin C", "mg"),
}
NUTRIENT_KEYS = list(NUTRIENT_COLUMNS.keys())
