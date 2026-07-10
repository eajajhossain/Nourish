# Nourish — Complete Project Guide

*Everything about this project in one place: what it is, the tech stack, the
architecture, how it was built, and the design decisions behind it. Written
so you can explain any part of it confidently.*

---

## 1. The 30-second pitch (say this first)

> "Nourish is a personal Indian food & nutrition companion. It first gets to
> know the user through a conversational onboarding — gender, age, height,
> weight, activity, diet, and any health conditions — built as a
> human-in-the-loop LangGraph flow. After that, the user can name any Indian
> dish and the agent answers with the dish's history, a step-by-step recipe,
> the right portion *for that specific user*, exact nutrition numbers, and
> personalised health tips. It uses a **hybrid RAG** design: a vector-less
> lookup over a local SQLite database of 1,014 Indian dishes first, semantic
> search over a Chroma vector store second, and Tavily web search only as a
> fallback. The core principle: **the LLM never produces a nutrition number —
> every number comes from a deterministic engine or a database.**"

## 2. What the app does (user journey)

1. **First visit** → the agent asks onboarding questions one by one in chat
   (name → gender → age → height → weight → activity → diet preference →
   health conditions). If the user mentions a condition, it asks a follow-up:
   *"please describe it a little"*. Bad answers get politely re-asked.
2. **Profile saved** → BMI (Asian-Indian cutoffs), daily calorie target
   (Mifflin-St Jeor × activity factor) computed; editable anytime from the
   sidebar form OR by just telling the agent ("my weight is 65 now").
3. **Dish questions** → "masala dosa" returns: 📜 the dish's real history
   (web-sourced), 🧺 ingredients with quantities, 👩‍🍳 8–14 beginner steps,
   🍽️ portion for this user, 📊 nutrition table (database numbers), 💚
   personalised tips.
4. **Diet chart** → a one-day meal plan built deterministically from real
   dishes, sized to the calorie target and filtered by conditions
   (diabetes → low sugar, hypertension → low sodium, anemia → high iron)
   and diet preference (veg/eggetarian/non-veg).
5. **Food journey** → every dish asked is logged; the sidebar shows it with
   friendly timestamps ("Masala Dosa · yesterday", tappable to revisit), and
   the agent references it warmly in conversation.

## 3. Tech stack (and WHY each piece)

| Layer | Technology | Why this choice |
|---|---|---|
| LLM (the brain) | **Groq API — Llama 3.3 70B** | Free tier, very fast inference, good tool-calling; swappable via env var |
| Agent framework | **LangGraph** (+ LangChain) | Graph-based state machine: first-class `interrupt()` for human-in-the-loop, checkpointing for memory, conditional edges for routing |
| Tool layer | **LangChain `@tool`** | Declarative tool schemas the LLM can call; 11 tools |
| Conversation memory | **LangGraph SqliteSaver** | Checkpoints every step to SQLite → chat survives restarts ("memory saver") |
| Vector-less RAG | **SQLite + RapidFuzz** | The dish table is small enough that fuzzy name matching IS retrieval — exact, instant, zero cost |
| Vector RAG | **ChromaDB** (persistent, local) | Simple local vector store; 2,311 documents |
| Embeddings | **MiniLM-L6-v2 via HuggingFace Inference API** | No heavy local model download; falls back to Chroma's local ONNX if the key is absent |
| Web fallback | **Tavily Search API** | LLM-friendly search results; used for rare dishes, trusted recipe steps, and dish history |
| Nutrition math | **Pure Python engine** (pandas at ETL time) | Deterministic, unit-tested — the LLM never does arithmetic |
| Data | IFCT 2017 (PDF), USDA FoodData Central, Indian dish nutrition CSV | Authoritative Indian + international composition data |
| UI | **Streamlit** (chat components + custom CSS) | Fast to build, python-native; theme pinned via `.streamlit/config.toml` |
| Storage | **SQLite everywhere** (5 stores) | Zero-ops, file-based, perfect for a local-first app |
| Testing | **pytest + Streamlit AppTest** | 96 tests, all runnable offline — no LLM or network needed |
| Evaluation | **golden-set RAG harness** | measured hit-rates per cascade level, results in the repo |

## 4. Architecture

```
┌─────────────────────────── Streamlit UI (app.py) ───────────────────────────┐
│  chat transcript · onboarding via chat · profile card · food journey        │
└──────────────────────────────────┬───────────────────────────────────────---┘
                                   │ invoke / Command(resume=…)
┌──────────────────────────── LangGraph (graph.py) ────────────────────────────┐
│  START ─┬─ profile incomplete ──▶ ONBOARDING NODE                            │
│         │                         interrupt() per question → profile.db      │
│         └─ profile complete ────▶ AGENT NODE ◀────────▶ TOOL NODE            │
│                                   (Groq LLM,            (11 tools)           │
│                                    system prompt =                           │
│                                    live profile + rules)                     │
│  checkpoints.db (SqliteSaver) = conversation memory                          │
└──────────────────────────────────┬───────────────────────────────────────---┘
                                   │ tool calls
        ┌──────────────┬───────────┴──────────┬────────────────┐
   vector-less RAG   vector RAG          web (Tavily)     deterministic engine
   rapidfuzz over    Chroma over         web_search,      parse → resolve →
   recipes.db        2,311 docs          recipe fetch,    compute → swap
   (1,014 dishes)    (dishes + curated   dish story       (nutrition_engine,
                     recipes + IFCT PDF)                   swap_engine)
```

