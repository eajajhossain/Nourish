"""Load USDA FoodData Central Foundation Foods into the canonical store.

Reads the relational CSVs (food / food_category / food_nutrient), keeps only
curated `foundation_food` rows, pivots the nutrients we care about into the
canonical per-100g schema, and writes them to ingredients.db.

Run:  python -m etl.load_usda
"""
from __future__ import annotations

import pandas as pd

from . import db
from .config import (
    NUTRIENT_KEYS,
    USDA_DIR,
    USDA_KEEP_DATA_TYPES,
    USDA_NUTRIENT_MAP,
)


def _load_food() -> pd.DataFrame:
    food = pd.read_csv(
        USDA_DIR / "food.csv",
        usecols=["fdc_id", "data_type", "description", "food_category_id"],
        dtype={"fdc_id": "Int64", "food_category_id": "Int64"},
    )
    food = food[food["data_type"].isin(USDA_KEEP_DATA_TYPES)].copy()

    cats = pd.read_csv(
        USDA_DIR / "food_category.csv", usecols=["id", "description"]
    ).rename(columns={"id": "food_category_id", "description": "category"})
    food = food.merge(cats, on="food_category_id", how="left")
    return food


def _load_nutrients(keep_fdc_ids: set[int]) -> pd.DataFrame:
    """Return one row per fdc_id with canonical nutrient columns.

    Where a canonical nutrient maps to several USDA ids (e.g. energy), the
    lowest-priority-number id available for that food wins.
    """
    fn = pd.read_csv(
        USDA_DIR / "food_nutrient.csv",
        usecols=["fdc_id", "nutrient_id", "amount"],
        dtype={"fdc_id": "Int64", "nutrient_id": "Int64", "amount": "float64"},
    )
    fn = fn[
        fn["fdc_id"].isin(keep_fdc_ids)
        & fn["nutrient_id"].isin(USDA_NUTRIENT_MAP.keys())
    ].copy()
    fn["col"] = fn["nutrient_id"].map(lambda i: USDA_NUTRIENT_MAP[i][0])
    fn["priority"] = fn["nutrient_id"].map(lambda i: USDA_NUTRIENT_MAP[i][1])

    # For each (food, canonical column) keep the highest-priority amount.
    fn = fn.sort_values("priority")
    best = fn.drop_duplicates(subset=["fdc_id", "col"], keep="first")

    pivot = (
        best.pivot(index="fdc_id", columns="col", values="amount")
        .reindex(columns=NUTRIENT_KEYS)
    )
    return pivot


def load() -> int:
    print(f"[usda] reading from {USDA_DIR}")
    food = _load_food()
    print(f"[usda] kept {len(food)} foundation_food rows")

    nutrients = _load_nutrients(set(food["fdc_id"].dropna().astype(int)))
    print(f"[usda] pivoted nutrients for {len(nutrients)} foods")

    merged = food.set_index("fdc_id").join(nutrients, how="left")

    rows: list[dict] = []
    for fdc_id, r in merged.iterrows():
        row = {
            "id": f"usda:{int(fdc_id)}",
            "name": str(r["description"]).strip(),
            "source": "USDA",
            "category": (None if pd.isna(r.get("category")) else r["category"]),
            "aliases": None,
        }
        for k in NUTRIENT_KEYS:
            v = r.get(k)
            row[k] = (None if pd.isna(v) else round(float(v), 3))
        rows.append(row)

    conn = db.connect()
    db.create_ingredients_table(conn)
    written = db.upsert_ingredients(conn, rows)
    total = db.count_ingredients(conn)
    conn.close()
    print(f"[usda] wrote {written} ingredients (db total: {total})")
    return written


if __name__ == "__main__":
    load()
