"""Friendly log of the dishes the user has asked the agent about.

Lives in the same history.db as the old transformer log but in its own
table — the agent reads it to answer "what did I ask you last week?" and the
UI shows it in the sidebar.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from ..schema import PROCESSED

HISTORY_DB = PROCESSED / "history.db"


def _conn() -> sqlite3.Connection:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS dish_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                dish TEXT NOT NULL
            )""")


def log_dish(dish: str) -> None:
    """Record a dish the user asked about (deduped against the last entry)."""
    init()
    dish = (dish or "").strip()
    if not dish:
        return
    with _conn() as c:
        last = c.execute("SELECT dish FROM dish_queries "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        if last and last["dish"].lower() == dish.lower():
            return
        c.execute("INSERT INTO dish_queries (ts, dish) VALUES (?, ?)",
                  (datetime.now().isoformat(timespec="seconds"), dish))


def _friendly_when(ts: str) -> str:
    then = datetime.fromisoformat(ts)
    days = (datetime.now().date() - then.date()).days
    if days == 0:
        return "today " + then.strftime("%H:%M")
    if days == 1:
        return "yesterday"
    if days < 7:
        return then.strftime("%A").lower()
    return then.strftime("%d %b")


def recent(limit: int = 12) -> list[dict]:
    init()
    with _conn() as c:
        rows = c.execute("SELECT * FROM dish_queries ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
    return [{"dish": r["dish"], "when": _friendly_when(r["ts"]), "ts": r["ts"]}
            for r in rows]


def friendly_lines(limit: int = 12) -> list[str]:
    return [f"{r['dish']} — {r['when']}" for r in recent(limit)]
