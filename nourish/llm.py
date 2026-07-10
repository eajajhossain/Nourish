"""Optional, swappable LLM layer — language only, never numbers.

Two narrow jobs:
  * parse_recipe_items(text)  free-text recipe  -> [(name, qty, unit), ...]
  * phrase(prompt)            turn engine facts -> friendly prose

Provider is chosen by env vars, so Groq / Gemini / Ollama are interchangeable
and nothing in the core depends on any of them:

    NOURISH_LLM_PROVIDER = groq | gemini | ollama   (unset = disabled)
    NOURISH_LLM_API_KEY  = <key>                     (groq/gemini)
    NOURISH_LLM_MODEL    = <model name>              (optional override)

If no provider is configured, available() is False and callers fall back to
the deterministic parser/templates. Any network/parse error returns None so
the deterministic path always wins over a broken LLM.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .parsing import ParsedItem

PROVIDER = os.getenv("NOURISH_LLM_PROVIDER", "").strip().lower()
API_KEY = os.getenv("NOURISH_LLM_API_KEY", "").strip()
MODEL = os.getenv("NOURISH_LLM_MODEL", "").strip()

_DEFAULT_MODEL = {
    "groq": "llama-3.1-8b-instant",
    "gemini": "gemini-1.5-flash",
    "ollama": "llama3.1",
}


def available() -> bool:
    if PROVIDER in ("groq", "gemini"):
        return bool(API_KEY)
    if PROVIDER == "ollama":
        return True  # local; assume daemon if explicitly selected
    return False


def _model() -> str:
    return MODEL or _DEFAULT_MODEL.get(PROVIDER, "")


def _post(url: str, payload: dict, headers: dict) -> dict | None:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def complete(system: str, user: str) -> str | None:
    """Return the model's text reply, or None on any failure."""
    if not available():
        return None
    if PROVIDER == "groq":
        data = _post(
            "https://api.groq.com/openai/v1/chat/completions",
            {"model": _model(), "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}], "temperature": 0.2},
            {"Authorization": f"Bearer {API_KEY}"},
        )
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None
    if PROVIDER == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{_model()}:generateContent?key={API_KEY}")
        data = _post(url, {"contents": [{"parts": [
            {"text": system + "\n\n" + user}]}]}, {})
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return None
    if PROVIDER == "ollama":
        data = _post("http://localhost:11434/api/chat", {
            "model": _model(), "stream": False, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}]}, {})
        try:
            return data["message"]["content"]
        except Exception:
            return None
    return None


_PARSE_SYSTEM = (
    "You convert a recipe into structured ingredients. Return ONLY a JSON "
    "array of objects with keys: name (string), qty (number), unit (string, "
    "e.g. g, ml, tbsp, tsp, cup, piece). Do not include nutrition or any "
    "other text."
)


def parse_recipe_items(text: str) -> list[ParsedItem]:
    """LLM-backed parse. Returns [] on failure so the caller can fall back."""
    reply = complete(_PARSE_SYSTEM, text)
    if not reply:
        return []
    # be tolerant of code fences / surrounding prose
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        rows = json.loads(reply[start:end + 1])
    except Exception:
        return []
    items: list[ParsedItem] = []
    for r in rows:
        try:
            items.append(ParsedItem(
                name=str(r["name"]).strip(),
                qty=float(r["qty"]),
                unit=str(r.get("unit", "")).strip() or "piece",
                raw=str(r),
            ))
        except Exception:
            continue
    return items


def phrase(prompt: str) -> str | None:
    """Naturalise an engine-produced summary. Numbers come from the caller;
    the model only rewords. Returns None on failure (caller keeps template)."""
    system = (
        "You are a friendly Indian nutrition assistant. Rewrite the given "
        "recipe transformation summary in warm, clear language. Keep ALL "
        "numbers exactly as given — never change or invent any value."
    )
    return complete(system, prompt)
