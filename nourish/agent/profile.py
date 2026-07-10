"""Persistent user health profile.

One local user, one row (data/processed/profile.db). Collected once during
onboarding, editable any time — from the sidebar form or by just telling the
agent ("my weight is 72 now"), which routes through update_fields().

Also home to the lenient answer parsers the onboarding uses, so a user can
type "5'7", "170 cm" or "5.5 feet" and all of them land as centimetres.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from ..schema import PROCESSED

PROFILE_DB = PROCESSED / "profile.db"

FIELDS = ("name", "gender", "age", "height_cm", "weight_kg", "activity",
          "diet_pref", "conditions", "condition_details")

_ACTIVITY_FACTOR = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55,
                    "active": 1.725}


def _conn() -> sqlite3.Connection:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PROFILE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT, gender TEXT, age INTEGER,
                height_cm REAL, weight_kg REAL,
                activity TEXT, diet_pref TEXT,
                conditions TEXT, condition_details TEXT,
                updated TEXT
            )""")


def get() -> dict | None:
    init()
    with _conn() as c:
        r = c.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return dict(r) if r else None


def save(**fields) -> None:
    """Insert-or-replace the single profile row."""
    init()
    data = {k: fields.get(k) for k in FIELDS}
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    cols = ", ".join(data)
    with _conn() as c:
        c.execute(
            f"INSERT OR REPLACE INTO profile (id, {cols}) "
            f"VALUES (1, {', '.join('?' for _ in data)})",
            tuple(data.values()),
        )


def update_fields(changes: dict) -> dict:
    """Apply a partial update; unknown keys are ignored. Returns new profile."""
    current = get() or {}
    for k, v in changes.items():
        if k in FIELDS and v not in (None, ""):
            current[k] = v
    save(**current)
    return get()


def clear() -> None:
    init()
    with _conn() as c:
        c.execute("DELETE FROM profile WHERE id = 1")


def is_complete(p: dict | None) -> bool:
    return bool(p) and all(
        p.get(k) for k in ("gender", "age", "height_cm", "weight_kg"))


# ---------------------------------------------------------------- derived
def bmi(p: dict) -> float | None:
    h, w = p.get("height_cm"), p.get("weight_kg")
    if not h or not w:
        return None
    return round(w / (h / 100) ** 2, 1)


def bmi_band(value: float) -> str:
    # Asian-Indian BMI cutoffs (lower than WHO general)
    if value < 18.5:
        return "underweight"
    if value < 23:
        return "healthy"
    if value < 25:
        return "overweight"
    return "obese"


def daily_calories(p: dict) -> int | None:
    """Mifflin-St Jeor × activity factor — a target, not a prescription."""
    h, w, age = p.get("height_cm"), p.get("weight_kg"), p.get("age")
    if not (h and w and age):
        return None
    base = 10 * w + 6.25 * h - 5 * age
    base += 5 if (p.get("gender") or "").startswith("m") else -161
    factor = _ACTIVITY_FACTOR.get(p.get("activity") or "light", 1.375)
    return int(round(base * factor, -1))


def summary(p: dict) -> str:
    """One-line profile summary injected into the agent's system prompt."""
    bits = []
    if p.get("name"):
        bits.append(f"name: {p['name']}")
    if p.get("gender"):
        bits.append(p["gender"])
    if p.get("age"):
        bits.append(f"{p['age']} yrs")
    if p.get("height_cm"):
        bits.append(f"{p['height_cm']:g} cm")
    if p.get("weight_kg"):
        bits.append(f"{p['weight_kg']:g} kg")
    b = bmi(p)
    if b:
        bits.append(f"BMI {b} ({bmi_band(b)})")
    kcal = daily_calories(p)
    if kcal:
        bits.append(f"~{kcal} kcal/day target")
    if p.get("activity"):
        bits.append(f"activity: {p['activity']}")
    if p.get("diet_pref"):
        bits.append(f"diet: {p['diet_pref']}")
    cond = p.get("conditions") or "none reported"
    bits.append(f"health conditions: {cond}")
    if p.get("condition_details"):
        bits.append(f"details: {p['condition_details']}")
    return "; ".join(bits)


# ---------------------------------------------------------------- parsers
_NEGATIVE = re.compile(
    r"^\s*(no+|none|nothing|nope|nahi|nah|na|nil|fit|healthy|all good|"
    r"i am fine|i'?m fine)\b[\s.!]*$", re.I)


def is_negative(text: str) -> bool:
    return bool(_NEGATIVE.match(text or ""))


def parse_gender(text: str) -> str | None:
    t = (text or "").strip().lower()
    if re.search(r"\b(male|man|boy|m|ladka|purush)\b", t) and "fe" not in t:
        return "male"
    if re.search(r"\b(female|woman|girl|f|ladki|mahila)\b", t):
        return "female"
    if re.search(r"\b(other|non.?binary|prefer not)\b", t):
        return "other"
    return None


def parse_age(text: str) -> int | None:
    m = re.search(r"\d{1,3}", text or "")
    if not m:
        return None
    age = int(m.group())
    return age if 5 <= age <= 110 else None


def parse_height_cm(text: str) -> float | None:
    t = (text or "").strip().lower().replace("”", '"').replace("’", "'")
    # 5'7 / 5 ft 7 in / 5 feet 7
    m = re.search(r"(\d)\s*(?:'|ft|feet|foot)\s*(\d{1,2})?", t)
    if m:
        feet, inch = int(m.group(1)), int(m.group(2) or 0)
        return round(feet * 30.48 + inch * 2.54, 1)
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return None
    v = float(m.group(1))
    if "m" in t and "cm" not in t and v < 3:      # 1.7 m
        v *= 100
    elif v < 3:                                    # bare 1.7
        v *= 100
    elif v <= 9:                                   # bare 5.5 -> feet
        v *= 30.48
    return round(v, 1) if 90 <= v <= 250 else None


def parse_weight_kg(text: str) -> float | None:
    t = (text or "").strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return None
    v = float(m.group(1))
    if re.search(r"\b(lb|lbs|pound)", t):
        v *= 0.4536
    return round(v, 1) if 20 <= v <= 350 else None


def parse_activity(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"very|gym|athlete|heavy|daily (run|sport)|active every", t):
        return "active"
    if re.search(r"moder|walk|yoga|exercise|3-4|sometimes", t):
        return "moderate"
    if re.search(r"sit|desk|sedentary|no exercise|lazy|rarely", t):
        return "sedentary"
    return "light"


def parse_diet(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"non.?veg|chicken|mutton|fish|meat", t):
        return "non-vegetarian"
    if re.search(r"egg", t):
        return "eggetarian"
    if re.search(r"vegan", t):
        return "vegan"
    return "vegetarian"
