"""Turn an engine-computed Transformation into human-readable text.

Deterministic template by default; if an LLM is configured it rewords the
template (numbers preserved). The template is the source of truth for facts.
"""
from __future__ import annotations

from .schema import NUTRIENT_COLUMNS
from .swap_engine import Transformation

_SHOW = ["kcal", "protein_g", "carb_g", "fat_g", "fibre_g", "sugar_g", "sodium_mg"]


def _fmt_delta(d: float) -> str:
    return f"{'+' if d >= 0 else ''}{d}"


def summary(t: Transformation, dish: str | None = None,
            insights: list[str] | None = None) -> str:
    goal = t.goal.replace("_", " ")
    head = f"Here's a {goal} version" + (f" of {dish}" if dish else "") + ":"
    lines = [head]

    if t.swaps:
        lines.append("\nSwaps made:")
        for s in t.swaps:
            if s.is_addition:
                lines.append(f"  - Add {s.replacement_name} ({s.reason})")
            elif s.is_reduction:
                lines.append(f"  - Use less {s.original_name} ({s.reason})")
            else:
                lines.append(f"  - {s.original_name} -> {s.replacement_name} "
                             f"({s.reason})")
    else:
        lines.append("\nNo beneficial swaps found - this recipe already looks "
                     "good for that goal.")

    lines.append("\nNutrition (before -> after, per recipe):")
    for k in _SHOW:
        label, unit = NUTRIENT_COLUMNS[k]
        b, a = t.before.totals.get(k, 0), t.after.totals.get(k, 0)
        lines.append(f"  {label}: {b} -> {a} {unit} ({_fmt_delta(t.delta(k))})")

    if insights:
        lines.append("\nBenefits & tips:")
        for tip in insights:
            lines.append(f"  - {tip}")

    if t.notes:
        lines.append("\nNotes:")
        for n in t.notes:
            lines.append(f"  ! {n}")

    return "\n".join(lines)


def phrase_transformation(t: Transformation, dish: str | None = None,
                          insights: list[str] | None = None,
                          use_llm: bool = True) -> str:
    """Friendly narrative. Falls back to the deterministic template."""
    template = summary(t, dish=dish, insights=insights)
    if use_llm:
        try:
            from . import llm
            if llm.available():
                worded = llm.phrase(template)
                if worded:
                    return worded.strip()
        except Exception:
            pass
    return template
