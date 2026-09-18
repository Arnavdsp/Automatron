"""Reading a diligence packet: what gets found, how it is graded, and what is not claimed."""

import pytest

import automatron_realestate as re_


@pytest.fixture(scope="module", autouse=True)
def samples():
    re_.ensure_samples()


def test_each_document_is_identified_by_its_own_wording():
    result = re_.classify_documents.invoke({"sample_name": "packet_purchase"})
    kinds = {d["document"]: d["document_type"] for d in result["documents"]}
    assert kinds == {
        "title_commitment": "title_commitment", "survey_notes": "survey_notes",
        "ccr": "ccr", "inspection_report": "inspection_report",
        "environmental_summary": "environmental_summary"}


def test_a_complete_packet_reports_nothing_missing():
    """The expected-document names must match the classifier's, or a supplied
    document is announced as missing."""
    result = re_.classify_documents.invoke({"sample_name": "packet_purchase"})
    assert result["missing_documents"] == []


def test_a_genuinely_absent_document_is_named():
    result = re_.classify_documents.invoke({"sample_name": "packet_lease"})
    assert "inspection_report" in result["missing_documents"]


def test_every_clause_cites_a_document_and_a_page():
    result = re_.extract_clauses.invoke({"sample_name": "packet_purchase"})
    assert result["clause_count"] > 0
    for clause in result["clauses"]:
        assert clause["page"] >= 1
        assert clause["document"]
        assert clause["excerpt"]


def test_the_four_findings_the_packet_was_written_around_are_all_found():
    result = re_.extract_clauses.invoke({"sample_name": "packet_purchase"})
    found = {(c["category"], c["document"]) for c in result["clauses"]}
    assert ("lien_encumbrance", "title_commitment") in found      # unreleased mortgage
    assert ("easement", "title_commitment") in found              # rear utility easement
    assert ("encroachment", "survey_notes") in found              # fence over the line
    assert ("restriction_ccr", "ccr") in found                    # accessory structures


def test_a_heading_does_not_become_a_finding():
    """A title page carries the document's subject words and nothing else."""
    result = re_.extract_clauses.invoke({"document_name": "environmental_summary"})
    pages = {c["page"] for c in result["clauses"]}
    assert 1 not in pages, "the letterhead page produced a finding"
    assert result["clause_count"] >= 1


def test_the_survey_exception_is_not_mistaken_for_an_encroachment():
    """Schedule B's general exception mentions encroachment but is a title exception."""
    result = re_.extract_clauses.invoke({"document_name": "title_commitment"})
    categories = {(c["page"], c["category"]) for c in result["clauses"]}
    assert (4, "title_exception") in categories
    assert (4, "encroachment") not in categories


def test_one_finding_per_category_per_page():
    """Several sentences about the same thing on one page are one item to a reader."""
    result = re_.extract_clauses.invoke({"sample_name": "packet_purchase"})
    keys = [(c["document"], c["page"], c["category"]) for c in result["clauses"]]
    assert len(keys) == len(set(keys))
    assert any(c.get("occurrences", 1) > 1 for c in result["clauses"])


def test_clauses_touching_the_intended_use_are_flagged():
    result = re_.cross_check_intended_use.invoke({"sample_name": "packet_purchase"})
    assert result["flagged_count"] > 0
    categories = {f["category"] for f in result["flagged"]}
    assert "easement" in categories
    assert all(f["why"] for f in result["flagged"])


def test_an_overlap_is_not_stated_as_a_prohibition():
    result = re_.cross_check_intended_use.invoke({"sample_name": "packet_purchase"})
    note = result["note"].lower()
    assert "does not mean the intended use is prohibited" in note
    assert "nothing here says whether it is allowed" in note


def test_the_rear_easement_is_raised_to_high_because_of_the_intended_use():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    easements = [f for f in result["findings"] if f["category"] == "easement"]
    assert easements
    assert all(f["severity"] == "high" for f in easements)
    assert any("overlaps" in " ".join(f["escalation_reasons"]).lower() for f in easements)


def test_the_unreleased_mortgage_is_high_and_says_why_it_moved():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    lien = next(f for f in result["findings"] if f["category"] == "lien_encumbrance")
    assert lien["severity"] == "high"
    assert any("unreleased" in r.lower() for r in lien["escalation_reasons"])


def test_a_minor_inspection_item_stays_low():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    items = [f for f in result["findings"] if f["category"] == "inspection_defect"]
    assert items
    assert any(f["severity"] in {"low", "medium"} for f in items)


def test_every_finding_carries_a_question_and_a_source():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    for finding in result["findings"]:
        assert finding["question_for_attorney"]
        assert finding["why_it_may_matter"]
        assert finding["document"]


def test_the_level_reflects_the_highest_severity_present():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    assert result["level"] == "HIGH_SEVERITY_FLAGS"
    assert result["severity_counts"]["high"] > 0


def test_the_rubric_says_it_is_not_legal_advice():
    result = re_.severity_rubric.invoke({"sample_name": "packet_purchase"})
    assert "not legal advice" in result["disclaimer"].lower()


def test_the_question_list_is_a_draft_grouped_by_severity():
    result = re_.draft_attorney_questions.invoke({"sample_name": "packet_purchase"})
    assert result["is_draft"] is True
    assert result["question_count"] > 0
    assert "not conclusions" in result["body"].lower()
    severities = [q["severity"] for q in result["questions"]]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1,
                                                          "low": 2, "needs_info": 3}[s])
