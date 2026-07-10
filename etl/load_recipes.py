"""Load the Indian dish nutrition CSV into recipes.db.

This is DISH-level data (finished dishes with total nutrition) -- not ingredient
lists. It serves two roles in Nourish:
  1. a validation set for the Nutrition Engine (known dish totals to check against)
  2. seed entries for the recipe library / "before" reference

Run:  python -m etl.load_recipes
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from .config import INDIAN_CSV, PROCESSED

RECIPES_DB = PROCESSED / "recipes.db"

# CSV column -> canonical dish column.
COLUMN_MAP = {
    "Dish Name": "dish_name",
    "Calories (kcal)": "kcal",
    "Carbohydrates (g)": "carb_g",
    "Protein (g)": "protein_g",
    "Fats (g)": "fat_g",
    "Free Sugar (g)": "sugar_g",
    "Fibre (g)": "fibre_g",
    "Sodium (mg)": "sodium_mg",
    "Calcium (mg)": "calcium_mg",
    "Iron (mg)": "iron_mg",
    "Vitamin C (mg)": "vitc_mg",
    "Folate (µg)": "folate_ug",
}


def load() -> int:
    print(f"[recipes] reading {INDIAN_CSV.name}")
    df = pd.read_csv(INDIAN_CSV)
    df = df.rename(columns=COLUMN_MAP)
    df = df[[c for c in COLUMN_MAP.values() if c in df.columns]]
    df = df.dropna(subset=["dish_name"])
    df = df[df["dish_name"].astype(str).str.strip() != ""]

    PROCESSED.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(RECIPES_DB)
    df.to_sql("dishes", conn, if_exists="replace", index=False)
    n = conn.execute("SELECT COUNT(*) FROM dishes").fetchone()[0]
    conn.close()
    print(f"[recipes] wrote {n} dishes to {RECIPES_DB.name}")
    return n


if __name__ == "__main__":
    load()
