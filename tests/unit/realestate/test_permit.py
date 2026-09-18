"""Dimensional standards: the arithmetic, and the edge where equal means compliant."""

import pytest

import automatron_realestate as re_


@pytest.fixture(scope="module", autouse=True)
def samples():
    re_.ensure_samples()


def test_floor_area_ratio_and_lot_coverage_are_computed_from_stated_inputs():
    result = re_.check_dimensional_standards.invoke({"sample_name": "project_r1_compliant"})
    computed = result["computed"]
    assert computed["floor_area_ratio"] == pytest.approx(3600 / 8000)
    assert computed["lot_coverage_pct"] == pytest.approx(2400 / 8000 * 100)
    assert computed["floor_area_ratio_inputs"]["gross_floor_area_sqft"] == 3600
    assert computed["lot_coverage_inputs"]["building_footprint_sqft"] == 2400


def test_a_value_exactly_on_its_limit_passes():
    """Codes say 'not less than' and 'not more than', so equality is compliance.

    The sample project sits exactly on several limits at once; an off-by-one
    comparison would fail a project that complies.
    """
    result = re_.check_dimensional_standards.invoke(
        {"sample_name": "project_r1_setback_violation"})
    at_limit = [r for r in result["rules"] if r.get("at_limit")]
    assert len(at_limit) >= 4
    assert all(r["result"] == "PASS" for r in at_limit)


def test_only_the_genuine_violation_fails():
    result = re_.check_dimensional_standards.invoke(
        {"sample_name": "project_r1_setback_violation"})
    assert result["fail_count"] == 1
    assert result["failed"][0]["standard"] == "min_side_setback_ft"
    assert result["failed"][0]["section"] == "SC-21.21"


@pytest.mark.parametrize("comparison,required,proposed,expected", [
    ("at_least", 7, 7, "PASS"),
    ("at_least", 7, 6.999, "FAIL"),
    ("at_least", 7, 7.001, "PASS"),
    ("at_most", 30, 30, "PASS"),
    ("at_most", 30, 30.001, "FAIL"),
    ("at_most", 30, 29.999, "PASS"),
])
def test_both_comparison_directions_at_their_boundary(comparison, required, proposed, expected):
    field = "side_setback_ft" if comparison == "at_least" else "height_ft"
    project = {**re_.PROJECTS["project_r1_compliant"], field: proposed}
    rules = re_.load_zoning()["districts"]["R-1"]["standards"]
    standard = "min_side_setback_ft" if comparison == "at_least" else "max_height_ft"
    # Confirm the fixture is actually testing the boundary the parameters describe.
    assert rules[standard]["comparison"] == comparison
    assert rules[standard]["value"] == required

    result = re_.check_dimensional_standards.invoke({"project": project})
    row = next(r for r in result["rules"] if r["standard"] == standard)
    assert row["result"] == expected


def test_every_row_reports_required_proposed_and_its_section():
    result = re_.check_dimensional_standards.invoke({"sample_name": "project_c1_conditional_use"})
    assert result["rule_count"] == 10
    for row in result["rules"]:
        assert row["section"].startswith("SC-")
        assert row["required"] is not None
        assert row["detail"]


def test_a_missing_field_gives_needs_info_not_a_silent_zero():
    project = {k: v for k, v in re_.PROJECTS["project_r1_compliant"].items()
               if k != "height_ft"}
    result = re_.check_dimensional_standards.invoke({"project": project})
    row = next(r for r in result["rules"] if r["standard"] == "max_height_ft")
    assert row["result"] == "NEEDS_INFO"
    assert row["proposed"] is None


def test_the_four_outcome_levels_are_all_reachable():
    assert re_.prescreen_outcome.invoke(
        {"sample_name": "project_r1_compliant"})["level"] == "READY_FOR_EXAMINER"
    assert re_.prescreen_outcome.invoke(
        {"sample_name": "project_r1_setback_violation"})["level"] == "CORRECTIONS_LIKELY"
    assert re_.prescreen_outcome.invoke(
        {"sample_name": "project_c1_conditional_use"})["level"] == "HEARING_LIKELY"
    assert re_.prescreen_outcome.invoke(
        {"project": {"zone_district": "R-1", "use": "single_family_dwelling"}}
    )["level"] == "INCOMPLETE_SUBMISSION"


def test_a_use_not_permitted_in_the_district_needs_corrections():
    result = re_.prescreen_outcome.invoke(
        {"project": {**re_.PROJECTS["project_r1_compliant"], "use": "retail"}})
    assert result["level"] == "CORRECTIONS_LIKELY"
    assert result["use_status"] == "not_permitted"


def test_an_unlisted_use_is_not_treated_as_a_refusal():
    result = re_.use_permission.invoke({"use": "helipad", "zone_district": "R-1"})
    assert result["status"] == "unlisted"
    assert "similar to a listed one" in result["note"]


def test_a_conditional_use_says_a_hearing_is_normal():
    result = re_.use_permission.invoke({"use": "restaurant", "zone_district": "C-1"})
    assert result["status"] == "conditional"
    assert "hearing" in result["note"].lower()


def test_validation_rejects_a_footprint_larger_than_the_lot():
    result = re_.validate_project.invoke(
        {"project": {**re_.PROJECTS["project_r1_compliant"],
                     "building_footprint_sqft": 9000}})
    assert result["complete"] is False
    assert any("exceeds the lot area" in p for p in result["problems"])


def test_a_plan_that_disagrees_with_the_form_reports_both_numbers():
    result = re_.extract_plan_values.invoke(
        {"sample_name": "project_r1_setback_violation"})
    conflict = next(c for c in result["conflicts"] if c["field"] == "side_setback_ft")
    assert conflict["on_form"] == 5.0
    assert conflict["on_plan"] == 6.0
    assert "examiner decides" in conflict["note"]


def test_the_outcome_never_claims_a_permit_decision():
    result = re_.prescreen_outcome.invoke({"sample_name": "project_r1_compliant"})
    assert "does not approve, deny" in result["note"]
