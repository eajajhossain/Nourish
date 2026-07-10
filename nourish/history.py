"""Local history of recipe transformations.

A single SQLite log (data/processed/history.db). It is deliberately separate
from ingredients/recipes and is never read by the engine -- it's a UI feature,
not a dependency. No accounts: one local log for this install.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .schema import PROCESSED

HISTORY_DB = PROCESSED / "history.db"


def _conn() -> sqlite3.Connection:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                dish      TEXT,
                goal      TEXT NOT NULL,
                before    TEXT NOT NULL,   -- json of totals
                after     TEXT NOT NULL,   -- json of totals
                swaps     TEXT NOT NULL,   -- json list
                insights  TEXT NOT NULL,   -- json list
                narrative TEXT
            )
            """
        )


def save_transformation(t, insights: list[str], dish: str | None = None,
                        narrative: str = "") -> int:
    """Persist a single Transformation (+ insights). Returns the new row id."""
    init()
    swaps = [
        {
            "original": s.original_name,
            "replacement": (None if s.is_reduction else s.replacement_name),
            "reduction": s.is_reduction,
            "addition": s.is_addition,
            "reason": s.reason,
        }
        for s in t.swaps
    ]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO history (ts, dish, goal, before, after, swaps, "
            "insights, narrative) VALUES (?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                dish or "",
                t.goal,
                json.dumps(t.before.totals),
                json.dumps(t.after.totals),
                json.dumps(swaps),
                json.dumps(insights),
                narrative,
            ),
        )
        return cur.lastrowid


def save(result, dish: str | None = None) -> int:
    """Persist a pipeline RecipeResult. Returns the new row id."""
    return save_transformation(result.transformation, result.insights,
                               dish=dish, narrative=result.narrative)


def _row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "ts": r["ts"],
        "dish": r["dish"],
        "goal": r["goal"],
        "before": json.loads(r["before"]),
        "after": json.loads(r["after"]),
        "swaps": json.loads(r["swaps"]),
        "insights": json.loads(r["insights"]),
        "narrative": r["narrative"],
    }


def list_recent(limit: int = 20) -> list[dict]:
    init()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get(history_id: int) -> dict | None:
    init()
    with _conn() as c:
        r = c.execute("SELECT * FROM history WHERE id = ?",
                      (history_id,)).fetchone()
    return _row_to_dict(r) if r else None
