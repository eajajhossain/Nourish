"""Resolver tests — assert robust behaviours, not brittle exact picks.

These require ingredients.db; they skip cleanly if it isn't built.
"""
import pytest

from nourish import data_access, resolver


def _db_ready() -> bool:
    try:
        return len(data_access.all_ingredients()) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(),
                                reason="ingredients.db not built")


def test_exact_match():
    r = resolver.resolve("Paneer")
    assert r.ok and r.method == "exact"
    assert r.ingredient.name == "Paneer"


def test_alias_match():
    r = resolver.resolve("gobi")
    assert r.ok
    assert "cauliflower" in r.ingredient.name.lower()


def test_alias_resolves_to_base_not_processed():
    # 'aloo' -> potato; must land on a real potato, not 'Flour, potato'
    r = resolver.resolve("aloo")
    assert r.ok
    assert "potato" in r.ingredient.name.lower()
    assert "flour" not in r.ingredient.name.lower()


def test_typo_tolerance():
    r = resolver.resolve("tomatoe")
    assert r.ok
    assert "tomato" in r.ingredient.name.lower()


def test_absent_ingredient_is_low_confidence():
    # a nonsense ingredient must NOT confidently match anything
    r = resolver.resolve("blorptang root")
    assert not r.ok


def test_empty_query():
    r = resolver.resolve("   ")
    assert r.ingredient is None and r.method == "none"


def test_score_capped_at_100():
    r = resolver.resolve("jeera")
    assert r.score <= 100.0
