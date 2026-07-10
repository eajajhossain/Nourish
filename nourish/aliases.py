"""Indian / Hinglish ingredient synonyms.

Maps a colloquial name a user is likely to type -> a canonical English term
that appears in (or matches well against) the ingredient store. This single
hand-built map removes most of the resolver's hard cases at near-zero cost.

Keys and values are lower-case. The resolver also matches the reverse
direction, so listing one synonym helps both ways.
"""
from __future__ import annotations

# colloquial -> canonical search term
ALIASES: dict[str, str] = {
    # grains / flours
    "atta": "wheat flour",
    "gehu": "wheat",
    "gehu atta": "wheat flour",
    "maida": "refined wheat flour",
    "besan": "bengal gram flour",
    "chawal": "rice",
    "basmati": "rice",
    "poha": "flattened rice",
    "suji": "semolina",
    "rava": "semolina",
    "jowar": "sorghum",
    "bajra": "pearl millet",
    "ragi": "finger millet",
    "makka": "maize",
    "makki": "maize",
    # pulses / dals
    "dal": "lentil",
    "daal": "lentil",
    "toor dal": "pigeon pea",
    "arhar dal": "pigeon pea",
    "moong": "green gram",
    "moong dal": "green gram",
    "masoor": "red lentil",
    "masoor dal": "red lentil",
    "chana": "bengal gram",
    "chana dal": "bengal gram",
    "rajma": "kidney beans",
    "chole": "chickpea",
    "kabuli chana": "chickpea",
    "urad": "black gram",
    "urad dal": "black gram",
    # dairy / fats
    "ghee": "ghee",
    "dahi": "curd",
    "doodh": "milk",
    "paneer": "paneer",
    "makhan": "butter",
    "malai": "cream",
    # vegetables
    "aloo": "potato",
    "pyaz": "onion",
    "pyaaz": "onion",
    "tamatar": "tomato",
    "tamaatar": "tomato",
    "gajar": "carrot",
    "matar": "peas",
    "gobi": "cauliflower",
    "patta gobi": "cabbage",
    "bhindi": "okra",
    "baingan": "brinjal",
    "lauki": "bottle gourd",
    "palak": "spinach",
    "methi": "fenugreek leaves",
    "shimla mirch": "capsicum",
    "adrak": "ginger",
    "lehsun": "garlic",
    "hari mirch": "green chilli",
    # spices
    "haldi": "turmeric",
    "jeera": "cumin",
    "dhania": "coriander",
    "mirch": "chilli",
    "lal mirch": "red chilli",
    "namak": "salt",
    "elaichi": "cardamom",
    "dalchini": "cinnamon",
    "laung": "clove",
    "saunf": "fennel",
    "rai": "mustard",
    "sarson": "mustard",
    # oils / sweeteners
    "tel": "oil",
    "sarson tel": "mustard oil",
    "cheeni": "sugar",
    "shakkar": "sugar",
    "gud": "jaggery",
    "gur": "jaggery",
    "shahad": "honey",
    # nuts
    "badam": "almond",
    "kaju": "cashew",
    "pista": "pistachio",
    "mungfali": "groundnut",
    "moongphali": "groundnut",
    "nariyal": "coconut",
}


def expand(name: str) -> str:
    """Return the canonical search term for a name, or the name unchanged."""
    return ALIASES.get(name.strip().lower(), name)


def expand_tokens(name: str) -> str:
    """Expand each word via the alias map (helps multi-word queries like
    'basmati rice' -> 'rice rice' -> deduped 'rice'). Order preserved."""
    out: list[str] = []
    for tok in name.strip().lower().split():
        exp = ALIASES.get(tok, tok)
        for w in exp.split():
            if not out or out[-1] != w:
                out.append(w)
    return " ".join(out)
