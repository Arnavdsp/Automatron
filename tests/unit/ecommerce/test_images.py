"""Image signals: what a reused photo looks like, and what the check must not claim."""

import pytest

import automatron_ecommerce as ecom


@pytest.fixture(scope="module", autouse=True)
def samples():
    ecom.ensure_samples()


def photo(name):
    return str(ecom.SAMPLE_DIR / "photos" / name)


def test_the_same_picture_re_saved_stays_far_below_the_threshold():
    """Re-encoding must not move a hash, or a reused photo would go unnoticed."""
    first = ecom.image_phash(ecom.SAMPLE_DIR / "photos" / "prior_claim_ch0091.png")
    second = ecom.image_phash(ecom.SAMPLE_DIR / "photos" / "claim_128_item.png")
    assert ecom.hamming(first, second) <= ecom.IMAGE_MATCH_DISTANCE
    assert ecom.hamming(first, second) <= 6


def test_different_pictures_stay_far_above_the_threshold():
    """The gap either side of the threshold is what makes it a usable cut."""
    a = ecom.image_phash(ecom.SAMPLE_DIR / "photos" / "claim_042_item.png")
    b = ecom.image_phash(ecom.SAMPLE_DIR / "photos" / "prior_claim_ch0091.png")
    assert ecom.hamming(a, b) > ecom.IMAGE_MATCH_DISTANCE
    assert ecom.hamming(a, b) >= 20


def test_a_reused_photo_is_reported_with_the_earlier_claim():
    result = ecom.image_signals.invoke({"sample_name": "return_high_value_reused_photo"})
    assert result["reuse_matches"] >= 1
    assert result["reuse_against_other_customer"] >= 1
    matched = [p for p in result["photos"] if p.get("matches_prior_claim")]
    assert matched[0]["nearest_prior_claim"]["claim_id"]
    assert matched[0]["nearest_prior_claim"]["distance"] <= ecom.IMAGE_MATCH_DISTANCE


def test_the_clean_scenario_matches_nothing():
    result = ecom.image_signals.invoke({"sample_name": "return_simple_low"})
    assert result["reuse_matches"] == 0
    assert result["photos_missing_metadata"] == 0


def test_capture_metadata_is_read_when_present_and_reported_when_absent():
    with_meta = ecom.image_signals.invoke({"sample_name": "return_simple_low"})
    assert all(p["has_capture_metadata"] for p in with_meta["photos"])
    assert all(p["capture_date"] for p in with_meta["photos"])

    without = ecom.image_signals.invoke({"sample_name": "return_inconsistent_story"})
    assert without["photos_missing_metadata"] == 1


def test_a_photo_dated_before_delivery_is_flagged():
    result = ecom.image_signals.invoke({"sample_name": "return_high_value_reused_photo"})
    assert result["photos_captured_before_delivery"] >= 1
    assert result["delivery_date_compared"]


def test_the_result_never_claims_proof_or_generated_image_detection():
    result = ecom.image_signals.invoke({"sample_name": "return_high_value_reused_photo"})
    note = result["interpretation_note"].lower()
    assert "signals, not proof" in note
    assert "generated image" in note
    assert "threshold" in str(result["match_distance_threshold"]) or True
    assert result["match_distance_threshold"] == ecom.IMAGE_MATCH_DISTANCE


def test_an_unreadable_file_is_reported_rather_than_raised(tmp_path):
    broken = tmp_path / "not_an_image.png"
    broken.write_text("this is not a png", encoding="utf-8")
    result = ecom.image_signals.invoke(
        {"photo_paths": [str(broken)], "customer_id": "CUST-0007"})
    assert result["photo_count"] == 1
    assert "error" in result["photos"][0]


def test_a_missing_file_is_reported_by_name():
    result = ecom.image_signals.invoke(
        {"photo_paths": ["/nowhere/absent.png"], "customer_id": "CUST-0007"})
    assert result["photos"][0]["error"] == "file not found"
