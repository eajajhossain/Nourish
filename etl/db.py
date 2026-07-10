"""SQLite helpers for the canonical ingredient store.

The `ingredients` table is the single per-100g source the Nutrition Engine
reads. Both USDA and IFCT loaders write rows in this exact shape.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import INGREDIENTS_DB, NUTRIENT_KEYS, PROCESSED


def connect(db_path: Path = INGREDIENTS_DB) -> sqlite3.Connection:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def create_ingredients_table(conn: sqlite3.Connection) -> None:
    """(Re)create the ingredients table with the canonical schema."""
    nutrient_cols = ",\n        ".join(f"{k} REAL" for k in NUTRIENT_KEYS)
    conn.executescript(
        f"""
        DROP TABLE IF EXISTS ingredients;
        CREATE TABLE ingredients (
            id        TEXT PRIMARY KEY,   -- e.g. 'usda:321358' or 'ifct:A001'
            name      TEXT NOT NULL,
            source    TEXT NOT NULL,      -- 'IFCT' | 'USDA'
            category  TEXT,
            {nutrient_cols},
            aliases   TEXT                -- '|'-joined alternate names
        );
        CREATE INDEX idx_ingredients_name ON ingredients(name);
        """
    )
    conn.commit()


def upsert_ingredients(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert ingredient rows. Returns number written."""
    cols = ["id", "name", "source", "category", *NUTRIENT_KEYS, "aliases"]
    placeholders = ", ".join("?" for _ in cols)
    sql = (
        f"INSERT OR REPLACE INTO ingredients ({', '.join(cols)}) "
        f"VALUES ({placeholders})"
    )
    data = [[r.get(c) for c in cols] for r in rows]
    conn.executemany(sql, data)
    conn.commit()
    return len(data)


def count_ingredients(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
