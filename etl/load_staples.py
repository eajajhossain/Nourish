"""Load the curated staples supplement into ingredients.db.

These are essential Indian-kitchen items (ghee, cooking oils, salt, sugar,
common dals) that the public datasets carry poorly or not at all -- pure fats
have too few columns to parse from IFCT, and USDA Foundation lacks ghee. The
values are well-established textbook per-100g constants; the file is small,
hand-curated and version-controlled (data/curated/staples.csv).

Run:  python -m etl.load_staples   (after USDA + IFCT loaders)
"""
from __future__ import annotations

import csv

from . import db
from .config import NUTRIENT_KEYS, ROOT

CURATED_DIR = ROOT / "data" / "curated"
# full-profile ingredient files (NOT minerals.csv, which is an enrichment file)
INGREDIENT_CSVS = ["staples.csv", "boosters.csv"]


def _slug(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def load() -> int:
    rows: list[dict] = []
    for fname in INGREDIENT_CSVS:
        path = CURATED_DIR / fname
        if not path.exists():
            print(f"[curated] {path} not found — skipping")
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                name = r["name"].strip()
                row = {
                    "id": f"curated:{_slug(name)}",
                    "name": name,
                    "source": "CURATED",
                    "category": r.get("category") or None,
                    "aliases": (r.get("aliases") or "").strip() or None,
                }
                for k in NUTRIENT_KEYS:
                    val = (r.get(k) or "").strip()
                    row[k] = float(val) if val != "" else None
                rows.append(row)

    conn = db.connect()
    written = db.upsert_ingredients(conn, rows)  # appends to USDA+IFCT
    total = db.count_ingredients(conn)
    conn.close()
    print(f"[curated] wrote {written} curated ingredients (db total: {total})")
    return written


if __name__ == "__main__":
    load()
