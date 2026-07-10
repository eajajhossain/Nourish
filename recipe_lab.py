"""Nourish — Streamlit UI.

Pick or paste an Indian recipe and see several healthier variations side by
side (protein, iron, calcium, fibre, diabetic-friendly), each with a clear
before/after, grounded tips, and India-available swaps. All numbers come from
the deterministic engine.

Run:  streamlit run app.py
"""
from __future__ import annotations

import random

import pandas as pd
import streamlit as st

from nourish import content, history, pipeline, recipes
from nourish.content import DEFICIENCY_NOTES
from nourish.schema import NUTRIENT_COLUMNS
from nourish.swap_engine import DEFAULT_VARIANT_GOALS, GOALS

GOAL_LABELS = {
    "higher_protein": "💪 Higher protein",
    "iron_boost": "🩸 Iron boost",
    "calcium_boost": "🦴 Calcium boost",
    "higher_fibre": "🌾 Higher fibre",
    "diabetic_friendly": "🩺 Diabetic friendly",
    "lower_calorie": "⚖️ Lower calorie",
    "lower_sugar": "🍬 Lower sugar",
    "lower_sodium": "🧂 Lower sodium",
    "lower_fat": "🫗 Lower fat",
}
LABEL_TO_GOAL = {v: k for k, v in GOAL_LABELS.items()}
# headline nutrient per goal, for the big metric on each card
GOAL_PRIMARY = {
    "higher_protein": "protein_g", "iron_boost": "iron_mg",
    "calcium_boost": "calcium_mg", "higher_fibre": "fibre_g",
    "diabetic_friendly": "sugar_g", "lower_calorie": "kcal",
    "lower_sugar": "sugar_g", "lower_sodium": "sodium_mg", "lower_fat": "fat_g",
}

