"""Number-verification guardrail.

"The LLM never touches a number" is the project's golden rule — this module
ENFORCES it instead of trusting it. After the agent answers, every number in
the answer text is checked against the numbers the model was actually given
this turn (tool outputs + the user's own profile). Anything unaccounted for
is flagged in the UI.

Tolerances are deliberate: the model may round (164.58 -> 165, 191.28 ->
191.3) and small counting numbers (step 3, 2 parathas, 10 minutes) are part
of language, not nutrition data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# counting numbers, timings, step indices — language, not data
_SMALL_MAX = 30.0
# "400°F (200°C)", "4-5 hours" style ranges are cooking language too
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class Verification:
    checked: int = 0                       # data-like numbers in the answer
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unverified


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:
            continue
    return out


def _matches(value: float, source: float) -> bool:
    if value == source:
        return True
    # the model may round to fewer decimals or the nearest whole number
    if abs(value - round(source)) < 0.5 and value == round(value):
        return True
    if abs(value - source) <= 0.05 + 10 ** -min(_decimals(value), 3):
        return True
    # scaled by an integer serving count (2 parathas -> 2 × kcal)
    for k in (2, 3, 4):
        if source and abs(value - source * k) < 0.5 * k:
            return True
    return False


def _decimals(v: float) -> int:
    s = f"{v}"
    return len(s.split(".")[1]) if "." in s else 0


def verify_answer(answer: str, source_texts: list[str],
                  profile: dict | None = None) -> Verification:
    """Check every data-like number in `answer` against the numbers present
    in `source_texts` (tool outputs of this turn) and the profile."""
    allowed = []
    for t in source_texts:
        allowed.extend(_numbers(t))
    for v in (profile or {}).values():
        if isinstance(v, (int, float)) and v is not None:
            allowed.append(float(v))

    result = Verification()
    for raw in _NUM.finditer(answer or ""):
        try:
            value = float(raw.group().replace(",", ""))
        except ValueError:
            continue
        if value <= _SMALL_MAX and value == round(value):
            continue  # counting/steps/timings — not data
        result.checked += 1
        if not any(_matches(value, s) for s in allowed):
            result.unverified.append(raw.group())
    # de-duplicate while keeping order
    seen: set[str] = set()
    result.unverified = [x for x in result.unverified
                         if not (x in seen or seen.add(x))]
    return result
