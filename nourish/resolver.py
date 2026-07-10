"""Resolve a free-text ingredient name to an ingredient id.

Layered, cheapest-first:
  1. exact      — name (or IFCT scientific alias) matches exactly
  2. alias      — Hinglish/colloquial synonym (aliases.py) then exact
  3. fuzzy      — rapidfuzz token_set_ratio over names + aliases
  4. semantic   — optional embeddings fallback (rag.py) when fuzzy is weak

Returns the best candidate plus alternatives and a confidence score, so the
pipeline (and UI) can flag low-confidence matches instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from . import aliases, data_access, rag
from .data_access import Ingredient

ACCEPT_SCORE = 75.0   # at/above this we consider it a confident match


@dataclass
class ResolveResult:
    query: str
    ingredient: Ingredient | None
    score: float
    method: str                      # exact | alias | fuzzy | semantic | none
    alternatives: list[Ingredient] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ingredient is not None and self.score >= ACCEPT_SCORE


@lru_cache(maxsize=1)
def _corpus() -> list[tuple[str, tuple[str, ...], str]]:
    """List of (search_string, tokens, ingredient_id). Each ingredient may add
    its name and its scientific alias as separate searchable entries."""
    rows: list[tuple[str, tuple[str, ...], str]] = []
    for ing in data_access.all_ingredients():
        name = ing.name.lower()
        rows.append((name, tuple(re.split(r"[ ,]+", name)), ing.id))
        # aliases may hold several '|'-separated alternates (curated) or a
        # single scientific name (IFCT); index each separately.
        for al in (ing.aliases or "").lower().split("|"):
            al = al.strip()
            if al:
                rows.append((al, tuple(re.split(r"[ ,]+", al)), ing.id))
    return rows


@lru_cache(maxsize=1)
def _exact_index() -> dict[str, str]:
    """name/alias (lower) -> ingredient id, for O(1) exact hits."""
    idx: dict[str, str] = {}
    for ing in data_access.all_ingredients():
        idx.setdefault(ing.name.lower(), ing.id)
        for al in (ing.aliases or "").lower().split("|"):
            al = al.strip()
            if al:
                idx.setdefault(al, ing.id)
    return idx


# Processed-form descriptors. When a candidate name contains one of these but
# the query doesn't ask for it, it's probably not the base ingredient the user
# meant (e.g. query 'potato' -> prefer 'Potatoes, raw' over 'Flour, potato').
FORM_WORDS = {
    "flour", "flake", "flakes", "powder", "powdered", "fried", "restaurant",
    "sauce", "canned", "dried", "juice", "paste", "syrup", "baby", "infant",
    "beverage", "snack", "puffed", "roasted", "boiled",
}
FORM_PENALTY = 18.0


HEAD_BONUS = 15.0


def _form_penalty(term: str, candidate: str) -> float:
    qwords = set(term.lower().split())
    cwords = set(candidate.replace(",", " ").lower().split())
    if (cwords & FORM_WORDS) - qwords:
        return FORM_PENALTY
    return 0.0


def _head_bonus(term: str, candidate: str) -> float:
    """Reward candidates whose name starts with a query word -- canonical
    entries are usually named '<ingredient>, <descriptor>' (e.g. 'Potato,
    brown skin' or 'Rice, raw'), so the head word carries the identity."""
    head = candidate.split(",")[0].strip().lower()
    head_first = head.split()[0] if head else ""
    for qt in term.lower().split():
        if head_first and fuzz.ratio(qt, head_first) >= 85:
            return HEAD_BONUS
    return 0.0


def _coverage(qtokens: list[str], ctokens: tuple[str, ...]) -> float:
    """Fraction of query tokens that strongly match some candidate token.

    Unlike token_set_ratio this ignores extra descriptor words, so a query is
    scored the same whether the canonical name is 'Potato' or 'Potato, brown
    skin, big' -- letting head-bonus / form-penalty pick the right variant."""
    if not qtokens:
        return 0.0
    matched = 0
    for q in qtokens:
        for c in ctokens:
            if not c:
                continue
            if fuzz.ratio(q, c) >= 85 or (len(q) >= 4 and q in c):
                matched += 1
                break
    return 100.0 * matched / len(qtokens)


def _fuzzy(term: str, limit: int = 5) -> list[tuple[str, float]]:
    """Return (ingredient_id, score) best matches for term.

    Primary score is query-token coverage; a processed-form penalty and a
    head-word bonus disambiguate between variants; WRatio breaks remaining
    ties (prefers the closer/shorter name). Coverage means a multi-word query
    only scores high when most of its words are present -- so genuinely absent
    ingredients (no 'mustard oil' entry) stay low-confidence instead of
    snapping to a wrong short match."""
    qtokens = term.split()
    best: dict[str, tuple[float, float]] = {}
    for cand_string, ctokens, iid in _corpus():
        cov = _coverage(qtokens, ctokens)
        if cov == 0.0:
            continue
        score = cov - _form_penalty(term, cand_string) + _head_bonus(term, cand_string)
        wr = float(fuzz.WRatio(term, cand_string))
        cur = best.get(iid)
        if cur is None or (score, wr) > cur:
            best[iid] = (score, wr)
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    return [(iid, max(0.0, sc)) for iid, (sc, _wr) in ranked][:limit]


def resolve(query: str, use_semantic: bool = True) -> ResolveResult:
    raw = (query or "").strip()
    if not raw:
        return ResolveResult(query, None, 0.0, "none")

    norm = raw.lower()
    expanded = aliases.expand(norm).lower()
    tok_expanded = aliases.expand_tokens(norm)

    # 1 & 2: exact / alias
    exact = _exact_index()
    for term, method in ((norm, "exact"), (expanded, "alias")):
        if term in exact:
            return ResolveResult(raw, data_access.get(exact[term]), 100.0, method)

    # 3: fuzzy (try raw, whole-alias, and token-wise expanded; keep the best)
    candidates: dict[str, float] = {}
    for term in {norm, expanded, tok_expanded}:
        for iid, score in _fuzzy(term):
            if iid not in candidates or score > candidates[iid]:
                candidates[iid] = score
    ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)

    best_id, best_score, method = (None, 0.0, "none")
    if ranked:
        best_id, best_score = ranked[0]
        method = "fuzzy"

    # 4: semantic fallback only when fuzzy is weak and rag is available
    if best_score < ACCEPT_SCORE and use_semantic and rag.available():
        sem = rag.search(expanded, k=3)
        if sem and sem[0][1] > best_score:
            best_id, best_score = sem[0]
            method = "semantic"
            ranked = sem + ranked

    if best_id is None:
        return ResolveResult(raw, None, 0.0, "none")

    alts = [data_access.get(i) for i, _ in ranked[1:4] if data_access.get(i)]
    return ResolveResult(raw, data_access.get(best_id),
                         round(min(100.0, best_score), 1), method, alts)


def resolve_many(names: list[str]) -> list[ResolveResult]:
    return [resolve(n) for n in names]


if __name__ == "__main__":
    tests = ["atta", "aloo", "mustard oil", "toor dal", "jeera",
             "paneer", "basmati rice", "gobi", "xyzzy unknown"]
    print("=== resolver demo ===")
    for t in tests:
        r = resolve(t)
        name = r.ingredient.name if r.ingredient else "—"
        flag = "" if r.ok else "  (low confidence)"
        print(f"  {t:18} -> {name[:34]:36} [{r.method} {r.score}]{flag}")