**The retrieval cascade (hybrid RAG).** For any dish question:
1. `lookup_dish_database` — vector-less: fuzzy name match over SQLite. When
   it hits, the row itself is the exact grounded answer.
2. `search_knowledge_base` — semantic: Chroma + MiniLM embeddings, for
   descriptive questions ("high-iron breakfast") or when names don't match.
3. **Deterministic fallback**: if the best vector score is weak (< 0.2), the
   tool *itself* chains a Tavily web search and returns those results too —
   we don't rely on the LLM choosing to escalate (it often didn't).
4. `get_recipe_from_web` / `get_dish_story_from_web` — dedicated deep
   searches so cooking steps and dish history are grounded in real sources.

**Human-in-the-loop onboarding.** The onboarding node calls LangGraph's
`interrupt(question)` for each question. `interrupt` pauses the graph and
persists state; the UI shows the question and sends the user's reply back
with `Command(resume=answer)`. On resume, the node re-executes from the top
and previously answered interrupts replay their values — so the flow is
deterministic and even a retry-until-parseable loop works.

**State design.** Only `messages` live in graph state. The health profile
lives OUTSIDE the graph in its own SQLite store — deliberately, so it can be
edited anytime (sidebar form, or the LLM calling `update_user_profile`)
without touching checkpoint history, and every new conversation immediately
sees the current profile via the system prompt.

**The 11 tools** (`nourish/agent/tools.py`):
`lookup_dish_database`, `search_knowledge_base`, `web_search`,
`get_recipe_from_web`, `get_dish_story_from_web`, `compute_recipe_nutrition`,
`suggest_healthier_swaps`, `create_diet_chart`, `update_user_profile`,
`get_user_profile`, `get_dish_history`.

## 5. The deterministic engine (the older core this is built on)

- **ETL** (`etl/`): parses IFCT 2017 PDF (pdfplumber) + USDA CSVs + curated
  files into a canonical per-100g schema of 10 nutrients → `ingredients.db`
  (1,012 ingredients) and `recipes.db` (1,014 dishes).
- **Engine** (`nourish/`): `parsing` (free text → items) → `resolver`
  (name → ingredient via exact/alias/fuzzy layers, ~90 Hinglish aliases) →
  `units` ((qty, unit) → grams, incl. Indian measures like katori) →
  `nutrition_engine` (scale + sum) → `swap_engine` (goal-driven substitutions
  from `swap_rules.yaml`, applied only if the recompute proves improvement).
- The agent exposes this engine as tools — so "compute this recipe's
  nutrition" and "make it diabetic-friendly" are exact, reproducible math.

## 6. The diet chart algorithm (deterministic, explainable)

1. Daily target = Mifflin-St Jeor BMR (gender/age/height/weight) × activity
   factor (1.2–1.725); −15% if overweight, +10% if underweight.
2. Meal budgets: breakfast 25%, lunch 35%, snack 10%, dinner 30%.
3. Candidate dishes filtered by: diet preference (regex on names), condition
   flags parsed from the user's own words (diabetes/BP/anemia/heart/kidney),
   and a "not a dish" filter (powders, premixes, chutneys).
4. Dishes scored with explainable weights (protein +, fibre +, sugar − for
   diabetics, sodium − for hypertension, iron + for anemia…), picked per meal
   with meal-type hints (idli/poha/paratha for breakfast…), no repeats.
5. The LLM only formats the result as a table and adds advice — it cannot
   change any number.

## 7. Files & scripts you should be able to name

| Command | What it does |
|---|---|
| `pip install -r requirements.txt` | install everything |
| `python -m etl.build_all` | build ingredients.db + recipes.db from raw data |
| `python -m nourish.agent.build_index` | build the Chroma vector index (2,311 docs) |
| `streamlit run app.py` | run the chat companion |
| `streamlit run recipe_lab.py` | run the original recipe-transformer UI |
| `python -m pytest -q` | run all 96 tests (offline) |
| `python -m nourish.agent.evaluate` | measure RAG quality against the golden set |

Keys live in `.env` (gitignored): `GROQ_API_KEY`, `TAVILY_API_KEY`,
`EMBEDDING_API_KEY`.

Data stores: `ingredients.db`, `recipes.db`, `history.db` (incl. the
food-journey table), `profile.db`, `checkpoints.db`, `chroma/`.

## 8. Design decisions (the "why" answers)

1. **LLM never touches numbers.** Nutrition mistakes can harm someone with
   diabetes. All numbers come from databases or the pure-Python engine; the
   LLM arranges words around them. This also makes the app testable.
2. **Hybrid RAG instead of vectors-only.** For a known dish name, fuzzy
   lookup over SQLite is *more* accurate than embeddings (exact rows, no
   approximation), instant and free. Vectors add value only for descriptive
   queries — so both exist and are tried in order.
