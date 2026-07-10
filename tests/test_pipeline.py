"""End-to-end pipeline smoke tests (deterministic path, no LLM)."""
import pytest

from nourish import data_access, pipeline


def _db_ready() -> bool:
    try:
        return len(data_access.all_ingredients()) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="ingredients.db not built")


def test_transform_recipe_end_to_end():
    text = "150 g refined wheat flour\n2 tbsp ghee\n3 tsp sugar"
    res = pipeline.transform_recipe(text, "lower_calorie")
    assert len(res.parsed) == 3
    # every line resolved to something
    assert all(m is not None for _, m, _, _ in res.resolution)
    # lower_calorie must reduce calories
    assert res.transformation.after.totals["kcal"] < res.transformation.before.totals["kcal"]
    # narrative mentions the before/after energy figure
    assert "Energy" in res.narrative


def test_unknown_goal_propagates():
    with pytest.raises(ValueError):
        pipeline.transform_recipe("150 g atta", "be_purple")


def test_make_variants_returns_multiple_dimensions():
    vr = pipeline.make_variants("1 cup rice\n2 tsp sugar")
    # at least the iron and calcium boosts should fire on rice+sugar
    goals = {v.goal for v in vr.variants}
    assert "iron_boost" in goals and "calcium_boost" in goals
    # every returned variant actually changed something
    assert all(v.transformation.swaps for v in vr.variants)
    assert vr.baseline.totals["iron_mg"] >= 0
