"""Nourish — conversational nutrition companion (Streamlit UI).

Chat front-end over the LangGraph agent in nourish/agent/graph.py:
onboarding questions arrive as chat (LangGraph interrupts), then the agent
answers dish questions grounded in the local databases, with Tavily as the
web fallback. Profile and dish history live in the sidebar.

Run:  streamlit run app.py
(The original recipe-transformer UI still exists:  streamlit run recipe_lab.py)
"""
from __future__ import annotations

import uuid

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from nourish.agent import agent_history, config, guardrail, safety, vectorstore
from nourish.agent import profile as prof
from nourish.agent.graph import get_app

st.set_page_config(page_title="Nourish", page_icon="🌿", layout="centered",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,680&family=Inter:wght@400;500;600&display=swap');

:root { --ink:#2b2118; --saff:#d96c2f; --green:#2e7d54; --paper:#faf5ec; }
.stApp { background:
  radial-gradient(1200px 500px at 80% -10%, #f3e3cd 0%, transparent 60%),
  linear-gradient(180deg, #faf5ec 0%, #f4ecdf 100%); }
html, body, [class*="css"] { font-family:'Inter',sans-serif; color:var(--ink); }

.n-hero { margin: .2rem 0 1.1rem; }
.n-hero h1 { font-family:'Fraunces',serif; font-weight:680; font-size:2.6rem;
  letter-spacing:-.5px; margin:0; color:var(--ink); }
.n-hero h1 em { font-style:normal; color:var(--saff); }
.n-hero p { color:#6b5d4b; margin:.25rem 0 0; font-size:.98rem; }

/* chat bubbles — style the st.chat_message containers themselves so the
   markdown inside renders normally (never wrap markdown in raw HTML) */
div[data-testid="stChatMessage"] { padding:.85rem 1.05rem; margin:.3rem 0; }
div[data-testid="stChatMessage"] p,
div[data-testid="stChatMessage"] li { font-size:.97rem; line-height:1.55;
  color:var(--ink) !important; }
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
  background:#fffdf8; border:1px solid #eadfca;
  border-radius:4px 18px 18px 18px;
  box-shadow:0 2px 10px rgba(120,90,40,.05); }
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
  background:linear-gradient(135deg,#fdeedd,#fbe3c8);
  border:1px solid #f0d4ac; border-radius:18px 4px 18px 18px; }

section[data-testid="stSidebar"] { background:#f2ead9; border-right:1px solid #e6d8bf; }
section[data-testid="stSidebar"] .stMarkdown h3 { font-family:'Fraunces',serif; }

.n-card { background:#fffdf8; border:1px solid #e8dcc4; border-radius:14px;
  padding: .9rem 1rem; margin-bottom:.6rem; }
.n-card .who { font-family:'Fraunces',serif; font-size:1.25rem; font-weight:650; }
.n-chip { display:inline-block; background:#f6eddc; border:1px solid #e5d4b2;
  border-radius:999px; padding:.1rem .6rem; margin:.12rem .18rem .12rem 0;
  font-size:.78rem; color:#6b5535; }
.n-bmi { display:inline-block; border-radius:999px; padding:.12rem .65rem;
  font-size:.8rem; font-weight:600; color:#fff; }
section[data-testid="stSidebar"] .stButton button {
  text-align:left; justify-content:flex-start; background:#fffdf8;
  border:1px solid #e8dcc4; color:#5d4f3c; font-size:.85rem;
  border-radius:10px; }
section[data-testid="stSidebar"] .stButton button:hover {
  border-color:var(--saff); color:var(--saff); }
footer, #MainMenu { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

BMI_COLORS = {"underweight": "#7a94c9", "healthy": "#2e7d54",
              "overweight": "#d9932f", "obese": "#c25438"}
TOOL_LABELS = {
    "lookup_dish_database": "Looking through my dish book…",
    "search_knowledge_base": "Reading the Indian food tables…",
    "web_search": "Asking the web (not in my books)…",
    "get_recipe_from_web": "Fetching a trusted recipe…",
    "get_dish_story_from_web": "Digging up this dish's story…",
    "compute_recipe_nutrition": "Weighing every ingredient…",
    "suggest_healthier_swaps": "Finding healthier swaps…",
    "create_diet_chart": "Planning your plate for the day…",
    "update_user_profile": "Updating your details…",
    "get_user_profile": "Checking your profile…",
    "get_dish_history": "Flipping back through your dishes…",
}

# ---------------------------------------------------------------- state
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.transcript = []       # [{"role","text"}] for display
    st.session_state.pending_interrupt = False
    st.session_state.booted = False

graph = get_app()
CFG = {"configurable": {"thread_id": st.session_state.thread_id}}


def rebuild_from_checkpoint() -> None:
    """After a restart, restore the visible transcript from the checkpoint."""
    snap = graph.get_state(CFG)
    transcript = []
    for m in snap.values.get("messages", []):
        if isinstance(m, HumanMessage) and m.content:
            transcript.append({"role": "user", "text": m.content})
        elif isinstance(m, AIMessage) and m.content and not m.tool_calls:
            transcript.append({"role": "assistant", "text": m.content})
    for task in snap.tasks:
        for intr in getattr(task, "interrupts", ()):
            transcript.append({"role": "assistant", "text": str(intr.value)})
            st.session_state.pending_interrupt = True
    st.session_state.transcript = transcript


def run_graph(payload) -> None:
    """Stream the graph, narrating tool use, then append the outcome."""
    st.session_state.pending_interrupt = False
    label_box = st.status("Thinking…", expanded=False)
    interrupted_q = None
    try:
        for chunk in graph.stream(payload, CFG, stream_mode="updates"):
            if "__interrupt__" in chunk:
                interrupted_q = str(chunk["__interrupt__"][0].value)
                continue
            for node, update in chunk.items():
                if node == "agent":
                    msg = update["messages"][-1]
                    for tc in getattr(msg, "tool_calls", None) or []:
                        label_box.update(label=TOOL_LABELS.get(
                            tc["name"], "Working on it…"))
        label_box.update(label="Done", state="complete")
    except Exception as e:
        label_box.update(label="Something went wrong", state="error")
        st.session_state.transcript.append({
            "role": "assistant",
            "text": f"Sorry, I hit a snag: `{e}`. If this mentions an API "
                    "key, check the `.env` file."})
        return

    if interrupted_q is not None:
        st.session_state.pending_interrupt = True
        st.session_state.transcript.append({"role": "assistant",
                                            "text": interrupted_q})
    else:
        snap = graph.get_state(CFG)
        msgs = snap.values.get("messages", [])
        if msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].content:
            entry = {"role": "assistant", "text": msgs[-1].content}
            # guardrail: every data-like number in the answer must exist in
            # this turn's tool outputs (or the profile) — enforced, not hoped
            p = prof.get()
            sources = []
            # profile-DERIVED numbers (BMI, kcal target) are grounded too: the
            # model sees them via profile.summary() in its system prompt, so
            # repeating "~2300 kcal/day" is legitimate, not invented
            if p:
                sources.append(prof.summary(p))
            for m in reversed(msgs[:-1]):
                if isinstance(m, HumanMessage):
                    break
                if isinstance(m, ToolMessage):
                    sources.append(str(m.content))
            if sources:
                v = guardrail.verify_answer(msgs[-1].content, sources, p)
                if v.checked:
                    entry["verify"] = {"ok": v.ok, "checked": v.checked,
                                       "unverified": v.unverified}
            st.session_state.transcript.append(entry)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    p = prof.get()
    if p and prof.is_complete(p):
        b = prof.bmi(p)
        band = prof.bmi_band(b) if b else ""
        kcal = prof.daily_calories(p)
        cond = p.get("conditions") or "none reported"
        st.markdown(f"""
        <div class='n-card'>
          <div class='who'>🌿 {p.get('name') or 'You'}</div>
          <div style='margin:.35rem 0 .45rem'>
            <span class='n-bmi' style='background:{BMI_COLORS.get(band, "#888")}'>BMI {b} · {band}</span>
          </div>
          <span class='n-chip'>{p.get('gender','?')}, {p.get('age','?')}</span>
          <span class='n-chip'>{p.get('height_cm', 0):g} cm</span>
          <span class='n-chip'>{p.get('weight_kg', 0):g} kg</span>
          <span class='n-chip'>~{kcal} kcal/day</span>
          <span class='n-chip'>{p.get('diet_pref','')}</span>
          <div style='margin-top:.5rem;font-size:.84rem;color:#6b5535'>
            <b>Health notes:</b> {cond}</div>
        </div>""", unsafe_allow_html=True)

        with st.expander("✏️ Update my details"):
            with st.form("edit_profile", border=False):
                new_w = st.text_input("Weight (kg)", value=str(p.get("weight_kg") or ""))
                new_h = st.text_input("Height (cm)", value=str(p.get("height_cm") or ""))
                new_age = st.text_input("Age", value=str(p.get("age") or ""))
                new_act = st.selectbox("Activity", ["sedentary", "light",
                                       "moderate", "active"],
                                       index=["sedentary", "light", "moderate",
                                              "active"].index(p.get("activity") or "light"))
                new_diet = st.selectbox("Diet", ["vegetarian", "eggetarian",
                                        "non-vegetarian", "vegan"],
                                        index=["vegetarian", "eggetarian",
                                               "non-vegetarian", "vegan"].index(
                                               p.get("diet_pref") or "vegetarian"))
                new_cond = st.text_area("Health conditions",
                                        value=p.get("conditions") or "",
                                        height=68)
                new_det = st.text_area("Details (medicines, doctor's advice…)",
                                       value=p.get("condition_details") or "",
                                       height=68)
                if st.form_submit_button("Save", use_container_width=True):
                    prof.update_fields({
                        "weight_kg": prof.parse_weight_kg(new_w),
                        "height_cm": prof.parse_height_cm(new_h),
                        "age": prof.parse_age(new_age),
                        "activity": new_act, "diet_pref": new_diet,
                        "conditions": new_cond.strip(),
                        "condition_details": new_det.strip()})
                    st.rerun()

        st.markdown("### 🍲 Your food journey")
        hist = agent_history.recent(10)
        if hist:
            st.caption("Tap a dish to revisit it 💛")
            for i, h in enumerate(hist):
                if st.button(f"{h['dish']}  ·  {h['when']}",
                             key=f"hist_{i}", use_container_width=True):
                    ask = f"Tell me about {h['dish']} again"
                    st.session_state.transcript.append(
                        {"role": "user", "text": ask})
                    run_graph({"messages": [HumanMessage(content=ask)]})
                    st.rerun()
        else:
            st.caption("Nothing yet — ask me about any dish and I'll "
                       "remember it here!")

        st.markdown("")
        c1, c2 = st.columns(2)
        if c1.button("New chat", use_container_width=True):
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.transcript = []
            st.session_state.pending_interrupt = False
            st.session_state.booted = False
            st.rerun()
        if c2.button("Start over", use_container_width=True,
                     help="Erase profile and redo the questions"):
            prof.clear()
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.transcript = []
            st.session_state.pending_interrupt = False
            st.session_state.booted = False
            st.rerun()
    else:
        st.markdown("### 🌿 Getting to know you")
        st.caption("Answer the questions in the chat — your profile card "
                   "will appear here when we're done.")

    if not config.llm_ready():
        st.warning("`GROQ_API_KEY` missing in `.env` — chat won't work "
                   "until it's set.", icon="🔑")
    if not config.web_ready():
        st.caption("🔎 Tavily key not set — web fallback disabled.")
    if not vectorstore.ready():
        st.caption("📚 Knowledge index not built yet — run "
                   "`python -m nourish.agent.build_index`")

# ---------------------------------------------------------------- header
st.markdown("""
<div class='n-hero'>
  <h1>Nourish<em>.</em></h1>
  <p>Ghar ka khana, made for <i>your</i> body — dish guidance, honest
  numbers, and a plan that respects your health.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- boot
if not st.session_state.booted:
    st.session_state.booted = True
    snap = graph.get_state(CFG)
    if snap.values.get("messages") or snap.tasks:
        rebuild_from_checkpoint()
    elif not prof.is_complete(prof.get()):
        run_graph({"messages": []})   # kicks off onboarding -> first question

# ---------------------------------------------------------------- chat log
for m in st.session_state.transcript:
    role = m["role"]
    with st.chat_message(role, avatar="🌿" if role == "assistant" else "🧑🏽"):
        st.markdown(m["text"])
        v = m.get("verify")
        if v:
            if v["ok"]:
                st.caption(f"🛡️ {v['checked']} numbers verified against "
                           "tool data")
            else:
                st.caption("⚠️ couldn't verify these numbers against tool "
                           f"data: {', '.join(v['unverified'][:6])}")

# suggestion chips once onboarding is done and chat is fresh
if (prof.is_complete(prof.get()) and not st.session_state.pending_interrupt
        and len(st.session_state.transcript) <= 1):
    st.caption("Try one of these:")
    chips = ["Aloo paratha", "Masala dosa for dinner?",
             "Make me a diet chart", "High-protein veg breakfast ideas"]
    cols = st.columns(len(chips))
    for col, chip in zip(cols, chips):
        if col.button(chip, use_container_width=True):
            st.session_state.transcript.append({"role": "user", "text": chip})
            with st.chat_message("user", avatar="🧑🏽"):
                st.markdown(chip)
            run_graph({"messages": [HumanMessage(content=chip)]})
            st.rerun()

# ---------------------------------------------------------------- input
placeholder = ("Type your answer…" if st.session_state.pending_interrupt
               else "Name a dish, ask for a diet chart, or tell me what changed…")
if user_text := st.chat_input(placeholder):
    st.session_state.transcript.append({"role": "user", "text": user_text})
    with st.chat_message("user", avatar="🧑🏽"):
        st.markdown(user_text)
    # safety input rail: catch self-harm / dangerous-health intent BEFORE the
    # message reaches the agent, and answer with care instead of running it
    if safety.screen(user_text).blocked:
        st.session_state.transcript.append(
            {"role": "assistant", "text": safety.crisis_response(prof.get())})
    elif st.session_state.pending_interrupt:
        run_graph(Command(resume=user_text))
    else:
        run_graph({"messages": [HumanMessage(content=user_text)]})
    st.rerun()
