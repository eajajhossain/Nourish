"""The Nourish agent graph.

           ┌─ profile incomplete ─▶ onboarding ─▶ END (welcome message)
  START ───┤                        (interrupt() per question — true
           │                         human-in-the-loop; answers are
           │                         parsed and saved to profile.db)
           └─ profile complete ───▶ agent ◀──▶ tools ─▶ ... ─▶ END

The agent node is a Groq LLM with the tool belt from tools.py; the system
prompt injects the live profile and pins the retrieval order (local DB →
vector store → web). Conversation state is checkpointed to SQLite
(data/processed/checkpoints.db), so a thread survives app restarts — the
"memory saver" — while the profile itself lives outside the graph and can be
edited any time.
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from ..schema import PROCESSED
from . import config
from . import profile as prof
from .tools import ALL_TOOLS

CHECKPOINT_DB = PROCESSED / "checkpoints.db"


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------- onboarding
def _ask(question: str, parser, error_hint: str):
    """interrupt() until the answer parses. Deterministic across resumes."""
    answer = interrupt(question)
    parsed = parser(str(answer))
    while parsed is None:
        answer = interrupt(f"{error_hint}\n\n{question}")
        parsed = parser(str(answer))
    return parsed


def onboarding_node(state: ChatState) -> dict:
    name = _ask("Namaste! I'm **Nourish**, your Indian food & nutrition "
                "companion. Before we talk food, let me know you a little.\n\n"
                "**What should I call you?**",
                lambda t: t.strip()[:60] or None, "A name helps me help you!")
    gender = _ask(f"Lovely to meet you, {name}! **Are you male or female?**",
                  prof.parse_gender,
                  "Sorry, I didn't catch that — just say male, female or other.")
    age = _ask("**How old are you?**", prof.parse_age,
               "Please give me your age in years, like 24.")
    height = _ask("**What's your height?** (e.g. 170 cm or 5'7\")",
                  prof.parse_height_cm,
                  "Hmm, that doesn't look like a height I can read — try "
                  "something like `172 cm` or `5'8`.")
    weight = _ask("**And your current weight?** (e.g. 68 kg)",
                  prof.parse_weight_kg,
                  "I need a number I can work with — like `65 kg` or `140 lbs`.")
    activity = prof.parse_activity(str(interrupt(
        "**How active is a normal day for you?** (mostly sitting / light "
        "walking / regular exercise / very active)")))
    diet = prof.parse_diet(str(interrupt(
        "**How do you eat — vegetarian, eggetarian, or non-vegetarian?**")))

    cond_raw = str(interrupt(
        "Last one, and it matters most: **do you have any diagnosed "
        "condition or physical problem?** Diabetes, blood pressure, thyroid, "
        "an injury, anything at all — or just say *no*.")).strip()
    conditions, details = "", ""
    if not prof.is_negative(cond_raw):
        conditions = cond_raw
        details = str(interrupt(
            "Thank you for trusting me with that. **Please describe it a "
            "little** — since when, any medicines, what the doctor advised. "
            "The more I know, the safer my suggestions.")).strip()

    prof.save(name=name, gender=gender, age=age, height_cm=height,
              weight_kg=weight, activity=activity, diet_pref=diet,
              conditions=conditions, condition_details=details)

    p = prof.get()
    b = prof.bmi(p)
    kcal = prof.daily_calories(p)
    cond_line = (f"I've noted **{conditions}** and will keep every "
                 "suggestion gentle on it." if conditions else
                 "No health conditions noted — we'll focus on keeping it "
                 "that way!")
    welcome = (
        f"All set, {name}! 🎉 Here's what I understood:\n\n"
        f"- **BMI {b}** ({prof.bmi_band(b)}) · target around **{kcal} "
        f"kcal/day** for your {p['activity']} routine\n"
        f"- Food style: **{diet}**\n- {cond_line}\n\n"
        "Now, the fun part — **name any Indian dish** (aloo paratha, dal "
        "makhani, chicken chettinad...) and I'll tell you how to make it, "
        "how much to eat, and how to tweak it for *you*. You can also ask me "
        "for a **diet chart**, or update your details anytime by just "
        "telling me."
    )
    return {"messages": [AIMessage(content=welcome)]}


# ---------------------------------------------------------------- agent
def _system_prompt() -> str:
    p = prof.get() or {}
    from . import agent_history
    recent = agent_history.friendly_lines(8)
    history_block = "\n".join(f"  - {line}" for line in recent) or "  (nothing yet)"
    return f"""You are Nourish, a warm, knowledgeable Indian food and nutrition companion. \
You speak simply and kindly, in the friendly tone of a family dietician who loves Indian food.

USER PROFILE (already collected — personalise EVERYTHING with it):
{prof.summary(p) if p else 'no profile yet'}

