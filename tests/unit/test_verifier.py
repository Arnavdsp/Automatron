"""The verifier runs no model: it checks a brief against what the tools actually returned."""

import pytest

import automatron_core as core


def completed_with(data=None, excerpt="", summary=""):
    return {
        "s1": {
            "step_id": "s1",
            "agent": "analyst",
            "status": "ok",
            "summary": summary,
            "data": data if data is not None else {"pc": "3.2e-04", "miss_m": 412},
            "evidence": [
                {
                    "id": "T1",
                    "kind": "tool",
                    "label": "compute_pc_2d",
                    "locator": "call-1",
                    "excerpt": excerpt,
                }
            ],
        }
    }


def brief_with(**overrides):
    base = {
        "title": "Conjunction triage",
        "sector": "space",
        "workflow_id": "space.conjunction_triage",
        "summary": "A close approach needs review.",
        "recommendation": "Proposed: maneuver planning — requires operator approval.",
        "recommendation_level": "RED",
        "confidence": "medium",
        "confidence_reason": "One screening.",
        "key_findings": [
            {"text": "Pc is 3.2e-04 at TCA.", "severity": "high", "evidence_ids": ["T1"]}
        ],
        "quantitative_results": {"Pc (latest)": "3.2e-04", "Miss distance": "412 m"},
        "options": [
            {"name": "Monitor", "description": "Wait for the next message."},
            {"name": "Plan a maneuver", "description": "Prepare an avoidance option."},
        ],
        "reviewer_must_decide": "Whether to commit propellant.",
        "evidence": [{"id": "T1", "kind": "tool", "label": "compute_pc_2d"}],
        "disclaimer": "Decision support only.",
    }
    base.update(overrides)
    return base


class TestNumberGrounding:
    def test_a_clean_brief_passes(self):
        assert core.verify_brief(brief_with(), completed_with()) == []

    def test_an_invented_number_is_caught(self):
        brief = brief_with(
            key_findings=[
                {"text": "Pc is 9.9e-02 at TCA.", "severity": "high", "evidence_ids": ["T1"]}
            ]
        )
        issues = core.verify_brief(brief, completed_with())
        assert any("no tool output" in issue for issue in issues)

    def test_formatting_differences_do_not_count_as_invented(self):
        # 412 in the tool output, "412.0 m" and "1,412" style formatting in the brief.
        brief = brief_with(quantitative_results={"Miss distance": "412.0 m"})
        assert core.verify_brief(brief, completed_with()) == []

    def test_years_are_exempt(self):
        brief = brief_with(
            key_findings=[
                {
                    "text": "The 2026 policy applies; Pc is 3.2e-04.",
                    "severity": "info",
                    "evidence_ids": ["T1"],
                }
            ]
        )
        assert core.verify_brief(brief, completed_with()) == []

    def test_numbers_inside_a_quoted_excerpt_are_exempt(self):
        brief = brief_with(
            key_findings=[
                {
                    "text": 'The code says "setback shall be 20 ft"; Pc is 3.2e-04.',
                    "severity": "info",
                    "evidence_ids": ["T1"],
                }
            ]
        )
        assert core.verify_brief(brief, completed_with()) == []

    def test_a_number_from_an_evidence_excerpt_counts_as_supported(self):
        brief = brief_with(quantitative_results={"Sigma": "88.5 m"})
        assert core.verify_brief(brief, completed_with(excerpt="sigma_x = 88.5 m")) == []


class TestCitations:
    def test_a_dangling_evidence_id_is_caught(self):
        brief = brief_with(
            key_findings=[{"text": "Pc is 3.2e-04.", "severity": "high", "evidence_ids": ["T9"]}]
        )
        issues = core.verify_brief(brief, completed_with())
        assert any("does not exist" in issue for issue in issues)

    def test_a_finding_with_no_citation_is_caught(self):
        brief = brief_with(
            key_findings=[{"text": "Pc is 3.2e-04.", "severity": "high", "evidence_ids": []}]
        )
        issues = core.verify_brief(brief, completed_with())
        assert any("no evidence id" in issue for issue in issues)


class TestForbiddenLanguage:
    @pytest.mark.parametrize(
        "text",
        [
            "I have approved the maneuver.",
            "The trade was executed.",
            "The packet was submitted to the issuer.",
            "This outcome is guaranteed.",
            "The order placed cleared at noon.",
        ],
    )
    def test_decision_taking_language_is_caught(self, text):
        issues = core.verify_brief(brief_with(summary=text), completed_with())
        assert any("decision-taking language" in issue for issue in issues)

    def test_a_workflow_can_add_its_own_patterns(self):
        class Spec:
            forbidden_phrases = [r"\bsafe to ignore\b"]
            level_vocab = []

        issues = core.verify_brief(
            brief_with(summary="This conjunction is safe to ignore."), completed_with(), Spec()
        )
        assert any("safe to ignore" in issue for issue in issues)

    def test_proposal_wording_is_allowed(self):
        brief = brief_with(recommendation="Proposed: maneuver planning — requires approval.")
        assert core.verify_brief(brief, completed_with()) == []


class TestStructuralChecks:
    def test_a_missing_disclaimer_is_caught(self):
        pack = core.SectorPack(**core.sector_identity("space"))
        issues = core.verify_brief(brief_with(disclaimer="   "), completed_with(), None, pack)
        assert any("disclaimer" in issue for issue in issues)

    def test_a_level_outside_the_vocabulary_is_caught(self):
        class Spec:
            forbidden_phrases = []
            level_vocab = ["RED", "YELLOW", "GREEN"]

        issues = core.verify_brief(
            brief_with(recommendation_level="MAUVE"), completed_with(), Spec()
        )
        assert any("is not one of" in issue for issue in issues)

    def test_fewer_than_two_options_is_caught(self):
        brief = brief_with(options=[{"name": "Only one", "description": "No choice offered."}])
        issues = core.verify_brief(brief, completed_with())
        assert any("two options" in issue for issue in issues)

    def test_a_brief_that_is_not_a_brief_fails_cleanly(self):
        issues = core.verify_brief({"title": "broken"}, completed_with())
        assert len(issues) == 1
        assert "schema" in issues[0]


class TestNumberNormalisation:
    def test_equivalent_forms_normalise_together(self):
        assert core.normalize_number("1,234") == core.normalize_number("1234")
        assert core.normalize_number("50%") == core.normalize_number("50")
        assert core.normalize_number("3.2e-04") == core.normalize_number("0.00032")

    def test_rounding_is_to_three_significant_figures(self):
        assert core.normalize_number("412.0001") == core.normalize_number("412")

    def test_non_numbers_return_nothing(self):
        assert core.normalize_number("abc") is None
