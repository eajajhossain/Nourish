"""RAG evaluation harness.

    python -m nourish.agent.evaluate              # all categories
    python -m nourish.agent.evaluate --no-vector  # skip categories that need
                                                  # the embedding API

Measures each level of the retrieval cascade against eval/golden_set.yaml:
  dish_lookup    hit@1 / hit@3 of the vector-less fuzzy lookup
  semantic       hit@4 of the Chroma vector search
  out_of_corpus  does the web fallback trigger when it should?

Writes eval/RESULTS.md so the numbers live in the repo.
"""
from __future__ import annotations

import sys
from datetime import date

import yaml

from ..schema import ROOT
from . import vectorless, vectorstore

GOLDEN = ROOT / "eval" / "golden_set.yaml"
RESULTS = ROOT / "eval" / "RESULTS.md"
WEAK = 0.2  # same threshold the live tool uses for the web fallback


def _contains(text: str, expects: list[str]) -> bool:
    t = text.lower()
    return any(e.lower() in t for e in expects)


def eval_dish_lookup(cases: list[dict]) -> dict:
    hit1 = hit3 = 0
    misses = []
    for c in cases:
        hits = vectorless.find_dish(c["query"], limit=3)
        names = [h["name"] for h in hits]
        if names and _contains(names[0], c["expect"]):
            hit1 += 1
            hit3 += 1
        elif any(_contains(n, c["expect"]) for n in names):
            hit3 += 1
            misses.append((c["query"], names[0], "@1"))
        else:
            misses.append((c["query"], names[0] if names else "—", "@3"))
    n = len(cases)
    return {"n": n, "hit@1": hit1 / n, "hit@3": hit3 / n, "misses": misses}


def eval_semantic(cases: list[dict]) -> dict:
    hit4 = 0
    misses = []
    for c in cases:
        docs = vectorstore.search(c["query"], k=4)
        if any(_contains(d["text"], c["expect"]) for d in docs):
            hit4 += 1
        else:
            top = docs[0]["text"][:60] if docs else "—"
            misses.append((c["query"], top, "@4"))
    n = len(cases)
    return {"n": n, "hit@4": hit4 / n, "misses": misses}


def eval_fallback(cases: list[dict], use_vector: bool) -> dict:
    """A fallback is CORRECT when the confident vector-less hit is absent and
    (if measurable) the vector score is weak — i.e. the live tool would have
    chained the web search."""
    correct = 0
    misses = []
    for c in cases:
        confident = vectorless.confident_hit(c["query"])
        weak_vec = True
        if use_vector:
            docs = vectorstore.search(c["query"], k=1)
            weak_vec = (not docs) or docs[0]["score"] < WEAK
        if confident is None and weak_vec:
            correct += 1
        else:
            why = (f"confident DB hit: {confident['name']}" if confident
                   else "vector score above threshold")
            misses.append((c["query"], why, ""))
    n = len(cases)
    return {"n": n, "fallback_rate": correct / n, "misses": misses}


def main() -> None:
    use_vector = "--no-vector" not in sys.argv
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))

    print("Nourish RAG evaluation\n" + "=" * 40)
    lookup = eval_dish_lookup(golden["dish_lookup"])
    print(f"dish_lookup   n={lookup['n']:>2}  hit@1={lookup['hit@1']:.0%}  "
          f"hit@3={lookup['hit@3']:.0%}")

    semantic = None
    if use_vector and vectorstore.ready():
        semantic = eval_semantic(golden["semantic"])
        print(f"semantic      n={semantic['n']:>2}  "
              f"hit@4={semantic['hit@4']:.0%}")
    else:
        print("semantic      skipped (index not built or --no-vector)")

    fallback = eval_fallback(golden["out_of_corpus"],
                             use_vector and vectorstore.ready())
    print(f"out_of_corpus n={fallback['n']:>2}  "
          f"fallback_rate={fallback['fallback_rate']:.0%}")

    for name, res in (("dish_lookup", lookup), ("semantic", semantic),
                      ("out_of_corpus", fallback)):
        if res and res["misses"]:
            print(f"\n{name} misses:")
            for q, got, level in res["misses"]:
                print(f"  {level:3} {q!r} -> {got}")

    lines = [
        "# RAG Evaluation Results", "",
        f"*Generated {date.today().isoformat()} by "
        "`python -m nourish.agent.evaluate` against `eval/golden_set.yaml`.*",
        "",
        "| Cascade level | Retriever | Cases | Metric | Score |",
        "|---|---|---|---|---|",
        f"| 1 — vector-less RAG | RapidFuzz over recipes.db "
        f"| {lookup['n']} | hit@1 | **{lookup['hit@1']:.0%}** |",
        f"| 1 — vector-less RAG |  | {lookup['n']} | hit@3 "
        f"| **{lookup['hit@3']:.0%}** |",
    ]
    if semantic:
        lines.append(f"| 2 — vector RAG | Chroma + MiniLM | {semantic['n']} "
                     f"| hit@4 | **{semantic['hit@4']:.0%}** |")
    lines.append(f"| 3 — web fallback | score-gated Tavily chain "
                 f"| {fallback['n']} | fallback triggered when it should "
                 f"| **{fallback['fallback_rate']:.0%}** |")
    lines += ["",
              "Known misses are kept in the golden set on purpose — the "
              "score should stay honest. See `golden_set.yaml` for the "
              "`# known hard` cases."]
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {RESULTS}")


if __name__ == "__main__":
    main()
