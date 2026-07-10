"""History store tests (uses a temp DB so it never touches real history)."""
import pytest

from nourish import data_access, history, pipeline


def _db_ready() -> bool:
    try:
        return len(data_access.all_ingredients()) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="ingredients.db not built")


@pytest.fixture(autouse=True)
def temp_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.db")


def test_save_and_list():
    res = pipeline.transform_recipe("150 g refined wheat flour\n2 tbsp ghee",
                                    "lower_calorie", dish="Test paratha")
    hid = history.save(res, dish="Test paratha")
    assert hid >= 1

    recent = history.list_recent()
    assert len(recent) == 1
    assert recent[0]["dish"] == "Test paratha"
    assert recent[0]["goal"] == "lower_calorie"
    assert "kcal" in recent[0]["before"]


def test_get_roundtrip():
    res = pipeline.transform_recipe("3 tsp sugar", "lower_sugar", dish="Chai")
    hid = history.save(res, dish="Chai")
    got = history.get(hid)
    assert got is not None
    assert got["dish"] == "Chai"
    assert isinstance(got["swaps"], list)
    assert isinstance(got["insights"], list)
