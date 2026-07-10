"""Unit-conversion tests."""
from nourish import units


def test_mass_is_exact():
    assert units.to_grams(2, "kg").grams == 2000.0
    assert units.to_grams(500, "mg").grams == 0.5
    assert units.to_grams(150, "g").grams == 150.0


def test_volume_default_density():
    # water-like default density 1.0
    c = units.to_grams(1, "cup", "water")
    assert c.grams == 240.0


def test_volume_with_density_override():
    # 1 tbsp oil = 15 ml * 0.92 g/ml
    c = units.to_grams(1, "tbsp", "mustard oil")
    assert abs(c.grams - 15 * 0.92) < 1e-6


def test_unknown_density_sets_note():
    c = units.to_grams(1, "cup", "mystery puree")
    assert c.note is not None and "density" in c.note


def test_count_known_weight():
    c = units.to_grams(2, "piece", "onion")
    assert c.grams == 220.0  # 2 * 110
    assert c.note is not None


def test_count_unknown_weight_fallback():
    c = units.to_grams(1, "medium", "alien fruit")
    assert c.grams == units.DEFAULT_COUNT_WEIGHT
    assert "assumed" in c.note


def test_unknown_unit_treated_as_grams():
    c = units.to_grams(30, "blorp", "ghee")
    assert c.grams == 30.0
    assert "unrecognised" in c.note
