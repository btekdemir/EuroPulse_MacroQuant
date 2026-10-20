"""Research note: the number check is the product, so it is tested hard. No test calls the real API."""

import types

import pytest

from hicp.note import MAX_ATTEMPTS, Fact, build_facts, facts_hash, matches, verify, write_note
from hicp.schemas import DraftNote, NoteCitation

FACTS = [Fact(id="dec", label="Dec forecast, %", value=3.816), Fact(id="last", label="Last print, %", value=3.77),
         Fact(id="base", label="Base effect, pp", value=-0.1135), Fact(id="p4", label="P(>4%), %", value=35.86),
         Fact(id="thr4", label="Threshold, %", value=4.0), Fact(id="n", label="Origins", value=198)]


def cite(*pairs):
    return [NoteCitation(number=n, fact_id=f) for n, f in pairs]


def test_matches_rounding_precision_and_sign():
    assert matches("3.8", 3.816) and matches("3.82", 3.816) and matches("3,8", 3.816) and matches("4", 3.816)
    assert not matches("3.9", 3.816) and not matches("3.81", 3.816)
    assert matches("0.11", -0.1135) and matches("−0.11", -0.1135)  # sign-insensitive: words carry direction
    assert matches("36", 35.86) and not matches("35", 35.86) and matches("198", 198)


def test_a_faithful_note_passes_and_links_each_number_to_its_fact():
    body = "Headline inflation is forecast at 3.8% in Dec 2026 versus 3.77% now; base effects subtract 0.11pp."
    nums, problems = verify(body, cite(("3.8", "dec"), ("3.77", "last"), ("0.11", "base")), FACTS)
    assert problems == [] and [n.fact_id for n in nums] == ["dec", "last", "base"] and all(n.ok for n in nums)
    assert nums[0].fact_label == "Dec forecast, %"


def test_years_are_not_numbers_to_cite():
    nums, problems = verify("From 2010 to 2026, in 2020-2023.", [], FACTS)
    assert problems == [] and nums == []


def test_an_invented_number_is_rejected():
    _, problems = verify("Inflation will hit 4.7% in Dec 2026.", cite(("4.7", "dec")), FACTS)
    assert problems and "does not equal fact 'dec'" in problems[0]


def test_an_uncited_number_is_rejected_even_if_it_is_correct():
    _, problems = verify("Forecast 3.8%.", [], FACTS)
    assert problems == ["'3.8' is in the text but cites no fact"]


def test_a_citation_to_a_made_up_fact_is_rejected():
    _, problems = verify("Forecast 3.8%.", cite(("3.8", "secret_model")), FACTS)
    assert "not in the fact sheet" in problems[0]


def test_citing_the_wrong_fact_for_the_value_is_rejected():
    _, problems = verify("Forecast 3.77% in December.", cite(("3.77", "dec")), FACTS)  # 3.77 is 'last', not 'dec'
    assert problems


def test_digits_hidden_in_other_forms_are_still_caught():
    for body in ["Up 5 percent.", "A 3-month view.", "Roughly 40% odds.", "Down 1,2 points.", "About −0.5pp."]:
        assert verify(body, [], FACTS)[1], body


def test_french_decimal_comma_and_unicode_minus():
    nums, problems = verify("L'inflation serait de 3,8 % ; l'effet de base est de −0,11 pt.", cite(("3,8", "dec"), ("−0,11", "base")), FACTS)
    assert problems == [] and len(nums) == 2


class FakeClient:
    def __init__(self, *drafts):
        self.queue, self.calls = list(drafts), []
        self.messages = types.SimpleNamespace(parse=self._parse)

    def _parse(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(parsed_output=self.queue.pop(0), stop_reason="end_turn")


GOOD = DraftNote(title="Outlook", body="Forecast 3.8% versus 3.77%.", citations=cite(("3.8", "dec"), ("3.77", "last")))
BAD = DraftNote(title="Outlook", body="Forecast 4.7% versus 3.77%.", citations=cite(("4.7", "dec"), ("3.77", "last")))


def test_write_note_accepts_first_good_draft():
    c = FakeClient(GOOD)
    n = write_note("en", FACTS, c, "m")
    assert n.verified and n.attempts == 1 and len(c.calls) == 1
    assert "Dec forecast" in c.calls[0]["messages"][0]["content"] and "tools" not in c.calls[0]


def test_write_note_retries_once_with_the_failures_then_accepts():
    c = FakeClient(BAD, GOOD)
    n = write_note("en", FACTS, c, "m")
    assert n.verified and n.attempts == 2
    assert "rejected by an automatic number check" in c.calls[1]["messages"][0]["content"] and "4.7" in c.calls[1]["messages"][0]["content"]


def test_write_note_gives_up_after_max_attempts_and_marks_it_unverified():
    c = FakeClient(*[BAD] * MAX_ATTEMPTS)
    n = write_note("en", FACTS, c, "m")
    assert not n.verified and n.attempts == MAX_ATTEMPTS and n.problems and len(c.calls) == MAX_ATTEMPTS


def test_unparseable_output_is_handled():
    n = write_note("en", FACTS, FakeClient(None, None), "m")
    assert not n.verified and n.body == ""


def test_facts_hash_changes_when_a_fact_changes():
    h = facts_hash(FACTS)
    assert facts_hash(FACTS) == h
    assert facts_hash([Fact(id="dec", label="x", value=3.9), *FACTS[1:]]) != h


def test_real_fact_sheet_contains_what_the_prompt_asks_for():
    from hicp.config import ROOT
    if not (ROOT / "outputs" / "forecast.json").exists():
        pytest.skip("run run.py first")
    ids = {f.id for f in build_facts()}
    assert {"forecast_h3", "band68_lo", "band68_level", "threshold_4", "p_above_4", "base_effect_pp", "momentum_pp",
            "ratio_h3", "dm_p_h3", "coverage_crisis_68", "horizon_months"} <= ids
