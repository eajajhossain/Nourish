"""Shared ETL configuration: paths and the canonical nutrient schema.

Everything downstream reads the same set of nutrient columns, in the same
units, regardless of whether the row came from USDA or IFCT.
"""
from __future__ import annotations

# Canonical schema + processed-store paths live in the core package so both
# build-time (etl) and run-time (nourish) share one definition.
from nourish.schema import (  # noqa: F401  (re-exported for etl modules)
    INGREDIENTS_DB,
    NUTRIENT_COLUMNS,
    NUTRIENT_KEYS,
    PROCESSED,
    ROOT,
)

# --- Raw dataset paths (build-time only) -----------------------------------
RAW = ROOT  # raw datasets currently live at the repo root
USDA_DIR = RAW / "FoodData_Central_foundation_food_csv_2026-04-30"
IFCT_PDF = RAW / "IFCT2017.pdf"
INDIAN_CSV = RAW / "Indian_Food_Nutrition_Processed.csv"

# --- USDA nutrient id -> (canonical column, priority) -----------------------
# USDA FoodData Central nutrient ids (from nutrient.csv). Some nutrients have
# several ids; priority picks the preferred one when more than one is present
# for a food (lower number = preferred). In the Foundation set, kcal id 1008
# is rare while Atwater (2047/2048) is common, and sugar lives under 1063.
USDA_NUTRIENT_MAP = {
    1008: ("kcal", 0),        # Energy (kcal) — preferred when present
    2047: ("kcal", 1),        # Energy (Atwater General Factors)
    2048: ("kcal", 2),        # Energy (Atwater Specific Factors)
    1003: ("protein_g", 0),
    1005: ("carb_g", 0),
    1004: ("fat_g", 0),
    1079: ("fibre_g", 0),
    1063: ("sugar_g", 0),     # Sugars, Total — the common Foundation id
    2000: ("sugar_g", 1),     # Total Sugars (NLEA) — fallback
    1093: ("sodium_mg", 0),
    1087: ("calcium_mg", 0),
    1089: ("iron_mg", 0),
    1162: ("vitc_mg", 0),     # Vitamin C, total ascorbic acid
}

# USDA data_types that represent clean per-100g ingredient profiles.
# In the Foundation Foods download only `foundation_food` rows are curated,
# de-duplicated, whole-ingredient profiles. The rest (sub_sample_food,
# market_acquisition, ...) are measurement components, not ingredients.
USDA_KEEP_DATA_TYPES = {"foundation_food"}
