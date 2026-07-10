"""Parse free-text recipe lines into structured (name, qty, unit) items.

A deterministic parser handles the common formats with zero cost:
    "150 g atta"  "2 tbsp ghee"  "1 onion"  "1/2 tsp salt"  "2-3 tomatoes"
    "a cup of rice"  "salt to taste"

When an LLM provider is configured (see llm.py) it is used for messier prose
and the deterministic parser remains the fallback. Either way the output shape
is identical, and no nutrition numbers are ever invented here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import units

NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "half": 0.5, "quarter": 0.25, "couple": 2, "few": 3,
}
UNICODE_FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1/3, "⅔": 2/3, "⅛": 0.125}

UNIT_SYN = {
    "tablespoons": "tbsp", "tablespoon": "tbsp", "tbsp.": "tbsp", "tbs": "tbsp",
    "teaspoons": "tsp", "teaspoon": "tsp", "tsp.": "tsp",
    "grams": "g", "gram": "g", "gm": "g", "gms": "g", "g.": "g",
    "kgs": "kg", "kilograms": "kg", "kilogram": "kg",
    "cups": "cup", "pieces": "piece", "pcs": "piece", "pc": "piece",
    "nos": "piece", "no.": "piece", "litre": "l", "liter": "l",
    "litres": "l", "liters": "l", "ml.": "ml", "katoris": "katori",
    "glasses": "glass",
}
KNOWN_UNITS = (set(units.MASS_TO_G) | set(units.VOLUME_TO_ML)
               | set(units.COUNT_UNITS)) - {""}

_TO_TASTE = re.compile(r"\b(to taste|as needed|as required|for garnish)\b", re.I)


@dataclass
class ParsedItem:
    name: str
    qty: float
    unit: str
    raw: str


def _as_number(tok: str) -> float | None:
    tok = tok.strip().lower()
    if tok in NUM_WORDS:
        return float(NUM_WORDS[tok])
    if tok in UNICODE_FRAC:
        return UNICODE_FRAC[tok]
    if re.fullmatch(r"\d+/\d+", tok):              # fraction 1/2
        a, b = tok.split("/")
        return float(a) / float(b) if float(b) else None
    if re.fullmatch(r"\d*\.?\d+\s*[-–]\s*\d*\.?\d+", tok):  # range 2-3
        a, b = re.split(r"[-–]", tok)
        return (float(a) + float(b)) / 2
    if re.fullmatch(r"\d*\.?\d+", tok):
        return float(tok)
    return None


def _lead_qty(tokens: list[str]) -> tuple[float | None, int]:
    """Return (quantity, tokens_consumed) from the start of the line."""
    if not tokens:
        return None, 0
    # mixed number: "1 1/2"
    if len(tokens) >= 2 and re.fullmatch(r"\d+", tokens[0]) \
            and re.fullmatch(r"\d+/\d+", tokens[1]):
        whole = float(tokens[0])
        frac = _as_number(tokens[1]) or 0
        return whole + frac, 2
    n = _as_number(tokens[0])
    if n is not None:
        return n, 1
    return None, 0


def parse_line(raw: str) -> ParsedItem | None:
    s = raw.strip().lstrip("-*••").strip()
    s = re.sub(r"^\d+[.)]\s*", "", s)         # drop "1. " / "2) " numbering
    if not s:
        return None

    to_taste = bool(_TO_TASTE.search(s))
    s = _TO_TASTE.sub("", s).strip(" ,.-")
    if not s:
        return None

    tokens = s.split()
    qty, consumed = _lead_qty(tokens)
    rest = tokens[consumed:]
    if rest and rest[0].lower() == "of":
        rest = rest[1:]

    if qty is None:
        # no leading number: a single item ("salt", "2 onions" handled above)
        qty = 0.5 if to_taste else 1.0
        unit = "tsp" if to_taste else "piece"
        name = " ".join(rest) or s
        return ParsedItem(name.strip(" ,."), qty, unit, raw)

    unit = ""
    if rest:
        u = rest[0].lower().strip(".")
        u = UNIT_SYN.get(u, u)
        if u in KNOWN_UNITS:
            unit = u
            rest = rest[1:]
    if not unit:
        unit = "tsp" if to_taste else "piece"

    if rest and rest[0].lower() == "of":   # "a cup of rice"
        rest = rest[1:]
    name = " ".join(rest).strip(" ,.")
    if not name:
        return None
    return ParsedItem(name, qty, unit, raw)


def _split_lines(text: str) -> list[str]:
    # split on newlines / semicolons; fall back to commas if it's one line
    parts = re.split(r"[\n;]+", text.strip())
    if len(parts) == 1 and "," in text:
        parts = re.split(r",(?![^()]*\))", text)  # commas not inside parens
    return [p for p in (p.strip() for p in parts) if p]


def parse_recipe(text: str, use_llm: bool = True) -> list[ParsedItem]:
    """Parse a recipe block into structured items.

    Tries an LLM if one is configured and `use_llm`; always falls back to the
    deterministic parser so this works offline at zero cost."""
    if use_llm:
        try:
            from . import llm
            if llm.available():
                items = llm.parse_recipe_items(text)
                if items:
                    return items
        except Exception:
            pass  # any LLM failure -> deterministic fallback

    out: list[ParsedItem] = []
    for line in _split_lines(text):
        item = parse_line(line)
        if item:
            out.append(item)
    return out
