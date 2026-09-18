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
