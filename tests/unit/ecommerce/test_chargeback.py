"""The representment packet: completeness, banding, deadlines and the draft."""

import pytest

import automatron_ecommerce as ecom


@pytest.fixture(scope="module", autouse=True)
def samples():
    ecom.ensure_samples()


def test_the_two_sample_disputes_land_in_different_bands():
    strong = ecom.win_likelihood_band.invoke({"sample_name": "dispute_not_received_strong"})
    weak = ecom.win_likelihood_band.invoke({"sample_name": "dispute_fraud_weak"})
    assert strong["level"] == "STRONG_PACKET"
    assert weak["level"] == "ACCEPT_LIABILITY_SUGGESTED"
    assert strong["completeness"] > weak["completeness"]


def test_completeness_is_a_share_of_available_weight():
    scored = ecom.completeness_score.invoke({"sample_name": "dispute_not_received_strong"})
    assert scored["available_weight"] > 0
    assert scored["completeness"] == pytest.approx(
        scored["covered_weight"] / scored["available_weight"], abs=1e-6)
    assert 0.0 <= scored["completeness"] <= 1.0


def test_missing_evidence_is_named_so_it_can_be_chased():
    scored = ecom.completeness_score.invoke({"sample_name": "dispute_fraud_weak"})
    assert scored["missing_required_count"] > 0
    for item in scored["missing_required"]:
        assert item["label"] and item["key"] and item["group"] == "required"


def test_missing_required_evidence_holds_a_packet_below_strong():
    """Otherwise a pile of helpful extras could dress up a packet with a hole in it."""
    result = ecom.win_likelihood_band.invoke(
        {"reason_category": "not_received", "completeness": 0.95,
         "signals": {"missing_required_count": 2}})
    assert result["band"] == "MEDIUM"
    assert any("held below strong" in r for r in result["reasons"])


def test_a_stated_window_is_used_and_an_absent_one_is_flagged():
    stated = ecom.response_deadline.invoke({"sample_name": "dispute_not_received_strong"})
    assert stated["response_window_days"] == 20
    assert stated["window_was_assumed"] is False

    assumed = ecom.response_deadline.invoke({"sample_name": "dispute_fraud_weak"})
    assert assumed["window_was_assumed"] is True
    assert assumed["response_window_days"] == 14
    assert "confirm" in assumed["confirm_note"].lower()


def test_the_deadline_arithmetic_is_checkable():
    import datetime as dt
    result = ecom.response_deadline.invoke(
        {"notice_date": "2026-04-01", "response_window_days": 10})
    assert result["due_date"] == "2026-04-11"
    expected = (dt.date(2026, 4, 11) - ecom.TODAY).days
    assert result["days_remaining"] == expected


def test_an_overdue_deadline_says_so():
    result = ecom.response_deadline.invoke(
        {"notice_date": "2026-01-01", "response_window_days": 5})
    assert result["overdue"] is True
    assert result["days_remaining"] < 0


def test_the_checklist_is_generic_and_says_the_processor_decides():
    result = ecom.evidence_checklist.invoke({"reason_category": "fraud_unauthorized"})
    assert result["required_count"] == 5
    assert "processor" in result["disclaimer"].lower()


def test_an_unknown_reason_category_is_refused_with_the_known_ones():
    result = ecom.evidence_checklist.invoke({"reason_category": "the_dog_ate_it"})
    assert "error" in result
    assert "not_received" in result["known"]


def test_the_rebuttal_is_a_draft_that_cites_exhibits_and_claims_nothing_sent():
    draft = ecom.draft_rebuttal.invoke({"sample_name": "dispute_not_received_strong"})
    assert draft["is_draft"] is True
    assert draft["exhibit_count"] > 0
    assert all(e["exhibit"].startswith("E") for e in draft["exhibits"])
    body = draft["body"].lower()
    assert "[draft" in body
    assert "submitted to" not in body
    assert "does not submit" in draft["note"].lower()


def test_a_weak_packet_draft_still_names_what_is_missing():
    draft = ecom.draft_rebuttal.invoke({"sample_name": "dispute_fraud_weak"})
    assert draft["missing_required"]
    assert all(m["label"] for m in draft["missing_required"])


def test_the_band_is_labelled_a_heuristic_not_a_prediction():
    result = ecom.win_likelihood_band.invoke({"sample_name": "dispute_fraud_weak"})
    assert "not a prediction" in result["note"].lower()
