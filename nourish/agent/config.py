"""Environment / key handling for the agent layer.

Reads a .env file at the project root (never committed). Nothing else in the
package touches os.environ directly, so swapping providers stays a one-file
change.

    GROQ_API_KEY      = gsk_...        (the agent's brain)
    TAVILY_API_KEY    = tvly-...       (web search fallback)
    EMBEDDING_API_KEY = hf_...         (HuggingFace Inference API embeddings;
                                        unset -> Chroma's local ONNX model)
    NOURISH_AGENT_MODEL = <override>   (optional; defaults below)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from ..schema import ROOT

load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "").strip()
MODEL = os.getenv("NOURISH_AGENT_MODEL", "").strip() or "llama-3.3-70b-versatile"


def llm_ready() -> bool:
    return bool(GROQ_API_KEY)


def web_ready() -> bool:
    return bool(TAVILY_API_KEY)
