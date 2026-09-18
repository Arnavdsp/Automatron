"""The return window, the weighted score, and the routing the two of them produce."""

import pytest

import automatron_ecommerce as ecom


@pytest.fixture(scope="module", autouse=True)
def samples():
    ecom.ensure_samples()


def test_the_three_scenarios_reach_three_different_levels():
    """Each bundled claim exists to demonstrate one routing path."""
    assert ecom.route_claim.invoke(
        {"sample_name": "return_simple_low"})["level"] == "FAST_TRACK_ELIGIBLE"
    assert ecom.route_claim.invoke(
        {"sample_name": "return_inconsistent_story"})["level"] == "SPECIALIST_REVIEW"
    assert ecom.route_claim.invoke(
        {"sample_name": "return_high_value_reused_photo"})["level"] == "HIGH_RISK_REVIEW"


def test_the_clean_scenario_fires_no_risk_factors_at_all():
    """A false positive here would make the fast-track demonstration meaningless."""
    scored = ecom.risk_score.invoke({"sample_name": "return_simple_low"})
    assert scored["factors"] == []
    assert scored["score"] == 0


def test_every_factor_reports_its_weight_and_an_innocent_explanation():
    scored = ecom.risk_score.invoke({"sample_name": "return_high_value_reused_photo"})
    assert scored["factors"], "the high-risk scenario must fire factors"
    for factor in scored["factors"]:
        assert factor["weight"] > 0
        assert factor["observation"]
        assert factor["innocent_explanation"], f"{factor['factor']} has no counter-reading"


def test_the_score_is_capped_at_its_stated_maximum():
    scored = ecom.risk_score.invoke({"sample_name": "return_high_value_reused_photo"})
    assert scored["score"] <= scored["max_score"] == 100
    assert sum(f["weight"] for f in scored["factors"]) >= scored["score"]


def test_routing_takes_the_value_and_the_score_together():
    """A cheap but suspicious claim and an expensive clean one both leave fast track."""
    cheap_clean = ecom.route_claim.invoke({"order_value_usd": 20.0, "score": 0.0})
    assert cheap_clean["level"] == "FAST_TRACK_ELIGIBLE"

    expensive_clean = ecom.route_claim.invoke({"order_value_usd": 900.0, "score": 0.0})
    assert expensive_clean["level"] == "SPECIALIST_REVIEW"

    cheap_risky = ecom.route_claim.invoke({"order_value_usd": 20.0, "score": 45.0})
    assert cheap_risky["level"] == "SPECIALIST_REVIEW"

    anything_high = ecom.route_claim.invoke({"order_value_usd": 20.0, "score": 70.0})
    assert anything_high["level"] == "HIGH_RISK_REVIEW"


def test_routing_measures_what_it_was_not_given():
    """Demo mode calls this with no numbers, so it must not invent them."""
    routed = ecom.route_claim.invoke({"sample_name": "return_inconsistent_story"})
    assert set(routed["measured_here"]) == {"order value", "risk score"}
    assert routed["risk_score"] > 0


def test_the_window_comes_from_the_category_not_the_default():
    """Apparel runs longer than the standard window and electronics shorter."""
    apparel = ecom.policy_check.invoke({"sample_name": "return_simple_low"})
    assert apparel["category"] == "apparel"
    assert apparel["window_days"] == 60

    electronics = ecom.policy_check.invoke({"sample_name": "return_inconsistent_story"})
    assert electronics["category"] == "electronics"
    assert electronics["window_days"] == 15


def test_a_not_received_claim_is_measured_from_the_order_not_the_delivery():
    policy = ecom.load_return_policy()
    assert "not_received" in policy["window_from_order"]
    result = ecom.policy_check.invoke(
        {"order_id": "ORD-100155", "claim_type": "not_received"})
    order = ecom.order_lookup.invoke({"order_id": "ORD-100155"})
    assert result["window_measured_from"] == order["order_date"]


def test_an_excluded_category_refuses_the_claim_types_it_excludes():
    rows = [r for r in ecom._read_rows("orders.csv") if r["category"] == "gift_card"]
    assert rows, "the sample set needs a gift card order for this check"
    refused = ecom.policy_check.invoke(
        {"order_id": rows[0]["order_id"], "claim_type": "changed_mind"})
    assert refused["category_excluded"] is True
    assert any("gift card" in p.lower() for p in refused["policy_problems"])

    allowed = ecom.policy_check.invoke(
        {"order_id": rows[0]["order_id"], "claim_type": "not_received"})
    assert not any("not returnable" in p for p in allowed["policy_problems"])


def test_missing_required_evidence_is_named():
    result = ecom.policy_check.invoke({"sample_name": "return_inconsistent_story"})
    assert "photo_of_item" in result["missing_required_evidence"]
    assert result["meets_policy"] is False


def test_an_unknown_claim_type_is_refused_with_the_known_ones():
    result = ecom.policy_check.invoke(
        {"order_id": "ORD-100042", "claim_type": "teleportation_failure"})
    assert "error" in result and "changed_mind" in result["known"]


def test_the_transcript_check_names_both_sides_of_a_mismatch():
    result = ecom.transcript_signals.invoke({"sample_name": "return_inconsistent_story"})
    assert result["inconsistency_count"] >= 1
    for entry in result["inconsistencies"]:
        assert entry["on_order"] and entry["in_conversation"]
    assert "not a conclusion" in result["interpretation_note"]


def test_urgency_alone_is_not_treated_as_an_inconsistency():
    result = ecom.transcript_signals.invoke({"sample_name": "return_high_value_reused_photo"})
    assert result["pressure_phrase_count"] > 0
    assert result["inconsistency_count"] == 0
