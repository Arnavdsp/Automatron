"""Seller appeals: invoice extraction, consistency against sales, and letter structure."""

import pytest

import automatron_ecommerce as ecom


@pytest.fixture(scope="module", autouse=True)
def samples():
    ecom.ensure_samples()


def test_invoice_header_fields_are_extracted_not_left_empty():
    """These anchor on a line start; without multiline matching they all come back blank."""
    result = ecom.extract_invoice_fields.invoke(
        {"sample_name": "appeal_strong_authorized_reseller"})
    invoice = result["invoices"][0]
    assert invoice["supplier"] == "Harbour Distribution Ltd (fictional)"
    assert invoice["invoice_number"] == "HD-2026-4471"
    assert invoice["invoice_date"] == "2026-01-06"
    assert invoice["stated_total"] == 8300.00
    assert invoice["missing_fields"] == []


def test_line_items_are_parsed_with_their_quantities():
    result = ecom.extract_invoice_fields.invoke(
        {"sample_name": "appeal_strong_authorized_reseller"})
    items = result["invoices"][0]["line_items"]
    assert len(items) == 1
    assert items[0]["sku"] == "NL-HP-300"
    assert items[0]["quantity"] == 200
    assert items[0]["line_total"] == 8300.00


def test_a_field_that_cannot_be_found_is_reported_not_guessed(tmp_path):
    thin = tmp_path / "thin.txt"
    thin.write_text("Supplier: Someone\n\nNo other fields here.\n", encoding="utf-8")
    result = ecom.extract_invoice_fields.invoke({"document_paths": [str(thin)]})
    invoice = result["invoices"][0]
    assert invoice["supplier"] == "Someone"
    assert set(invoice["missing_fields"]) == {"invoice_number", "invoice_date", "total"}


def test_the_supported_appeal_shows_no_discrepancies():
    result = ecom.invoice_consistency.invoke(
        {"sample_name": "appeal_strong_authorized_reseller"})
    assert result["consistent"] is True
    assert result["finding_count"] == 0
    assert result["check_count"] > 0


def test_the_mismatched_appeal_shows_each_discrepancy_separately():
    result = ecom.invoice_consistency.invoke({"sample_name": "appeal_invoice_mismatch"})
    kinds = {f["kind"] for f in result["findings"]}
    assert "units_sold_exceed_units_invoiced" in kinds
    assert "invoice_dated_after_first_sale" in kinds
    assert "supplier_not_authorized" in kinds


def test_a_quantity_shortfall_names_both_numbers():
    result = ecom.invoice_consistency.invoke({"sample_name": "appeal_invoice_mismatch"})
    shortfall = next(f for f in result["findings"]
                     if f["kind"] == "units_sold_exceed_units_invoiced")
    assert shortfall["units_sold"] == 640
    assert shortfall["units_invoiced"] == 120
    assert shortfall["shortfall"] == 520
    assert shortfall["question"]


def test_line_arithmetic_is_checked(tmp_path):
    bad = tmp_path / "bad_maths.txt"
    bad.write_text(
        "SUPPLIER INVOICE\n"
        "Supplier: Harbour Distribution Ltd (fictional)\n"
        "Invoice Number: X-1\n"
        "Invoice Date: 2026-01-06\n"
        "Bill To: Someone\n\n"
        "SKU         Description                 Qty      Unit Price     Line Total\n"
        "NL-HP-300   Northlight headphones 300   10       5.00           999.00\n\n"
        "Total: 999.00 USD\n",
        encoding="utf-8")
    extracted = ecom.extract_invoice_fields.invoke({"document_paths": [str(bad)]})
    result = ecom.invoice_consistency.invoke(
        {"invoices": extracted["invoices"], "seller_id": "SEL-2001"})
    mismatch = next(f for f in result["findings"] if f["kind"] == "line_arithmetic_mismatch")
    assert mismatch["expected"] == 50.0
    assert mismatch["stated"] == 999.00


def test_every_finding_is_framed_as_a_question_not_a_conclusion():
    result = ecom.invoice_consistency.invoke({"sample_name": "appeal_invoice_mismatch"})
    assert "question to put to the seller" in result["note"]
    assert "conclusion" in result["note"]


def test_a_complete_appeal_letter_is_recognised():
    result = ecom.appeal_quality.invoke({"sample_name": "appeal_strong_authorized_reseller"})
    assert result["level"] == "APPEAL_WELL_SUPPORTED"
    assert result["sections_missing"] == []
    assert "HD-2026-4471" in result["identifiers_cited"]


def test_a_deflecting_letter_with_no_structure_is_marked_weak():
    result = ecom.appeal_quality.invoke({"sample_name": "appeal_invoice_mismatch"})
    assert result["level"] == "APPEAL_WEAK"
    assert "root_cause" in result["sections_missing"]
    assert result["deflection_phrases"]


def test_the_letter_check_says_it_is_only_structural():
    result = ecom.appeal_quality.invoke({"sample_name": "appeal_invoice_mismatch"})
    assert "read the letter" in result["note"]


def test_the_timeline_distinguishes_repeat_complaints():
    once = ecom.violation_timeline.invoke({"seller_id": "SEL-2001"})
    repeatedly = ecom.violation_timeline.invoke({"seller_id": "SEL-2044"})
    assert once["repeat_complaints"] is False
    assert repeatedly["repeat_complaints"] is True
    assert repeatedly["enforcement_count"] >= 2


def test_an_unknown_seller_is_reported_rather_than_raised():
    assert "error" in ecom.seller_profile.invoke({"seller_id": "SEL-9999"})
