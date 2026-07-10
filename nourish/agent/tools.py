"""The tools the agent can call.

Retrieval order is enforced by the system prompt in graph.py:
  1. lookup_dish_database   (vector-less RAG — exact, structured, free)
  2. search_knowledge_base  (traditional RAG — Chroma over dishes + IFCT PDF)
  3. web_search             (Tavily — only when local knowledge has no answer)

Every number a tool returns comes from the deterministic engine or the
databases; the LLM only arranges them into an answer.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from .. import pipeline
from ..swap_engine import GOALS
from . import agent_history, config, dietchart, vectorless, vectorstore
from . import profile as prof


@tool
def lookup_dish_database(dish_name: str) -> str:
    """FIRST CHOICE for any Indian dish question. Looks the dish up in the
    local database of 1,014 Indian dishes (exact nutrition per serving) and
    the curated recipe library (ingredient lists). Input: the dish name only,
    e.g. 'aloo paratha'."""
    hits = vectorless.find_dish(dish_name, limit=4)
    agent_history.log_dish(dish_name.strip().title())
    if not hits:
        return json.dumps({"found": False,
                           "hint": "Not in the local database — try "
                                   "search_knowledge_base, then web_search."})
    return json.dumps({"found": True,
                       "confident": hits[0]["score"] >= vectorless.CONFIDENT,
                       "matches": hits}, ensure_ascii=False)


def _tavily(query: str, max_results: int = 4, chars: int = 600,
            depth: str = "basic") -> list[dict] | str:
    """Shared Tavily call. Returns result list, or an error string."""
    if not config.web_ready():
        return "TAVILY_API_KEY not set — web search unavailable."
    try:
        from tavily import TavilyClient
        res = TavilyClient(api_key=config.TAVILY_API_KEY).search(
            query, max_results=max_results, search_depth=depth)
        return [{"title": r.get("title"), "url": r.get("url"),
                 "content": (r.get("content") or "")[:chars]}
                for r in res.get("results", [])]
    except Exception as e:  # network/key errors surface to the model
        return f"web search failed: {e}"


@tool
def search_knowledge_base(query: str) -> str:
    """Semantic search over the local knowledge base (dish nutrition facts,
    curated recipes, and the IFCT 2017 Indian Food Composition Tables).
    Use for descriptive or comparative questions ('high-iron breakfast',
    'which dal is best for protein') or when lookup_dish_database misses.
    If local matches are weak it automatically falls through to a web search
    and returns those results too."""
    hits = vectorstore.search(query, k=4)
    payload: dict = {"found": bool(hits), "results": hits}
    # the LLM can't be trusted to escalate on its own — when local knowledge
    # is weak, chain the web fallback here so the cascade is deterministic
    if not hits or hits[0]["score"] < 0.2:
        payload["note"] = ("local matches were weak, so the web fallback "
                           "below was used — cite it, and say the numbers "
                           "are approximate (from the web, not our database).")
        payload["web_results"] = _tavily(query)
    return json.dumps(payload, ensure_ascii=False)


@tool
def web_search(query: str) -> str:
    """LAST RESORT: search the web with Tavily. Use ONLY when the local
    database and knowledge base could not answer (rare dish, cooking steps
    for an uncommon recipe, recent information)."""
    res = _tavily(query)
    if isinstance(res, str):
        return json.dumps({"error": res})
    return json.dumps({"results": res}, ensure_ascii=False)


@tool
def get_recipe_from_web(dish_name: str) -> str:
    """Fetch a RELIABLE recipe from trusted web sources: ingredient list with
    quantities and the cooking steps. Use whenever the curated library gave
    no ingredient list for the dish, so your 'what you need' and 'step by
    step' sections are grounded in a real recipe — never cook from memory."""
    res = _tavily(f"authentic {dish_name} recipe ingredients with quantities "
                  f"step by step instructions", max_results=3, chars=1600,
                  depth="advanced")
    if isinstance(res, str):
        return json.dumps({"error": res})
    return json.dumps({
        "sources": res,
        "note": "Base the ingredient quantities and steps on these sources; "
                "mention the source site name once."}, ensure_ascii=False)


@tool
def get_dish_story_from_web(dish_name: str) -> str:
    """The dish's history and culture from the web: where it comes from, who
    created it, how it became famous, interesting trivia. Call this once for
    every dish question to write the story section with reliable facts."""
    res = _tavily(f"{dish_name} dish history origin story who invented "
                  f"why famous", max_results=3, chars=900)
    if isinstance(res, str):
        return json.dumps({"error": res})
    return json.dumps({
        "sources": res,
        "note": "Summarise into 3-4 warm lines. If sources disagree, say "
                "'legend has it'. Never invent names or dates."},
        ensure_ascii=False)


