"""Nutrition-engine tests.

The math is validated with pure-function checks (scale_profile) plus an
end-to-end check against a real ingredient from the store: 100 g of any
ingredient must reproduce its per-100g profile exactly.
"""
import pytest

from nourish import data_access, nutrition_engine as ne
from nourish.schema import NUTRIENT_KEYS


def test_scale_100g_is_identity():
    per100 = {k: 10.0 for k in NUTRIENT_KEYS}
    scaled, missing = ne.scale_profile(per100, 100)
    assert missing == []
    assert all(scaled[k] == 10.0 for k in NUTRIENT_KEYS)


def test_scale_is_linear():
    per100 = {"kcal": 100.0, "protein_g": 8.0}
    scaled, _ = ne.scale_profile(per100, 250)
    assert scaled["kcal"] == 250.0
    assert scaled["protein_g"] == 20.0


def test_scale_reports_missing_and_skips_none():
    per100 = {"kcal": 100.0, "protein_g": None}
    scaled, missing = ne.scale_profile(per100, 200)
    assert scaled["kcal"] == 200.0
    assert "protein_g" in missing
    assert "protein_g" not in scaled


def test_totals_sum_two_lines():
    per_a = {k: 0.0 for k in NUTRIENT_KEYS}; per_a["kcal"] = 100.0
    per_b = {k: 0.0 for k in NUTRIENT_KEYS}; per_b["kcal"] = 50.0
    a, _ = ne.scale_profile(per_a, 100)
    b, _ = ne.scale_profile(per_b, 200)  # 50 * 2 = 100
    assert a["kcal"] + b["kcal"] == 200.0


def _first_complete_ingredient():
    for ing in data_access.all_ingredients():
        if ing.per100("kcal") is not None and ing.per100("protein_g") is not None:
            return ing
    return None


def test_end_to_end_100g_reproduces_profile():
    ing = _first_complete_ingredient()
    if ing is None:
        pytest.skip("ingredients.db not built — run python -m etl.build_all")
    res = ne.compute([ne.RecipeItem(ingredient_id=ing.id, qty=100, unit="g")])
    assert len(res.lines) == 1
    line = res.lines[0]
    assert abs(line.nutrients["kcal"] - ing.per100("kcal")) < 0.01
    assert abs(line.nutrients["protein_g"] - ing.per100("protein_g")) < 0.01


def test_missing_ingredient_is_warned_not_crashed():
    res = ne.compute([ne.RecipeItem(ingredient_id="does:not_exist", qty=100, unit="g")])
    assert res.lines == []
    assert any("not found" in w for w in res.warnings)