st.set_page_config(page_title="Nourish", page_icon="🥗", layout="wide")

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
:root { --ink:#2b2118; --saff:#e8743b; --green:#2e7d54; --cream:#fbf6ee; }
.stApp { background: linear-gradient(180deg,#fbf6ee 0%,#f4ece0 100%); }
.hero { padding: 8px 0 2px; }
.hero h1 { font-size: 2.5rem; margin-bottom:0; color:var(--ink); letter-spacing:-1px; }
.hero .tag { color:var(--saff); font-weight:600; font-size:1.05rem; }
.hero .intro { color:#5c5347; max-width:760px; font-size:0.95rem; line-height:1.5; }
.card { background:#fff; border:1px solid #ecdfce; border-radius:16px;
        padding:18px 20px; box-shadow:0 2px 10px rgba(120,90,40,.06); }
.factcard { background:#fff7ee; border:1px solid #f1d9bf; border-left:5px solid var(--saff);
            border-radius:12px; padding:14px 18px; color:#5a4a36; }
.swap { background:#f4faf6; border-left:4px solid var(--green); border-radius:8px;
        padding:6px 12px; margin:5px 0; font-size:0.92rem; }
.note { color:#7a6d5c; font-size:0.88rem; font-style:italic; }
div[data-testid="stMetricValue"] { font-size:1.4rem; }
.stTabs [data-baseweb="tab"] { font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def nutrition_df(before: dict, after: dict) -> pd.DataFrame:
    rows = []
    for key, (label, unit) in NUTRIENT_COLUMNS.items():
        b, a = before.get(key, 0), after.get(key, 0)
        rows.append({"Nutrient": f"{label} ({unit})",
                     "Before": round(b, 1), "After": round(a, 1),
                     "Change": round(a - b, 1)})
    return pd.DataFrame(rows)


def render_variant(t, insights, goal):
    note = DEFICIENCY_NOTES.get(goal)
    if note:
        st.markdown(f"<div class='note'>{note}</div>", unsafe_allow_html=True)

    # headline metrics: primary nutrient + calories
    primary = GOAL_PRIMARY.get(goal, "kcal")
    keys = [primary] + [k for k in ("kcal", "protein_g", "fibre_g") if k != primary][:2]
    cols = st.columns(len(keys))
    for col, k in zip(cols, keys):
        label, unit = NUTRIENT_COLUMNS[k]
        b, a = t.before.totals.get(k, 0), t.after.totals.get(k, 0)
        lower_better = k in ("kcal", "sugar_g", "sodium_mg", "fat_g")
        col.metric(f"{label} ({unit})", round(a, 1), round(a - b, 1),
                   delta_color="inverse" if lower_better else "normal")

    st.markdown("**Swaps**")
    if t.swaps:
        for s in t.swaps:
            if s.is_addition:
                label = f"Add <b>{s.replacement_name}</b>"
            elif s.is_reduction:
                label = f"Use less <b>{s.original_name}</b>"
            else:
                label = f"<b>{s.original_name}</b> → <b>{s.replacement_name}</b>"
            st.markdown(f"<div class='swap'>{label} — {s.reason}</div>",
                        unsafe_allow_html=True)
    else:
        st.caption("No swaps needed for this goal.")

    with st.expander("Full before → after & tips"):
        st.dataframe(nutrition_df(t.before.totals, t.after.totals),
                     hide_index=True, width='stretch')
        for tip in insights:
            st.markdown(f"- {tip}")
    for n in t.notes:
        st.caption(f"⚠️ {n}")


def did_you_know():
    idx = st.session_state.setdefault("fact_idx", random.randrange(len(content.FOOD_HISTORY)))
    st.markdown(f"<div class='factcard'><b>Did you know?</b> {content.fact(idx)}</div>",
                unsafe_allow_html=True)
    if st.button("Another food-history fact ↻"):
        st.session_state["fact_idx"] = (idx + 1) % len(content.FOOD_HISTORY)
        st.rerun()


# ---------------------------------------------------------------- header
st.markdown(f"""
<div class='hero'>
  <h1>🥗 Nourish</h1>
  <div class='tag'>{content.TAGLINE}</div>
  <p class='intro'>{content.INTRO}</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("🕘 Your history")
    for h in history.list_recent(20):
        title = h["dish"] or "(untitled)"
        if st.button(f"{title} · {GOAL_LABELS.get(h['goal'], h['goal'])}",
                     key=f"hist_{h['id']}", width='stretch'):
            st.session_state["view_history"] = h["id"]
        st.caption(h["ts"].replace("T", " "))
    if not history.list_recent(1):
        st.caption("No transformations yet.")

# view a past entry
if "view_history" in st.session_state:
    h = history.get(st.session_state["view_history"])
    if h:
        st.subheader(f"History · {h['dish'] or '(untitled)'} — "
                     f"{GOAL_LABELS.get(h['goal'], h['goal'])}")
        st.dataframe(nutrition_df(h["before"], h["after"]),
                     hide_index=True, width='stretch')
        if h["swaps"]:
            def _fmt_swap(s):
                if s.get("addition"):
                    return f"add {s['replacement']}"
                if s["reduction"]:
                    return f"less {s['original']}"
                return f"{s['original']} → {s['replacement']}"
            st.markdown("**Swaps:** " + "; ".join(_fmt_swap(s) for s in h["swaps"]))
        for tip in h["insights"]:
            st.markdown(f"- {tip}")
    if st.button("← Back"):
        del st.session_state["view_history"]
    st.stop()

# ---------------------------------------------------------------- input
st.markdown("### 1 · Choose a recipe")
tab_pick, tab_paste = st.tabs(["📖 Pick a recipe", "✍️ Paste your own"])
with tab_pick:
    choice = st.selectbox("Indian recipes", recipes.names())
    sel = recipes.get(choice)
    picked_text = sel.as_text() if sel else ""
    st.code(picked_text, language=None)
with tab_paste:
    pasted_text = st.text_area("One ingredient per line",
                               placeholder="2 cups rice\n1 cup toor dal\n2 tbsp ghee\nsalt to taste",
                               height=180)

st.markdown("### 2 · How should we make it healthier?")
c1, c2 = st.columns([2, 1])
with c1:
    mode = st.radio("Mode", ["✨ Show me healthier variations (recommended)",
                             "🎯 One specific goal"], label_visibility="collapsed")
with c2:
    dish = st.text_input("Dish name", value=choice)

specific_goal = None
if mode.startswith("🎯"):
    specific_goal = LABEL_TO_GOAL[st.selectbox("Goal",
                                  [GOAL_LABELS[g] for g in GOALS])]

source = pasted_text if (pasted_text and pasted_text.strip()) else picked_text
go = st.button("Transform 🔄", type="primary", width='stretch')

# ---------------------------------------------------------------- run
if go:
    if not source.strip():
        st.warning("Pick a recipe or paste one first.")
        st.stop()

    if specific_goal:
        res = pipeline.transform_recipe(source, specific_goal, dish=dish or None)
        history.save(res, dish=dish or None)
        st.markdown("### Result")
        render_variant(res.transformation, res.insights, specific_goal)
    else:
        vr = pipeline.make_variants(source)
        st.markdown("### Healthier variations")
        b = vr.baseline.totals
        st.caption(f"Your recipe today: **{round(b['kcal'])} kcal** · "
                   f"{round(b['protein_g'],1)}g protein · {round(b['iron_mg'],1)}mg iron · "
                   f"{round(b['calcium_mg'])}mg calcium · {round(b['fibre_g'],1)}g fibre")
        if not vr.variants:
            st.info("This recipe is already well-balanced — no strong swaps found.")
        else:
            tabs = st.tabs([GOAL_LABELS.get(v.goal, v.goal) for v in vr.variants])
            for tab, v in zip(tabs, vr.variants):
                with tab:
                    render_variant(v.transformation, v.insights, v.goal)
                    history.save_transformation(v.transformation, v.insights,
                                                dish=dish or None)

    # resolution confidence (shared)
    st.markdown("---")
    with st.expander("How we matched your ingredients"):
        target = (res.resolution if specific_goal else vr.resolution)
        for q, m, score, ok in target:
            if m is None:
                st.markdown(f"- ❌ **{q}** — not found")
            elif ok:
                st.markdown(f"- ✅ {q} → {m}")
            else:
                st.markdown(f"- ⚠️ {q} → {m} _(low confidence {score})_")

# ---------------------------------------------------------------- footer
st.markdown("---")
did_you_know()
st.caption("Nourish celebrates that Indian food has always evolved — these are "
           "gentle, optional tweaks, not a verdict on tradition.")
