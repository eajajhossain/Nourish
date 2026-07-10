"""Vector-less RAG lookup + diet chart generation (no network, no LLM)."""
from nourish.agent import dietchart, vectorless


def test_find_dish_exact_ish():
    hits = vectorless.find_dish("aloo paratha")
    assert hits, "expected at least one match"
    assert any("paratha" in h["name"].lower() for h in hits)
    assert hits[0]["nutrition"] is None or "kcal" in (hits[0]["nutrition"] or {})


def test_confident_hit_vs_miss():
    assert vectorless.confident_hit("masala dosa") is not None
    assert vectorless.confident_hit("zzz not a dish qqq") is None


def _profile(**over):
    base = dict(name="T", gender="male", age=30, height_cm=175, weight_kg=80,
                activity="light", diet_pref="vegetarian",
                conditions="", condition_details="")
    base.update(over)
    return base


def test_diet_chart_structure_and_budget():
    chart = dietchart.build_chart(_profile())
    assert len(chart["meals"]) == 4
    total = sum(m["kcal_actual"] for m in chart["meals"])
    assert 0.5 * chart["daily_target_kcal"] <= total <= 1.35 * chart["daily_target_kcal"]
    names = [d["dish"] for m in chart["meals"] for d in m["dishes"]]
    assert len(names) == len(set(names)), "no dish repeated across meals"


def test_diet_chart_respects_veg():
    chart = dietchart.build_chart(_profile(diet_pref="vegetarian"))
    for meal in chart["meals"]:
        for d in meal["dishes"]:
            assert not dietchart._NONVEG.search(d["dish"]), d["dish"]


def test_diet_chart_flags_diabetes():
    chart = dietchart.build_chart(_profile(conditions="type 2 diabetes"))
    assert "diabetes" in chart["adjusted_for"]


def test_diet_chart_excludes_condiments():
    chart = dietchart.build_chart(_profile())
    for meal in chart["meals"]:
        for d in meal["dishes"]:
            assert not dietchart._NOT_A_DISH.search(d["dish"]), d["dish"]
