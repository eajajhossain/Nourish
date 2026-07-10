"""Seed recipe library + content tests."""
from nourish import content, recipes


def test_recipes_load():
    rs = recipes.all_recipes()
    assert len(rs) >= 8
    r = recipes.get("Aloo Paratha")
    assert r is not None and r.ingredients
    txt = r.as_text()
    assert "atta" in txt and "\n" in txt


def test_food_history_facts():
    assert len(content.FOOD_HISTORY) >= 5
    assert content.fact(0) == content.fact(len(content.FOOD_HISTORY))  # wraps
    assert "potato" in content.FOOD_HISTORY[0].lower()


def test_deficiency_notes_cover_boost_goals():
    for g in ("higher_protein", "iron_boost", "calcium_boost", "higher_fibre"):
        assert g in content.DEFICIENCY_NOTES
