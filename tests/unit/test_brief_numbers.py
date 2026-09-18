"""What counts as a number worth putting in a brief's quantitative table."""

import automatron_core as core


def test_a_key_is_judged_by_its_words_not_its_characters():
    """'account' and 'discount' both contain 'count', and neither is a measurement."""
    assert core._is_measure("account_opened") is False
    assert core._is_measure("discount_code") is False
    assert core._is_measure("account_age_days") is True
    assert core._is_measure("factor_count") is True


def test_measures_across_the_sectors_are_still_recognised():
    for key in ("pc", "miss_distance_m", "deflated_sharpe", "notional_usd",
                "approval_threshold_usd", "risk_score", "completeness", "value_usd"):
        assert core._is_measure(key) is True, key


def test_a_date_is_not_a_measurement():
    """An ISO date reads as numeric to a loose pattern, hyphens and all."""
    extracted = core._flatten_numbers({"t": {"filed_on": "2026-03-23", "days_open": 20}})
    assert "t days open" in extracted
    assert not any("2026-03-23" == value for value in extracted.values())


def test_booleans_and_prose_stay_out():
    extracted = core._flatten_numbers(
        {"t": {"high_value": True, "level": "RED", "score": 42}})
    assert extracted == {"t score": "42"}


def test_the_table_stays_small_enough_to_read():
    wide = {f"metric_{i}_count": i for i in range(50)}
    assert len(core._flatten_numbers({"t": wide})) <= 12


def test_the_level_shown_is_the_one_a_tool_decided():
    """A term mentioned elsewhere must not outrank the tool that made the call.

    A use table can report the level its own answer would suggest in isolation. If
    the brief picks the first vocabulary term it finds anywhere, that suggestion wins
    on vocabulary order alone and the brief shows a level nothing decided.
    """
    spec = _level_spec(["READY_FOR_EXAMINER", "CORRECTIONS_LIKELY", "HEARING_LIKELY"])
    completed = {
        "s3": {"data": {"use_permission": {"status": "permitted",
                                           "suggested_level": "READY_FOR_EXAMINER"}}},
        "s4": {"data": {"prescreen_outcome": {"level": "CORRECTIONS_LIKELY",
                                              "fail_count": 1}}},
    }
    assert core._level_from(completed, spec) == "CORRECTIONS_LIKELY"


def test_a_mention_is_still_used_when_no_tool_declared_a_level():
    spec = _level_spec(["READY_FOR_EXAMINER", "CORRECTIONS_LIKELY"])
    completed = {"s1": {"data": {"t": {"suggested_level": "CORRECTIONS_LIKELY"}}}}
    assert core._level_from(completed, spec) == "CORRECTIONS_LIKELY"


def test_the_first_vocabulary_entry_is_the_last_resort():
    spec = _level_spec(["ALPHA", "BETA"])
    assert core._level_from({"s1": {"data": {"t": {"note": "nothing here"}}}}, spec) == "ALPHA"


def _level_spec(vocabulary):
    """A minimal workflow spec carrying only the vocabulary under test."""
    from tests import testsector

    spec = testsector.build_pack().workflows[0]
    return spec.model_copy(update={"level_vocab": vocabulary})
