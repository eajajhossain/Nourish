"""Build all canonical stores from raw data, in order.

Run:  python -m etl.build_all
"""
from __future__ import annotations

from . import enrich, load_recipes, load_staples, load_usda, parse_ifct


def main() -> None:
    print("=== Building ingredients.db ===")
    load_usda.load()    # (re)creates the table, writes USDA rows
    parse_ifct.load()   # appends IFCT rows
    load_staples.load()  # appends curated staples + boosters
    enrich.enrich()     # curated minerals onto existing Indian ingredients
    print("=== Building recipes.db ===")
    load_recipes.load()
    print("=== Done ===")


if __name__ == "__main__":
    main()