3. **Deterministic web fallback.** Llama 3.3 wouldn't reliably call
   `web_search` even when instructed. Instead of fighting the prompt, the
   knowledge-base tool chains the web call itself when scores are weak.
   Lesson: **put control flow in code, not in the prompt, whenever you can.**
4. **Profile outside graph state.** Editable anytime without rewriting
   conversation history; single source of truth for every thread.
5. **`interrupt()` over a UI form.** The requirement was a *conversational*
   onboarding with follow-ups and validation — that's exactly what
   LangGraph's human-in-the-loop primitive models, and the checkpointer means
   a half-finished onboarding survives an app restart.
6. **SQLite everywhere.** Local-first, zero-ops, one file per concern.
7. **Answer parsing is lenient code, not LLM.** Height "5'8", "172 cm",
   "1.7 m" all parse with regex; gender/diet/activity keyword-matched with
   Hinglish support ("nahi" = no). Deterministic = testable.

## 9. Hard problems I actually solved (interview gold)

1. **Fuzzy matching Indian dish names.** The DB name for aloo paratha is
   *"Potato parantha/paratha (Aloo ka parantha/paratha)"*. Plain WRatio
   missed it. Fix: blend WRatio with token_set_ratio (−2 penalty) **and**
   RapidFuzz's `default_process` so `/` and `(` become token separators.
2. **The LLM leaking tool-call syntax.** Llama sometimes printed
   `<function=suggest_healthier_swaps>{…}</function>` as visible text.
   Fix: regex-strip that pattern in the agent node + prompt it to *ask*
   before making a healthier version.
3. **The "white box" UI bug.** Users on Streamlit's dark theme saw invisible
   white-on-cream text, and wrapping markdown in a raw HTML `<div>` made
   the bubble render empty (markdown closes an HTML block at the first blank
   line). Fix: pin light theme in `.streamlit/config.toml` and style
   Streamlit's own chat containers via CSS `:has()` selectors instead of
   wrapping content.
4. **79 MB embedding model wouldn't download** on a slow connection (Chroma's
   default local ONNX model, timeouts). Fix: switch embeddings to the
   HuggingFace Inference API (same MiniLM model, one env key), with the local
   model as automatic fallback.
5. **IFCT 2017 PDF tables** are nearly unparseable for minerals (columns
   shift). Solution: parse only the reliably-anchored proximates; curate
   mineral values from known sources instead of risking wrong iron numbers.
6. **Spice powders in meal plans.** The dish DB contains "Sambar powder" and
   premixes; the diet chart once served them as lunch. Fix: a "not a dish"
   exclusion filter.

## 10. The evaluation harness & the guardrail (built, not planned)

**RAG evaluation** (`python -m nourish.agent.evaluate`): a hand-verified
golden set (`eval/golden_set.yaml`) measures each cascade level — including
known-hard cases kept in on purpose so the score stays honest. Current
results (also in `eval/RESULTS.md`):

| Level | Metric | Score |
|---|---|---|
| Vector-less lookup | hit@1 over 24 dish queries | **92%** |
| Vector search | hit@4 over 10 descriptive queries | **40%** |
| Web fallback | fires when it should (8 out-of-corpus dishes) | **88%** |

The 40% is a real finding I can discuss: MiniLM embeddings over table-heavy
fact-sentences retrieve poorly for descriptive queries. The system stays
safe because level 1 answers the common case exactly and level 3 catches
what both miss; the improvement plan is re-ranking + table-aware chunking.

**Number guardrail** (`nourish/agent/guardrail.py`): after every answer, a
verifier extracts each data-like number from the LLM's text and checks it
existed in this turn's tool outputs (or the user's profile), tolerating
rounding and serving multiples while ignoring counting numbers like "step 3"
or "2 minutes". The UI shows 🛡️ *"n numbers verified against tool data"* —
or an explicit warning listing anything unverified. The golden rule is
enforced by code, not by trust.

## 11. Numbers to remember

- **1,014** Indian dishes (nutrition per serving) · **1,012** ingredients
  (per-100g, 10 nutrients) · **2,311** vector documents
- **11** agent tools · **9** onboarding questions (8 + conditional describe)
- **96** automated tests, all offline · **5** SQLite stores + 1 vector store
- RAG eval: **92%** lookup hit@1 · **40%** semantic hit@4 · **88%** fallback
- Model: **Llama 3.3 70B** on Groq · Embeddings: **MiniLM-L6-v2** (384-dim)

## 12. What I'd improve next (always have this ready)

- **Semantic retrieval quality**: the eval says 40% hit@4 — fix with a
  re-ranking step, table-aware chunking of the IFCT PDF, and richer dish
  descriptions in the index (the harness makes every change measurable).
- **Multi-user support**: profile keyed by user id, auth, Postgres instead of
  SQLite, thread-per-user checkpoints (LangGraph supports this natively).
- **Streaming token-by-token responses** in the UI.
- **Meal-plan variety**: multi-day charts with rotation, festivals, budgets.
