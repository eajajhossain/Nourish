"""Health-insight tests — all pure (no DB needed)."""
from nourish import health_insights as hi
from nourish.nutrition_engine import RecipeNutrition
from nourish.swap_engine import Transformation


def _profile(**kw):
    base = {k: 0.0 for k in
            ["kcal", "protein_g", "carb_g", "fat_g", "fibre_g", "sugar_g",
             "sodium_mg", "calcium_mg", "iron_mg", "vitc_mg"]}
    base.update(kw)
    return base


def test_benefit_high_fibre():
    texts = [i.text for i in hi.analyze(_profile(fibre_g=10, kcal=300))]
    assert any("fibre" in t.lower() for t in texts)


def test_caution_high_sodium():
    out = hi.analyze(_profile(sodium_mg=800, kcal=300))
    assert any(i.kind == "caution" and "sodium" in i.text.lower() for i in out)


def test_no_false_claims_on_missing_data():
    # a profile with no sodium/sugar must not raise a high-sodium/sugar caution
    out = hi.analyze(_profile(kcal=300, protein_g=5))
    assert not any("sodium" in i.text.lower() or "sugar" in i.text.lower()
                   for i in out)


def test_protein_tier_dedup():
    texts = [i.text for i in hi.analyze(_profile(protein_g=25, kcal=400))]
    assert "High in protein - helps keep you full" in texts
    assert "Good source of protein" not in texts


def _transformation(before, after, goal="higher_fibre"):
    return Transformation(
        goal=goal,
        before=RecipeNutrition(totals=before, lines=[]),
        after=RecipeNutrition(totals=after, lines=[]),
    )


def test_improvement_reports_healthy_direction():
    t = _transformation(_profile(fibre_g=4, sugar_g=12, kcal=800),
                        _profile(fibre_g=17, sugar_g=3, kcal=700))
    texts = [i.text for i in hi.improvements(t)]
    assert any("fibre" in x.lower() and "up" in x.lower() for x in texts)
    assert any("sugar" in x.lower() and "down" in x.lower() for x in texts)


def test_improvement_ignores_unhealthy_direction():
    # fibre went DOWN -> must not be reported as an improvement
    t = _transformation(_profile(fibre_g=17), _profile(fibre_g=4))
    assert not any("fibre" in i.text.lower() for i in hi.improvements(t))


def test_insights_for_transformation_returns_strings():
    t = _transformation(_profile(fibre_g=4, kcal=800),
                        _profile(fibre_g=17, kcal=700))
    out = hi.insights_for_transformation(t)
    assert out and all(isinstance(x, str) for x in out)
