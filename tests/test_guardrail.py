"""Number-verification guardrail: answers may only contain tool numbers."""
from nourish.agent.guardrail import verify_answer

TOOL = ('{"nutrition": {"kcal": 164.58, "protein_g": 3.29, '
        '"sodium_mg": 191.28, "fibre_g": 2.52}}')


def test_exact_and_rounded_numbers_pass():
    ans = ("One dosa has 164.58 kcal (about 165 kcal), 3.29 g protein "
           "and 191.3 mg sodium.")
    v = verify_answer(ans, [TOOL])
    assert v.ok, v.unverified
    assert v.checked >= 3


def test_invented_number_is_flagged():
    ans = "One dosa has 164.58 kcal and 99.9 g of protein."
    v = verify_answer(ans, [TOOL])
    assert not v.ok
    assert "99.9" in v.unverified


def test_small_counting_numbers_ignored():
    ans = "Step 3: cook for 2 minutes on each side, makes 4 parathas."
    v = verify_answer(ans, [TOOL])
    assert v.ok
    assert v.checked == 0


def test_profile_numbers_allowed():
    ans = "Your target is 2130 kcal per day at 82 kg."
    v = verify_answer(ans, ["{}"], profile={"weight_kg": 82.0,
                                            "target": 2130})
    assert v.ok, v.unverified


def test_serving_multiples_allowed():
    ans = "Two dosas give you about 329 kcal."
    v = verify_answer(ans, [TOOL])
    assert v.ok, v.unverified


def test_no_sources_no_pass_for_data_numbers():
    v = verify_answer("It has 512.7 kcal.", ["no numbers here"])
    assert not v.ok
