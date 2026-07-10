"""Profile store + onboarding answer parsers."""
import pytest

from nourish.agent import profile as prof


# ---------------------------------------------------------------- parsers
@pytest.mark.parametrize("text,expected", [
    ("male", "male"), ("I am a Man", "male"), ("F", "female"),
    ("female", "female"), ("ladki", "female"), ("dunno", None),
])
def test_parse_gender(text, expected):
    assert prof.parse_gender(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("170 cm", 170.0), ("170", 170.0), ("1.7 m", 170.0), ("1.7", 170.0),
    ("5'7", 170.2), ("5 ft 7 in", 170.2), ("5.5", 167.6), ("999", None),
])
def test_parse_height(text, expected):
    got = prof.parse_height_cm(text)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, abs=0.5)


@pytest.mark.parametrize("text,expected", [
    ("65 kg", 65.0), ("65", 65.0), ("140 lbs", 63.5), ("5", None),
])
def test_parse_weight(text, expected):
    got = prof.parse_weight_kg(text)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, abs=0.2)


@pytest.mark.parametrize("text,neg", [
    ("no", True), ("None", True), ("nahi", True), ("I'm fine", True),
    ("I have diabetes", False), ("knee pain", False),
])
def test_is_negative(text, neg):
    assert prof.is_negative(text) is neg


# ---------------------------------------------------------------- store
def test_save_get_update(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILE_DB", tmp_path / "profile.db")
    assert prof.get() is None
    prof.save(name="Ramiz", gender="male", age=24, height_cm=172,
              weight_kg=70, activity="light", diet_pref="vegetarian",
              conditions="", condition_details="")
    p = prof.get()
    assert prof.is_complete(p)
    assert prof.bmi(p) == pytest.approx(23.7, abs=0.1)
    assert prof.daily_calories(p) > 1800

    p2 = prof.update_fields({"weight_kg": 75, "bogus": "ignored"})
    assert p2["weight_kg"] == 75
    assert p2["name"] == "Ramiz"

    prof.clear()
    assert prof.get() is None


def test_incomplete_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILE_DB", tmp_path / "profile.db")
    prof.save(name="X", gender="female")
    assert not prof.is_complete(prof.get())
