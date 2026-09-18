"""Dispute summaries: the timeline, the placeholder dates, and when counsel is forced."""

import datetime as dt

import pytest

import automatron_realestate as re_


@pytest.fixture(scope="module", autouse=True)
def samples():
    re_.ensure_samples()


def test_the_timeline_is_built_from_dated_lines_only_and_ordered():
    result = re_.build_timeline.invoke({"sample_name": "dispute_deposit"})
    assert result["event_count"] == 4
    dates = [e["date"] for e in result["events"]]
    assert dates == sorted(dates)
    assert result["first_event"] == "2026-03-01"
    assert result["last_event"] == "2026-04-14"


def test_a_long_silence_is_reported():
    """In a dispute the gaps are often the point, so they are not passed over."""
    result = re_.build_timeline.invoke({"sample_name": "dispute_hoa_fence"})
    assert result["gap_count"] >= 1
    assert all(g["days"] >= 14 for g in result["gaps"])


def test_undated_prose_does_not_become_an_event():
    result = re_.build_timeline.invoke(
        {"correspondence": "Some day last month the manager said something.\n"
                           "2026-04-02 - Manager to Tenant: Please keep noise down."})
    assert result["event_count"] == 1


def test_each_party_position_is_attributed_and_not_weighed():
    result = re_.positions_extractor.invoke({"sample_name": "dispute_hoa_fence"})
    assert result["party_count"] >= 2
    assert "without weighing them" in result["note"]
    assert any(p["request_count"] > 0 for p in result["positions"])


def test_notice_dates_are_labelled_placeholders_every_time():
    result = re_.notice_deadlines.invoke({"sample_name": "dispute_deposit"})
    assert result["date_count"] > 0
    for entry in result["computed_dates"]:
        assert entry["label"] == "placeholder — confirm local law"
    assert "not the notice periods of any jurisdiction" in result["disclaimer"]


def test_the_date_arithmetic_is_checkable():
    result = re_.notice_deadlines.invoke({"sample_name": "dispute_deposit"})
    entry = next(e for e in result["computed_dates"] if e["period"] == "return_or_itemize_days")
    anchor = dt.date.fromisoformat(entry["measured_from"])
    assert dt.date.fromisoformat(entry["date"]) == anchor + dt.timedelta(days=21)


def test_an_unknown_dispute_type_is_refused_with_the_known_ones():
    result = re_.notice_deadlines.invoke({"dispute_type": "spite_fence"})
    assert "error" in result
    assert "deposit" in result["known"]


def test_threatening_and_discriminatory_wording_forces_counsel():
    flags = re_.tone_flags.invoke({"sample_name": "dispute_noise_escalating"})
    assert flags["threat_count"] > 0
    assert flags["discrimination_count"] > 0
    assert flags["escalation_triggered"] is True
    assert flags["recommended_level"] == "ESCALATE_TO_COUNSEL"

    outcome = re_.dispute_outcome.invoke({"sample_name": "dispute_noise_escalating"})
    assert outcome["level"] == "ESCALATE_TO_COUNSEL"


def test_ordinary_legal_escalation_language_does_not_force_counsel():
    """Mentioning a lawyer is a normal thing to do and is not a threat."""
    flags = re_.tone_flags.invoke({"sample_name": "dispute_deposit"})
    assert "escalation" in flags["flag_kinds"]
    assert flags["threat_count"] == 0
    assert flags["discrimination_count"] == 0
    assert flags["escalation_triggered"] is False

    outcome = re_.dispute_outcome.invoke({"sample_name": "dispute_deposit"})
    assert outcome["level"] == "MEDIATION_CANDIDATE"


def test_eviction_always_goes_to_counsel_whatever_the_tone():
    outcome = re_.dispute_outcome.invoke(
        {"dispute_type": "eviction_related", "sample_name": "dispute_hoa_fence"})
    assert outcome["level"] == "ESCALATE_TO_COUNSEL"
    assert any("eviction_related" in r for r in outcome["escalation_reasons"])


def test_a_thin_record_asks_for_more_rather_than_summarising():
    outcome = re_.dispute_outcome.invoke({"dispute_type": "noise"})
    assert outcome["level"] == "NEEDS_MORE_INFORMATION"


def test_the_outcome_says_courts_decide_evictions():
    outcome = re_.dispute_outcome.invoke({"sample_name": "dispute_hoa_fence"})
    assert "decide evictions" in outcome["note"]


def test_tone_flags_report_context_not_just_a_verdict():
    flags = re_.tone_flags.invoke({"sample_name": "dispute_noise_escalating"})
    for entries in flags["flags"].values():
        for entry in entries:
            assert entry["context"]
    assert "not findings" in flags["interpretation_note"].lower()


def test_matched_clauses_carry_a_page_reference():
    result = re_.match_clauses.invoke({"sample_name": "dispute_hoa_fence"})
    assert result["clause_count"] > 0
    for clause in result["clauses"]:
        assert clause["page"] >= 1
        assert clause["quote"]
        assert clause["matched_terms"]
