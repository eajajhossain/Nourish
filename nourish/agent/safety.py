"""Self-harm / dangerous-intent input rail — runs BEFORE the agent.

Nourish talks about food, and food language is full of harmless idioms —
"this biryani is to die for", "I'm dying to try dal makhani", "killer combo".
But a nutrition companion must never help someone hurt themselves. So every
user message is screened for genuine self-harm intent ("I want to die", "which
food helps me die", "how can I kill myself") before it ever reaches the LLM,
and if it fires we short-circuit to a compassionate crisis response instead of
answering.

Two layers, on purpose:

  Layer 1 — deterministic patterns (ALWAYS on, instant, free, offline).
            First-person harm intent, with food idioms explicitly excluded so
            "to die for" never trips it. This is the guarantee.

  Layer 2 — NeMo Guardrails self-check input (OPTIONAL, one cheap LLM call).
            Catches subtly phrased cases the patterns miss. Lazy-loaded; if
            nemoguardrails isn't installed or errors, we fall back to Layer 1
            alone — safety must never depend on a heavy optional dependency.
            Toggle with NOURISH_SAFETY_NEMO=0.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config

NEMO_CONFIG_DIR = Path(__file__).parent / "nemo_config"

# ------------------------------------------------------------------ Layer 1
# Food idioms that LOOK dangerous but are just warmth about a dish. Stripped
# out before intent matching so they can never cause a false block.
_IDIOMS = re.compile(
    r"to die for"
    r"|dying to (?:try|taste|eat|have|make|cook|know|see|learn)"
    r"|dying of (?:laughter|hunger|thirst|boredom|curiosity)"
    r"|die[- ]?hard"
    r"|killer (?:biryani|recipe|dish|meal|combo|combination|taste|looks?|snack)"
    r"|kill(?:ing)? (?:it|time|the (?:craving|hunger|flavou?r))"
    r"|kill for (?:a|some|this|that)"
    r"|to kill time",
    re.I,
)

# Genuine self-harm / self-injury / "help me die" intent. Kept specific to
# first-person harm so ordinary cooking talk stays untouched.
_HARM = [
    re.compile(p, re.I)
    for p in (
        r"\bkill(?:ing)?\s+(?:my ?self|me)\b",
        r"\bsuicid",                                      # suicide / suicidal
        r"\bend(?:ing)?\s+(?:my|this)\s+(?:own\s+)?life\b",
        r"\btak(?:e|ing)\s+my\s+(?:own\s+)?life\b",
        r"\b(?:want|wanna|wish|going|trying|ready|need|like)\s+(?:to\s+|na\s+)?die\b",
        r"\bi\s+(?:want|wanna|wish|need)\s+to\s+die\b",
        r"\b(?:how|way|ways|method|methods|easiest|best|fastest)\s+"
        r"(?:can\s+i\s+|do\s+i\s+|to\s+|i\s+can\s+)?die\b",
        r"\bhelp\s+me\s+(?:to\s+)?(?:die|end\s+it|kill)\b",
        # food / recipe explicitly tied to dying or self-harm
        r"\b(?:food|foods|recipe|recipes|dish|dishes|meal|meals|eat|drink|"
        r"ingredient|ingredients)\b.{0,30}\b(?:die|death|kill\s+me|"
        r"end\s+my\s+life|not\s+wake\s+up|never\s+wake)\b",
        r"\beat\b.{0,20}\b(?:to\s+die|and\s+die|so\s+i\s+die|to\s+death)\b",
        r"\b(?:don'?t|do\s+not|no\s+reason\s+to)\s+(?:want\s+to\s+)?(?:live|be\s+alive|wake\s+up)\b",
        r"\bbetter\s+off\s+dead\b",
        r"\bself[-\s]?harm\b",
        r"\b(?:hurt|harm|cut|injure|injuring|hurting|harming|cutting)\s+my ?self\b",
        r"\boverdos",                                     # overdose / overdosing
        r"\bpoison(?:ing)?\s+(?:my ?self|me)\b",
        r"\bstarve\s+(?:my ?self|to\s+death)\b",
        r"\bwhat\s+(?:can|should|do)\s+i\s+eat\s+to\s+(?:die|not\s+wake\s+up)\b",
    )
]


@dataclass
class SafetyVerdict:
    blocked: bool = False
    layer: str = ""          # "pattern" | "nemo" — which layer fired
    matched: str = ""        # the offending fragment (for logs, never shown)

    @property
    def ok(self) -> bool:
        return not self.blocked


def _pattern_hit(text: str) -> str | None:
    """Return the matched fragment if genuine harm intent is present, else None.
    Idioms are removed first so food warmth is never mistaken for a crisis."""
    cleaned = _IDIOMS.sub("  ", text or "")
    for rx in _HARM:
        m = rx.search(cleaned)
        if m:
            return m.group(0).strip()
    return None


# ------------------------------------------------------------------ Layer 2
def nemo_enabled() -> bool:
    """Layer 2 needs an LLM (Groq) and must be turned on. Off by env or no key
    -> we silently run on Layer 1 alone."""
    if os.getenv("NOURISH_SAFETY_NEMO", "1").strip() in ("0", "false", "no"):
        return False
    return config.llm_ready()


@lru_cache(maxsize=1)
def _rails():
    """Build the NeMo LLMRails once, reusing Nourish's own Groq LLM so there's
    a single model + key source. Returns None if anything is unavailable."""
    if not nemo_enabled():
        return None
    try:
        from langchain_groq import ChatGroq
        from nemoguardrails import LLMRails, RailsConfig

        # a PLAIN ChatGroq — NOT graph._llm(), which is .bind_tools(...)-wrapped
        # (a RunnableBinding). NeMo needs a BaseChatModel; the safety check has
        # no use for the tool belt anyway.
        llm = ChatGroq(model=config.MODEL, api_key=config.GROQ_API_KEY,
                       temperature=0)
        cfg = RailsConfig.from_path(str(NEMO_CONFIG_DIR))
        return LLMRails(cfg, llm=llm)
    except Exception:
        # nemoguardrails not installed, bad config, or init failure — Layer 1
        # still fully protects the app, so we degrade quietly.
        return None


def _nemo_hit(text: str) -> bool:
    """True if NeMo's self-check input rail decides the message is unsafe.
    Fails OPEN (returns False) on any error: Layer 1 is the real guarantee, so
    a flaky optional dependency must never block ordinary questions."""
    rails = _rails()
    if rails is None:
        return False
    try:
        res = rails.generate(
            messages=[{"role": "user", "content": text}],
            options={"rails": ["input"], "log": {"activated_rails": True}},
        )
        log = getattr(res, "log", None)
        for ar in (getattr(log, "activated_rails", None) or []):
            if getattr(ar, "stop", False):        # an input rail halted the turn
                return True
        return False
    except Exception:
        return False


# ------------------------------------------------------------------ public API
def screen(text: str) -> SafetyVerdict:
    """Screen one user message. Layer 1 (patterns) first — instant and the
    guarantee; Layer 2 (NeMo) only for what patterns let through."""
    hit = _pattern_hit(text)
    if hit:
        return SafetyVerdict(blocked=True, layer="pattern", matched=hit)
    if _nemo_hit(text):
        return SafetyVerdict(blocked=True, layer="nemo", matched="(self-check)")
    return SafetyVerdict(blocked=False)


def crisis_response(profile: dict | None = None) -> str:
    """A warm, non-clinical reply with real Indian helplines. Never diagnoses,
    never mentions food; its only job is to be kind and point to help."""
    name = (profile or {}).get("name") or "friend"
    return (
        f"I hear you, {name}, and I'm really glad you told me. 💛 I can't help "
        "with anything that would harm you — and much more than that, I don't "
        "want you to be hurt at all. You matter, and what you're feeling right "
        "now can change with the right support.\n\n"
        "Please reach out to someone who can talk this through with you today. "
        "In India, these lines are free, confidential and open 24×7:\n\n"
        "- **Tele-MANAS** (Govt. of India): **14416** or **1-800-891-4416**\n"
        "- **KIRAN** mental-health helpline: **1800-599-0019**\n"
        "- **Vandrevala Foundation**: **1860-2662-345** / **1800-2333-330**\n"
        "- **AASRA**: **+91-98204-66726**\n\n"
        "If you feel you might act on these thoughts right now, please call "
        "**112** or go to your nearest hospital — you don't have to face this "
        "alone. When you're ready and safe, I'll be right here to talk about "
        "food and nourishing yourself. 🌿"
    )