@tool
def compute_recipe_nutrition(recipe_text: str) -> str:
    """Compute exact nutrition totals for a recipe using the deterministic
    engine. Input: one ingredient per line with quantity and unit, e.g.
    '2 cups wheat flour\\n2 tbsp ghee\\n1 cup milk'."""
    from .. import nutrition_engine, parsing
    parsed = parsing.parse_recipe(recipe_text)
    _rows, resolution, items = pipeline._resolve_rows(parsed)
    totals = nutrition_engine.compute(items).totals
    return json.dumps({
        "totals_for_whole_recipe": {k: round(v, 1) for k, v in totals.items()},
        "ingredient_matching": [
            {"asked": q, "matched": m, "confidence": s}
            for q, m, s, ok in resolution],
    }, ensure_ascii=False)


@tool
def suggest_healthier_swaps(recipe_text: str, goal: str) -> str:
    """Transform a recipe toward a health goal with exact before/after
    numbers. goal must be one of: higher_protein, iron_boost, calcium_boost,
    higher_fibre, diabetic_friendly, lower_calorie, lower_sugar,
    lower_sodium, lower_fat. recipe_text: one ingredient per line."""
    if goal not in GOALS:
        return json.dumps({"error": f"goal must be one of {sorted(GOALS)}"})
    res = pipeline.transform_recipe(recipe_text, goal)
    t = res.transformation
    return json.dumps({
        "goal": goal,
        "before": {k: round(v, 1) for k, v in t.before.totals.items()},
        "after": {k: round(v, 1) for k, v in t.after.totals.items()},
        "swaps": [{"change": (f"add {s.replacement_name}" if s.is_addition
                              else f"less {s.original_name}" if s.is_reduction
                              else f"{s.original_name} -> {s.replacement_name}"),
                   "reason": s.reason} for s in t.swaps],
        "tips": res.insights,
    }, ensure_ascii=False)


@tool
def create_diet_chart() -> str:
    """Build a personalised one-day diet chart for the user from their saved
    profile (calorie target, conditions, veg/non-veg) using real dishes from
    the database. Present the result as a clear meal-by-meal chart."""
    p = prof.get()
    if not prof.is_complete(p):
        return json.dumps({"error": "profile incomplete — ask the user to "
                                    "finish onboarding first."})
    return json.dumps(dietchart.build_chart(p), ensure_ascii=False)


@tool
def update_user_profile(field: str, value: str) -> str:
    """Update one field of the user's health profile when they mention a
    change (new weight, new diagnosis, diet change...). field must be one of:
    name, gender, age, height_cm, weight_kg, activity, diet_pref, conditions,
    condition_details. Height in cm, weight in kg."""
    if field not in prof.FIELDS:
        return json.dumps({"error": f"field must be one of {prof.FIELDS}"})
    parsed: object = value
    if field == "age":
        parsed = prof.parse_age(value)
    elif field == "height_cm":
        parsed = prof.parse_height_cm(value)
    elif field == "weight_kg":
        parsed = prof.parse_weight_kg(value)
    elif field == "gender":
        parsed = prof.parse_gender(value) or value
    if parsed is None:
        return json.dumps({"error": f"could not understand {value!r} for "
                                    f"{field} — ask the user to rephrase."})
    p = prof.update_fields({field: parsed})
    return json.dumps({"ok": True, "profile_now": prof.summary(p)},
                      ensure_ascii=False)


@tool
def get_user_profile() -> str:
    """Read the user's current saved health profile (measurements, BMI,
    calorie target, conditions). Use before personalising any advice if the
    profile is not already in context."""
    p = prof.get()
    if not p:
        return json.dumps({"error": "no profile saved yet"})
    return json.dumps({"summary": prof.summary(p)}, ensure_ascii=False)


@tool
def get_dish_history() -> str:
    """List the dishes the user has asked about recently, most recent first,
    with friendly timestamps. Use when the user asks what they searched or
    ate before."""
    lines = agent_history.friendly_lines()
    return json.dumps({"recent_dishes": lines or ["nothing yet"]},
                      ensure_ascii=False)


ALL_TOOLS = [lookup_dish_database, search_knowledge_base, web_search,
             get_recipe_from_web, get_dish_story_from_web,
             compute_recipe_nutrition, suggest_healthier_swaps,
             create_diet_chart, update_user_profile, get_user_profile,
             get_dish_history]
