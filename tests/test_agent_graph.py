"""Onboarding human-in-the-loop flow through the compiled graph.

Runs entirely without an LLM: the onboarding node is deterministic, so we can
drive it with Command(resume=...) like the UI does.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from nourish.agent import profile as prof
from nourish.agent.graph import build_graph


def _drive(app, cfg, answers):
    res = app.invoke({"messages": []}, cfg)
    steps = 0
    while "__interrupt__" in res and steps < len(answers):
        res = app.invoke(Command(resume=answers[steps]), cfg)
        steps += 1
    return res, steps


def test_onboarding_saves_profile_and_welcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILE_DB", tmp_path / "p.db")
    app = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    answers = ["Ramiz", "male", "24", "5'8", "70 kg", "light walking",
               "veg", "I have diabetes", "diagnosed last year, on metformin"]
    res, steps = _drive(app, cfg, answers)

    assert "__interrupt__" not in res, "onboarding should finish"
    assert steps == len(answers), "diagnosis should trigger the describe question"
    p = prof.get()
    assert prof.is_complete(p)
    assert p["name"] == "Ramiz" and p["gender"] == "male" and p["age"] == 24
    assert p["conditions"] == "I have diabetes"
    assert "metformin" in p["condition_details"]
    welcome = res["messages"][-1].content
    assert "Ramiz" in welcome and "BMI" in welcome


def test_onboarding_skips_describe_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILE_DB", tmp_path / "p.db")
    app = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "t2"}}

    answers = ["Asha", "female", "30", "160", "55", "regular exercise",
               "non-veg", "no"]
    res, steps = _drive(app, cfg, answers)
    assert "__interrupt__" not in res
    assert steps == len(answers), "'no' should skip the describe question"
    assert prof.get()["conditions"] == ""


def test_onboarding_reasks_on_bad_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILE_DB", tmp_path / "p.db")
    app = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "t3"}}

    res = app.invoke({"messages": []}, cfg)              # -> asks name
    res = app.invoke(Command(resume="Ramiz"), cfg)       # -> asks gender
    res = app.invoke(Command(resume="banana"), cfg)      # unparseable gender
    q = res["__interrupt__"][0].value
    assert "male" in q.lower(), "should re-ask gender with a hint"