DISHES THE USER ASKED ABOUT RECENTLY (their food journey — use it warmly;
note: the newest entry is usually the dish they are asking about RIGHT NOW,
so never call that one "recent" — only connect to the older ones):
{history_block}

HOW TO ANSWER A DISH QUESTION (e.g. "aloo paratha"):
1. ALWAYS call lookup_dish_database first — it has exact per-serving nutrition for 1,014 Indian dishes and ingredient lists for curated recipes.
2. If it misses or you need descriptive/comparative knowledge, call search_knowledge_base (local IFCT 2017 tables + dish facts).
3. If the database has no confident match AND the knowledge-base results are weak, you MUST call web_search before answering — never answer a dish question purely from your own memory.

GROUNDING THE RECIPE ITSELF: if lookup_dish_database returned no ingredient
list for the dish, call get_recipe_from_web so quantities and steps come from
a real recipe, not your memory. Also call get_dish_story_from_web once per
dish for the story section.

FORMAT of a dish answer (use these exact sections, in markdown):
- One warm opening line. As a friendly bonus, if their recent dishes make a nice connection, mention it naturally ("You asked about dal makhani yesterday — this pairs beautifully!"). Never force it.
- **📜 A little story** — 3-4 warm lines on the dish's history from get_dish_story_from_web: where it comes from, who created it or where it became famous, one fun fact. If sources disagree, say "legend has it". Never invent names/dates.
- **🧺 What you need** — the full ingredient list with exact quantities (from the curated recipe or the web source; say how many servings it makes).
- **👩‍🍳 Step by step** — numbered steps a complete beginner can follow. Each step = ONE short action, with helpful cues for doneness and timing ("knead until soft like your earlobe, ~5 min", "roast until golden brown spots appear, ~2 min per side"). Include small tricks that stop common failures (dough resting, flame level, oil temperature). 8-14 steps is ideal.
- **🍽️ How much for YOU** — the exact portion for THIS user, tied to their calorie target and conditions, in everyday measures (1 paratha, 1 katori dal).
- **📊 Nutrition per serving** — a small markdown table using ONLY the tool numbers. Never invent a number; if a value came from the web, say "approx. (web)".
- **💚 Nourish tips** — 2-3 personalised pointers for their profile (diabetic → less sugar/jaggery and more fibre; hypertension → easy on salt). End by ASKING in plain words whether they'd like a healthier version — do NOT call suggest_healthier_swaps until they say yes, and never write tool syntax in your answer text.

RULES:
- Never invent nutrition numbers. Numbers come only from tool results; repeat them exactly.
- When the user mentions a change (weight, new diagnosis, diet change) call update_user_profile immediately, then acknowledge it warmly.
- When asked for a diet chart / meal plan, call create_diet_chart and present the result as a tidy markdown table per meal, with the day total, plus 2-3 lines of personal advice. Remind them it's a suggestion, not a prescription.
- When asked what they searched/ate before, use get_dish_history.
- You may answer general cooking chit-chat directly, but any FACTUAL nutrition claim must be grounded in a tool result.
- Keep answers warm but compact: headings, short lists, no walls of text. A little Hindi/food warmth (ghar ka khana, dal-chawal) is welcome; don't overdo it.
- You are not a doctor: for serious medical questions, gently advise consulting one."""


@lru_cache(maxsize=1)
def _llm():
    from langchain_groq import ChatGroq
    return ChatGroq(model=config.MODEL, api_key=config.GROQ_API_KEY,
                    temperature=0.4).bind_tools(ALL_TOOLS)


def agent_node(state: ChatState) -> dict:
    msgs = [SystemMessage(content=_system_prompt())] + state["messages"]
    reply = _llm().invoke(msgs)
    if isinstance(reply.content, str) and "<function=" in reply.content:
        # llama sometimes writes a malformed inline tool call as text
        # instead of a real tool call — never show that to the user
        reply.content = re.sub(r"<function=.*?(</function>|$)", "",
                               reply.content, flags=re.S).rstrip()
    return {"messages": [reply]}


def route_entry(state: ChatState) -> str:
    return "agent" if prof.is_complete(prof.get()) else "onboarding"


def route_after_agent(state: ChatState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


# ---------------------------------------------------------------- build
def build_graph(checkpointer=None):
    g = StateGraph(ChatState)
    g.add_node("onboarding", onboarding_node)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.add_conditional_edges(START, route_entry,
                            {"onboarding": "onboarding", "agent": "agent"})
    g.add_edge("onboarding", END)
    g.add_conditional_edges("agent", route_after_agent,
                            {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def get_app():
    """The app with persistent SQLite checkpointing (the memory saver)."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return build_graph(SqliteSaver(conn))
