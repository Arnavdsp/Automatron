"""Personal data must be masked at the tool boundary, not on the way out."""

import json
import re

import pytest

import automatron_ecommerce as ecom


@pytest.fixture(scope="module", autouse=True)
def samples():
    ecom.ensure_samples()


def raw_rows(name):
    path = ecom.SAMPLE_DIR / name
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if not line.startswith("#")]
    import csv
    return list(csv.DictReader(lines))


def test_masking_helpers_keep_only_what_identifies_a_record():
    assert ecom.mask_email("sample.person7@example.invalid") == "s***@example.invalid"
    assert ecom.mask_phone("+15551000959") == "***59"
    assert ecom.mask_card("4111111111111234") == "**** **** **** 1234"
    assert ecom.mask_card("1234") == "**** **** **** 1234"
    assert ecom.mask_address("12 Sample Street, Testville, US") == \
        "[street withheld], Testville, US"


def test_masking_handles_values_that_are_not_there():
    assert ecom.mask_email("") == ""
    assert ecom.mask_email("not-an-address") == "not-an-address"
    assert ecom.mask_phone("") == "***"
    assert ecom.mask_card("") == "****"
    assert ecom.mask_address("") == "[address withheld]"


def test_no_full_email_or_phone_survives_a_customer_lookup():
    """The sample file holds full contact details; the tool output must not."""
    row = raw_rows("customers.csv")[6]
    result = ecom.customer_history.invoke({"customer_id": row["customer_id"]})
    blob = json.dumps(result)
    assert row["email"] not in blob
    assert row["phone"] not in blob
    assert result["email"].startswith(row["email"][0] + "***@")


def test_no_street_address_survives_an_order_lookup():
    row = next(r for r in raw_rows("orders.csv") if r["order_id"] == "ORD-100042")
    result = ecom.order_lookup.invoke({"order_id": "ORD-100042"})
    blob = json.dumps(result)
    assert row["shipping_address"] not in blob
    assert "[street withheld]" in result["shipping_address"]


def test_gathering_chargeback_evidence_masks_the_same_fields():
    row = next(r for r in raw_rows("orders.csv") if r["order_id"] == "ORD-100155")
    result = ecom.gather_evidence.invoke({"order_id": "ORD-100155"})
    blob = json.dumps(result)
    assert row["shipping_address"] not in blob
    assert re.search(r"\b\d{9,}\b", result["card_last4"]) is None


@pytest.mark.parametrize("sample", ["return_simple_low", "return_high_value_reused_photo",
                                    "return_inconsistent_story"])
def test_no_claim_workflow_tool_leaks_contact_details(sample):
    """Sweep every dispute tool's output against every contact detail on file."""
    outputs = json.dumps([
        ecom.order_lookup.invoke({"sample_name": sample}),
        ecom.customer_history.invoke({"sample_name": sample}),
        ecom.policy_check.invoke({"sample_name": sample}),
        ecom.image_signals.invoke({"sample_name": sample}),
        ecom.transcript_signals.invoke({"sample_name": sample}),
        ecom.risk_score.invoke({"sample_name": sample}),
        ecom.route_claim.invoke({"sample_name": sample}),
    ])
    for row in raw_rows("customers.csv"):
        assert row["email"] not in outputs, f"{row['customer_id']} email leaked"
        assert row["phone"] not in outputs, f"{row['customer_id']} phone leaked"
    for row in raw_rows("orders.csv"):
        assert row["shipping_address"] not in outputs, f"{row['order_id']} address leaked"
