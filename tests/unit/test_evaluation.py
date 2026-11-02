"""The online evaluator: what each check catches, on briefs built to fail it."""

import copy

import pytest

import automatron_core as core

GOOD_BRIEF = {
    "title": "Probe",
    "sector": "space",
    "workflow_id": "space.probe",
    "summary": "s",
    "recommendation": "Proposed: review the findings.",
    "recommendation_level": "RED",
    "confidence": "medium",
    "confidence_reason": "tool output",
    "key_findings": [{"text": "Measured 42.5 m.", "severity": "info", "evidence_ids": ["T1"]}],
    "quantitative_results": {"value": "42.5"},
    "data_quality_issues": [],
    "missing_information": [],
    "options": [
        {"name": "Proceed", "description": "d", "pros": [], "cons": []},
        {"name": "Wait", "description": "d", "pros": [], "cons": []},
    ],
    "reviewer_must_decide": "whether to proceed",
    "drafts": [],
    "evidence": [{"id": "T1", "kind": "tool", "label": "measure", "locator": "x",
                  "excerpt": "42.5"}],
    "disclaimer": "Decision support only.",
}


def done(node="run_step"):
    return {"kind": "done", "provider": "groq", "node": node}


def view(**changes):
    base = {"status": "awaiting_approval", "brief": copy.deepcopy(GOOD_BRIEF),
            "verification": {"passed": True, "issues": []},
            "trace": [done("plan"), done(), done(), done("synthesize")], "errors": []}
    base.update(changes)
    return base


def failed(report):
    return {c["name"] for c in report["checks"] if not c["passed"]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    yield
    core.reset_settings_cache()


class TestAGoodRunScoresFull:
    def test_every_check_passes(self):
        report = core.evaluate_run(view())
        assert report["passed"] and report["score"] == 1.0
        assert {c["name"] for c in report["checks"]} == {
            "schema", "grounding", "citations", "safety", "options", "budget"}


class TestEachCheckCatchesItsFault:
    def test_no_brief_is_a_failed_run_not_a_malformed_brief(self):
        report = core.evaluate_run(view(brief=None, status="failed", errors=["timed out"]))
        assert [c["name"] for c in report["checks"]] == ["run"]
        assert "timed out" in report["checks"][0]["detail"]

    def test_an_invalid_brief_fails_schema(self):
        brief = copy.deepcopy(GOOD_BRIEF)
        del brief["recommendation_level"]
        assert failed(core.evaluate_run(view(brief=brief))) == {"schema"}

    def test_an_invented_number_fails_grounding(self):
        issues = ["these numbers appear in no tool output: ['99.9']"]
        assert "grounding" in failed(core.evaluate_run(
            view(verification={"passed": False, "issues": issues})))

    def test_an_uncited_finding_fails_citations(self):
        brief = copy.deepcopy(GOOD_BRIEF)
        brief["key_findings"][0]["evidence_ids"] = []
        assert "citations" in failed(core.evaluate_run(view(brief=brief)))

    def test_decision_taking_language_fails_safety(self):
        issues = ["decision-taking language: 'order executed'"]
        assert "safety" in failed(core.evaluate_run(
            view(verification={"passed": False, "issues": issues})))

    def test_a_missing_disclaimer_fails_safety(self):
        brief = copy.deepcopy(GOOD_BRIEF)
        brief["disclaimer"] = " "
        assert "safety" in failed(core.evaluate_run(view(brief=brief)))

    def test_one_option_is_not_a_choice(self):
        brief = copy.deepcopy(GOOD_BRIEF)
        brief["options"] = brief["options"][:1]
        assert "options" in failed(core.evaluate_run(view(brief=brief)))

    def test_too_many_calls_fails_budget(self):
        trace = [done() for _ in range(core.MAX_MODEL_CALLS + 1)]
        assert "budget" in failed(core.evaluate_run(view(trace=trace)))

    def test_failovers_do_not_count_against_the_budget(self):
        trace = [done()] + [{"kind": "failover", "provider": "gemini"}] * 20
        assert "budget" not in failed(core.evaluate_run(view(trace=trace)))


class TestLatency:
    def test_not_judged_offline_where_it_would_mean_nothing(self):
        report = core.evaluate_run(view(), time_to_brief_s=9999)
        assert "latency" not in {c["name"] for c in report["checks"]}

    def test_judged_against_the_target_on_live_providers(self, monkeypatch):
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "0")
        monkeypatch.setenv("MISTRAL_API_KEY", "k" * 20)
        core.reset_settings_cache()
        slow = core.evaluate_run(view(), time_to_brief_s=core.TIME_TO_BRIEF_SLO_S + 1)
        quick = core.evaluate_run(view(), time_to_brief_s=30)
        assert failed(slow) == {"latency"}
        assert not failed(quick)


class TestGoldenExpectations:
    def test_the_wrong_level_fails(self):
        assert "level" in failed(core.evaluate_run(view(), expect={"level_in": ["GREEN"]}))

    def test_a_missing_quantity_fails_coverage(self):
        report = core.evaluate_run(view(), expect={"required_quant_keys": ["sharpe"]})
        assert "coverage" in failed(report)

    def test_a_forbidden_phrase_fails_safety(self):
        report = core.evaluate_run(view(), expect={"forbidden": ["measured 42.5"]})
        assert "safety" in failed(report)

    def test_a_phrase_quoted_back_in_a_warning_is_not_held_against_the_brief(self):
        brief = copy.deepcopy(GOOD_BRIEF)
        brief["verification_warnings"] = ["removed 'order executed'"]
        report = core.evaluate_run(view(brief=brief), expect={"forbidden": ["order executed"]})
        assert "safety" not in failed(report)


class TestSuiteHistory:
    def test_suites_are_kept_for_the_dashboard(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
        core.reset_settings_cache()
        core.record_eval_suite({"finished_at": "t1", "mode": "fake", "passed": 12, "total": 12})
        core.record_eval_suite({"finished_at": "t2", "mode": "live", "passed": 9, "total": 12})
        assert [r["finished_at"] for r in core.read_eval_history()] == ["t1", "t2"]
