"""The schemas that carry work between agents, the graph, and the reviewer."""

import pytest
from pydantic import BaseModel, ValidationError

import automatron_core as core


def plan(*steps, objective="check something"):
    return core.Plan(objective=objective, steps=list(steps))


def step(step_id, depends_on=(), agent="analyst"):
    return core.PlanStep(
        id=step_id, agent=agent, instruction="do the thing", depends_on=list(depends_on)
    )


class TestEvidence:
    def test_excerpt_is_truncated_not_rejected(self):
        evidence = core.Evidence(id="T1", kind="tool", label="compute_pc_2d", excerpt="x" * 500)
        assert len(evidence.excerpt) == core.MAX_EXCERPT_CHARS

    def test_excerpt_may_be_absent(self):
        assert core.Evidence(id="S1", kind="source", label="policy").excerpt is None

    def test_kind_is_constrained(self):
        with pytest.raises(ValidationError):
            core.Evidence(id="X1", kind="guess", label="nope")


class TestPlan:
    def test_a_valid_plan_reports_no_issues(self):
        assert plan(step("s1"), step("s2", ["s1"])).issues() == []

    def test_too_few_steps_is_reported(self):
        issues = plan(step("s1")).issues()
        assert any("between" in issue for issue in issues)

    def test_too_many_steps_is_reported(self):
        steps = [step(f"s{i}") for i in range(1, core.MAX_PLAN_STEPS + 2)]
        assert any("between" in issue for issue in plan(*steps).issues())

    def test_duplicate_ids_are_reported(self):
        assert any("duplicate" in i for i in plan(step("s1"), step("s1")).issues())

    def test_unknown_dependency_is_reported(self):
        issues = plan(step("s1"), step("s2", ["s9"])).issues()
        assert any("unknown" in issue for issue in issues)

    def test_self_dependency_is_reported(self):
        issues = plan(step("s1"), step("s2", ["s2"])).issues()
        assert any("itself" in issue for issue in issues)

    def test_cycle_is_detected(self):
        cyclic = plan(step("s1", ["s2"]), step("s2", ["s1"]))
        assert cyclic.has_cycle()
        assert any("cycle" in issue for issue in cyclic.issues())

    def test_a_chain_is_not_a_cycle(self):
        assert not plan(step("s1"), step("s2", ["s1"]), step("s3", ["s2"])).has_cycle()

    def test_parallel_steps_are_not_a_cycle(self):
        assert not plan(step("s1"), step("s2"), step("s3", ["s1", "s2"])).has_cycle()


class TestApprovalDecision:
    def test_reviewer_name_is_required(self):
        with pytest.raises(ValidationError):
            core.ApprovalDecision(action="approve", reviewer="   ")

    def test_reviewer_name_is_trimmed(self):
        assert core.ApprovalDecision(action="approve", reviewer="  Arnav ").reviewer == "Arnav"

    def test_action_is_constrained(self):
        with pytest.raises(ValidationError):
            core.ApprovalDecision(action="execute", reviewer="Arnav")

    def test_edits_are_limited_to_the_allowlist(self):
        allowed = core.ApprovalDecision(
            action="approve", reviewer="Arnav", edits={"recommendation": "Proposed: monitor"}
        )
        assert allowed.edits

        with pytest.raises(ValidationError):
            core.ApprovalDecision(
                action="approve", reviewer="Arnav", edits={"recommendation_level": "GREEN"}
            )

    def test_no_edits_is_fine(self):
        assert core.ApprovalDecision(action="reject", reviewer="Arnav").edits is None


class TestTraceEvent:
    def test_message_is_capped(self):
        event = core.TraceEvent(run_id="r1", node="plan", kind="start", message="y" * 400)
        assert len(event.message) == core.MAX_TRACE_MESSAGE_CHARS

    def test_message_is_redacted(self):
        event = core.TraceEvent(
            run_id="r1", node="plan", kind="error", message=f"key {'gsk_' + 'a' * 24} failed"
        )
        assert "a" * 24 not in event.message

    def test_timestamp_is_filled_in(self):
        assert core.TraceEvent(run_id="r1", node="intake", kind="start").ts


class TestDecisionBrief:
    def test_minimal_brief_validates_with_safe_defaults(self):
        brief = core.DecisionBrief(
            title="Conjunction triage",
            sector="space",
            workflow_id="space.conjunction_triage",
            summary="A close approach needs review.",
            recommendation="Proposed: maneuver planning — requires operator approval.",
            recommendation_level="RED",
        )
        assert brief.confidence == "low"
        assert brief.decision is None
        assert brief.key_findings == []
        assert brief.verification_warnings == []

    def test_decision_is_constrained(self):
        with pytest.raises(ValidationError):
            core.DecisionBrief(
                title="t",
                sector="space",
                workflow_id="w",
                summary="s",
                recommendation="r",
                recommendation_level="RED",
                decision="executed",
            )


class TestSectorPack:
    @staticmethod
    def build_pack():
        class Inputs(BaseModel):
            note: str = ""

        def a_tool():
            return {}

        a_tool.name = "a_tool"

        workflow = core.WorkflowSpec(
            id="space.demo",
            name="Demo",
            description="A demo workflow.",
            input_schema=Inputs,
            default_plan=plan(step("s1", agent="executor"), step("s2", ["s1"])),
        )
        return core.SectorPack(
            **core.sector_identity("space"),
            tools=[core.ToolSpec(tool=a_tool, roles=["analyst"])],
            workflows=[workflow],
            addenda={"analyst": "Pc in scientific notation."},
        )

    def test_identity_comes_from_configuration(self):
        pack = self.build_pack()
        assert pack.display_name == "Automatron Space"
        assert pack.accent == "#7C8CFF"
        assert "Decision support only" in pack.disclaimer

    def test_tools_are_filtered_by_role(self):
        pack = self.build_pack()
        assert pack.tool_names_for("analyst") == {"a_tool"}
        assert pack.tools_for("researcher") == []

    def test_workflow_lookup(self):
        pack = self.build_pack()
        assert pack.workflow("space.demo").name == "Demo"
        assert pack.has_workflow("space.demo")
        with pytest.raises(KeyError):
            pack.workflow("space.missing")

    def test_addendum_defaults_to_empty(self):
        assert self.build_pack().addendum("executor") == ""

    def test_a_broken_default_plan_is_refused(self):
        class Inputs(BaseModel):
            note: str = ""

        with pytest.raises(ValidationError):
            core.WorkflowSpec(
                id="space.bad",
                name="Bad",
                description="Fallback plan has a cycle.",
                input_schema=Inputs,
                default_plan=plan(step("s1", ["s2"]), step("s2", ["s1"])),
            )
