"""Messaging + cultural food-history content.

The plan is explicit: messaging matters as much as the product, and showing how
Indian cuisine has *always* evolved makes people open to evolving it again. None
of this attacks tradition -- it celebrates that our food has always absorbed new
ingredients. Kept as plain data so the UI (or an LLM) can present it.
"""
from __future__ import annotations

# Short, friendly framing shown up top. Respectful, not preachy.
TAGLINE = "Small, familiar swaps — same soul, more nourishment."

INTRO = (
    "Indian food has never stood still. The ingredients we call 'traditional' "
    "are themselves gifts from across the world, woven in over centuries. "
    "Nourish suggests gentle, India-friendly tweaks in that same spirit — your "
    "dish stays yours, just a little kinder to your body."
)

# "Did you know?" — cuisine has always evolved. Each is a real, checkable fact.
FOOD_HISTORY = [
    "The holy trinity of Indian cooking — potato, tomato and chilli — isn't "
    "Indian at all. All three came from the Americas via Portuguese traders only "
    "~400–500 years ago. Before that: no aloo, no tamatar, no mirch.",

    "Green and red chillies replaced long pepper (pippali) and black pepper as "
    "India's main source of heat only after they arrived from the Americas.",

    "Paneer is widely believed to have entered the subcontinent through Persian "
    "and Central Asian influence — a relatively late addition to Indian kitchens.",

    "Soya chunks (the protein-packed 'meal maker') are a 20th-century import, "
    "rooted in East Asian soy traditions and popularised in modern India.",

    "Cashews and pineapple were both introduced to India by the Portuguese from "
    "the Americas — today they feel completely native.",

    "Mass tea-drinking is barely ~150 years old in India, actively promoted by "
    "the colonial-era tea industry. Your daily chai is a recent ritual.",

    "Cauliflower and the orange carrot as we know them are fairly recent arrivals "
    "— earlier Indian carrots were red or purple.",

    "Refined sugar and maida at scale are industrial-era. For most of history, "
    "Indian sweetness came from jaggery and honey — which Nourish often swaps "
    "back in.",
]


def fact(index: int) -> str:
    """Deterministic accessor (index wraps)."""
    return FOOD_HISTORY[index % len(FOOD_HISTORY)]


# Why these boosts? Tie the goals to documented Indian deficiencies.
DEFICIENCY_NOTES = {
    "higher_protein": "Most Indian diets fall short on protein — even vegetarians "
                      "can close the gap with dals, besan and soya.",
    "iron_boost": "Iron-deficiency anaemia is widespread in India, especially "
                  "among women and children. Millets, besan and jaggery help.",
    "calcium_boost": "Calcium intake is low across much of India; ragi and sesame "
                     "are outstanding plant sources.",
    "higher_fibre": "Refined grains have stripped fibre from modern Indian meals; "
                    "whole grains and besan bring it back.",
    "diabetic_friendly": "India is a diabetes capital — lowering free sugar and "
                         "raising fibre keeps blood sugar steadier.",
    "lower_calorie": "Calorie-dense fried and sweet dishes add up; small cuts help "
                     "without losing the dish.",
    "lower_sugar": "Cutting added sugar is one of the simplest high-impact changes.",
    "lower_sodium": "High salt intake drives hypertension; easing off helps the heart.",
    "lower_fat": "Trimming excess fat lightens the dish while keeping the flavour.",
}
