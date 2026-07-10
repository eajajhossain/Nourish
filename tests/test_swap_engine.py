"""Swap-engine tests — verify transformations actually improve the goal and
never apply nonsense swaps. Skip cleanly if the DB isn't built."""
import pytest

from nourish import data_access, swap_engine as se


def _db_ready() -> bool:
    try:
        return len(data_access.all_ingredients()) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="ingredients.db not built")

RECIPE = [
    ("refined wheat flour", 150, "g"),
    ("ghee", 2, "tbsp"),
    ("sugar", 3, "tsp"),
    ("salt", 1, "tsp"),
]


def test_higher_fibre_increases_fibre():
    t = se.transform_by_name(RECIPE, "higher_fibre")
    assert len(t.swaps) >= 1
    assert t.after.totals["fibre_g"] > t.before.totals["fibre_g"]


def test_lower_calorie_reduces_calories():
    t = se.transform_by_name(RECIPE, "lower_calorie")
    assert t.after.totals["kcal"] < t.before.totals["kcal"]


def test_diabetic_friendly_reduces_sugar():
    t = se.transform_by_name(RECIPE, "diabetic_friendly")
    assert t.after.totals["sugar_g"] < t.before.totals["sugar_g"]


def test_unknown_goal_raises():
    with pytest.raises(ValueError):
        se.transform_by_name(RECIPE, "make_it_purple")


def test_no_swap_when_nothing_applies():
    # plain atta with a lower-sodium goal: no salt to cut, no additions defined
    t = se.transform_by_name([("atta", 100, "g")], "lower_sodium")
    assert t.swaps == []
    assert t.after.totals == t.before.totals


def test_swap_target_is_exact_not_fuzzy():
    # 'maida' -> protein swap must land on real Besan, never a fuzzy vegetable
    t = se.transform_by_name([("maida", 150, "g")], "higher_protein")
    subs = [s for s in t.swaps if not s.is_addition]
    assert len(subs) == 1
    assert subs[0].replacement_name == "Besan"


def test_additions_can_boost_a_recipe_with_no_substitutions():
    # a dish with no substitutable ingredient still gets a booster addition
    t = se.transform_by_name([("potato", 200, "g")], "iron_boost")
    assert any(s.is_addition for s in t.swaps)
    assert t.after.totals["iron_mg"] > t.before.totals["iron_mg"]


def test_iron_boost_increases_iron():
    t = se.transform_by_name([("rice", 1, "cup"), ("sugar", 2, "tsp")],
                             "iron_boost")
    assert len(t.swaps) >= 1
    assert t.after.totals["iron_mg"] > t.before.totals["iron_mg"]


def test_calcium_boost_increases_calcium():
    t = se.transform_by_name([("rice", 1, "cup")], "calcium_boost")
    assert t.after.totals["calcium_mg"] > t.before.totals["calcium_mg"]
