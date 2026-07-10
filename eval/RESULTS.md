# RAG Evaluation Results

*Generated 2026-07-08 by `python -m nourish.agent.evaluate` against `eval/golden_set.yaml`.*

| Cascade level | Retriever | Cases | Metric | Score |
|---|---|---|---|---|
| 1 — vector-less RAG | RapidFuzz over recipes.db | 24 | hit@1 | **92%** |
| 1 — vector-less RAG |  | 24 | hit@3 | **92%** |
| 2 — vector RAG | Chroma + MiniLM | 10 | hit@4 | **40%** |
| 3 — web fallback | score-gated Tavily chain | 8 | fallback triggered when it should | **88%** |

Known misses are kept in the golden set on purpose — the score should stay honest. See `golden_set.yaml` for the `# known hard` cases.
