"""Parse Indian ingredient nutrition from the IFCT 2017 PDF.

IFCT spreads each food across several tables keyed by a food code (e.g. E017).
The tables are not ruled, but text rows are regular:

    <CODE> <name (scientific)> <#regions> <v1> <v2> ... <vN>

where each value is `mean` or `mean±sd` (the ± renders as a stray byte).

We parse the cleanly-extractable single-page PROXIMATE table (p41-68):
protein, fat, fibre, carbohydrate, energy(kJ). MINERALS and VITAMINS are
deferred: those tables have rows with missing trailing values and (minerals)
split across facing pages, so column positions misalign on text extraction.
USDA covers sodium/calcium/iron/vitamin-C in the meantime. Better a null than
a wrong number — the whole engine depends on these values being right.

Run:  python -m etl.parse_ifct
"""
from __future__ import annotations

import re
import warnings

import pdfplumber

from . import db
from .config import IFCT_PDF, NUTRIENT_KEYS

warnings.filterwarnings("ignore")

# Page range (1-indexed, inclusive) located by scanning header signatures.
PROXIMATE_PAGES = (41, 68)

# PROXIMATE column order: WATER PROTCNT ASH FATCE [FIBTG FIBINS FIBSOL CHOAVLDF] ENERC
# Always present: WATER PROTCNT ASH FATCE (start) and ENERC (end) -> 5 columns.
# The middle block (fibre sub-columns + carbohydrate) is omitted column-by-
# column for foods that don't report them:
#   5 values  animal foods (egg/meat/fish): no carb, no fibre
#   6 values  + carbohydrate (dairy)
#   7-9 vals  + total/insoluble/soluble fibre
# CHOAVLDF, when present, is always the value just before ENERC; FIBTG (total
# fibre), when present, is always the 5th value. Anchoring this way is robust
# to the variable middle without ever mis-reading a column.
MIN_VALUES, MAX_VALUES = 5, 9

CODE_RE = re.compile(r"^([A-Z]\d{3}[A-Z]?)\b(.*)$")
VALUE_RE = re.compile(r"^\d+(?:\.\d+)?(?:[^\d\s]\d+(?:\.\d+)?)?$")


def _mean(token: str) -> float | None:
    """Take the mean from a 'mean' or 'mean±sd' token."""
    m = re.match(r"^(\d+(?:\.\d+)?)", token)
    return float(m.group(1)) if m else None


def _parse_row(line: str):
    """Return (code, name, scientific, profile_dict) or None.

    Layout after the code: <name...> <regions int> <v1..vN>. We take the
    maximal numeric suffix (regions + values), so the first numeric token is
    the region count and the rest are nutrient values. Anchoring from both
    ends makes column mapping robust to the variable fibre block.
    """
    m = CODE_RE.match(line)
    if not m:
        return None
    code, rest = m.group(1), m.group(2).strip()
    tokens = rest.split()

    # maximal trailing run of numeric tokens = [regions, v1..vN]
    suffix: list[str] = []
    for tok in reversed(tokens):
        if VALUE_RE.match(tok):
            suffix.insert(0, tok)
        else:
            break
    if len(suffix) < MIN_VALUES + 1:        # need regions + >=6 values
        return None
    values = [_mean(t) for t in suffix[1:]] # drop regions
    if not (MIN_VALUES <= len(values) <= MAX_VALUES):
        return None

    name_tokens = tokens[: len(tokens) - len(suffix)]
    name = " ".join(name_tokens).strip()
    sci = None
    smatch = re.search(r"\(([^)]+)\)", name)
    if smatch:
        sci = smatch.group(1).strip()
        name = name[: smatch.start()].strip()
    name = name.rstrip(", ")
    if not name:
        name = code

    # both-ends anchored mapping; carb present iff >=6 values, total fibre
    # present iff >=7 values (see column-order note above)
    profile = {
        "protein_g": values[1],
        "fat_g": values[3],
        "carb_g": values[-2] if len(values) >= 6 else None,
        "kcal": None if values[-1] is None else values[-1] / 4.184,  # kJ->kcal
        "fibre_g": values[4] if len(values) >= 7 else None,
    }
    profile = {k: (None if v is None else round(v, 3)) for k, v in profile.items()}
    return code, name, sci, profile


def load() -> int:
    print(f"[ifct] opening {IFCT_PDF.name}")
    pdf = pdfplumber.open(IFCT_PDF)

    parsed: dict[str, dict] = {}
    lo, hi = PROXIMATE_PAGES
    for pno in range(lo - 1, hi):
        for line in (pdf.pages[pno].extract_text() or "").split("\n"):
            row = _parse_row(line)
            if not row:
                continue
            code, name, sci, profile = row
            if code in parsed:
                continue
            parsed[code] = {"name": name, "sci": sci, **profile}
    pdf.close()
    print(f"[ifct] proximate rows: {len(parsed)}")

    rows: list[dict] = []
    for code, prof in parsed.items():
        row = {
            "id": f"ifct:{code}",
            "name": prof["name"],
            "source": "IFCT",
            "category": None,
            "aliases": prof["sci"],
        }
        for k in NUTRIENT_KEYS:
            row[k] = prof.get(k)  # only proximate cols set; rest stay None
        rows.append(row)

    conn = db.connect()
    written = db.upsert_ingredients(conn, rows)  # adds to existing USDA rows
    total = db.count_ingredients(conn)
    conn.close()
    print(f"[ifct] wrote {written} IFCT ingredients (db total: {total})")
    return written


if __name__ == "__main__":
    load()
