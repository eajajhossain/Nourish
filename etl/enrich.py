"""Enrich existing ingredients with curated mineral values.

IFCT 2017's minerals table can't be reliably parsed from the PDF (blank
columns drop with no stable anchor, so iron/calcium positions shift). Rather
than risk wrong values in a health app, we UPDATE a small set of important
Indian ingredients by exact name with accurate published per-100g minerals
(IFCT 2017 / NIN). Only the listed columns are touched.

Run:  python -m etl.enrich   (after the ingredient loaders)
"""
from __future__ import annotations

import csv

from . import db
from .config import ROOT

MINERALS_CSV = ROOT / "data" / "curated" / "minerals.csv"
COLS = ["calcium_mg", "iron_mg", "sodium_mg"]


def enrich() -> int:
    if not MINERALS_CSV.exists():
        print(f"[enrich] {MINERALS_CSV} not found — skipping")
        return 0

    conn = db.connect()
    updated = 0
    with open(MINERALS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = r["name"].strip()
            sets, vals = [], []
            for c in COLS:
                v = (r.get(c) or "").strip()
                if v != "":
                    sets.append(f"{c} = ?")
                    vals.append(float(v))
            if not sets:
                continue
            vals.append(name)
            cur = conn.execute(
                f"UPDATE ingredients SET {', '.join(sets)} WHERE name = ?", vals
            )
            updated += cur.rowcount
    conn.commit()
    conn.close()
    print(f"[enrich] updated minerals on {updated} ingredient rows")
    return updated


if __name__ == "__main__":
    enrich()
