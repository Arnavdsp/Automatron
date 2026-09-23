"""The whole graph, end to end, against the scripted model."""

import pytest
from pydantic import ValidationError

import automatron_core as core
from tests import testsector


# Function scope throughout: each test builds its own checkpointer and closes it,
# so there is nothing to share and no chance of a fixture and a test ending up on
# different event loops.
@pytest.fixture
async def graph_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_run_service()
    pack = testsector.install()
    yield pack
    await core.close_run_service()
    core.clear_fake_script()
    core.clear_registry()
    core.reset_settings_cache()


_DEFAULT_INPUTS = {"subject": "probe-1"}


async def run_to_gate(request="Assess probe-1.", inputs=_DEFAULT_INPUTS):
    # Not `inputs or default`: an empty dict is a meaningful argument here.
    run_id = await core.start_run("space", testsector.WORKFLOW_ID, request, inputs)
    await core.wait_for_run(run_id)
    return run_id, await core.get_run(run_id)


class TestHappyPath:
    async def test_run_reaches_the_approval_gate(self, graph_env):
        _, view = await run_to_gate()
        assert view.status == "awaiting_approval"
        assert view.awaiting_approval is True
        assert view.brief is not None

    async def test_every_planned_step_ran(self, graph_env):
        run_id, view = await run_to_gate()
        record = core._RUNS[run_id]["state"]
        assert set(record["completed"]) == {"s1", "s2", "s3"}
        assert all(r["status"] == "ok" for r in record["completed"].values())

    async def test_dependent_step_saw_its_dependency(self, graph_env):
        run_id, _ = await run_to_gate()
        completed = core._RUNS[run_id]["state"]["completed"]
        assert completed["s3"]["data"]["level"] == "RED"

    async def test_evidence_is_renumbered_across_steps(self, graph_env):
        _, view = await run_to_gate()
        ids = [item["id"] for item in view.brief["evidence"]]
        assert ids == ["T1", "T2"], "two tool calls across two steps, numbered run-wide"

    async def test_brief_carries_the_sector_disclaimer(self, graph_env):
        _, view = await run_to_gate()
        assert "Decision support only" in view.brief["disclaimer"]

    async def test_verification_passed(self, graph_env):
        _, view = await run_to_gate()
        assert view.verification["passed"] is True, view.verification["issues"]

    async def test_trace_records_each_node(self, graph_env):
        _, view = await run_to_gate()
        nodes = {event["node"] for event in view.trace}
        assert {"intake", "plan", "run_step", "synthesize", "verify"} <= nodes

    async def test_the_run_is_not_decided_yet(self, graph_env):
        _, view = await run_to_gate()
        assert view.brief["decision"] is None
        assert view.brief["decided_by"] is None


class TestApproval:
    async def test_approve_finalises_and_stamps_the_reviewer(self, graph_env):
        run_id, _ = await run_to_gate()
        view = await core.submit_decision(
            run_id, {"action": "approve", "reviewer": "Arnav", "notes": "Looks right."}
        )
        assert view.status == "approved"
        assert view.brief["decision"] == "approved"
        assert view.brief["decided_by"] == "Arnav"
        assert view.brief["decided_at"]

    async def test_reject_finalises_as_rejected(self, graph_env):
        run_id, _ = await run_to_gate()
        view = await core.submit_decision(
            run_id, {"action": "reject", "reviewer": "Arnav", "notes": "Not enough data."}
        )
        assert view.status == "rejected"
        assert view.brief["decision"] == "rejected"

    async def test_approved_brief_says_next_steps_happen_elsewhere(self, graph_env):
        run_id, _ = await run_to_gate()
        await core.submit_decision(run_id, {"action": "approve", "reviewer": "Arnav"})
        view = await core.get_run(run_id)
        rendered = core.render_brief_markdown(view.brief)
        assert "for next steps outside Automatron" in rendered

    async def test_a_decision_needs_a_reviewer_name(self, graph_env):
        run_id, _ = await run_to_gate()
        with pytest.raises(ValidationError):
            await core.submit_decision(run_id, {"action": "approve", "reviewer": "  "})

    async def test_deciding_twice_is_refused(self, graph_env):
        run_id, _ = await run_to_gate()
        await core.submit_decision(run_id, {"action": "approve", "reviewer": "Arnav"})
        with pytest.raises(ValueError, match="not waiting"):
            await core.submit_decision(run_id, {"action": "reject", "reviewer": "Arnav"})


class TestRequestChanges:
    async def test_request_changes_returns_to_the_gate_with_the_note_recorded(self, graph_env):
        run_id, first = await run_to_gate()
        # The brief a reviewer first sees has not been revised, so the count is zero.
        assert first.revisions == 0

        view = await core.submit_decision(
            run_id,
            {"action": "request_changes", "reviewer": "Arnav", "notes": "Add the units."},
        )
        assert view.status == "awaiting_approval"
        assert view.revisions == 1
        assert "Add the units." in view.brief["revision_notes"]

    async def test_the_reviewer_gets_every_round_the_gate_offers(self, graph_env):
        """Both change requests must be acted on, not just the first."""
        run_id, _ = await run_to_gate()
        first = await core.submit_decision(
            run_id, {"action": "request_changes", "reviewer": "Arnav", "notes": "One."}
        )
        second = await core.submit_decision(
            run_id, {"action": "request_changes", "reviewer": "Arnav", "notes": "Two."}
        )
        assert (first.revisions, second.revisions) == (1, core.MAX_REVISIONS)
        assert "Two." in second.brief["revision_notes"]

    async def test_the_revision_limit_is_enforced(self, graph_env):
        run_id, _ = await run_to_gate()
        for note in ("One.", "Two.", "Three."):
            view = await core.submit_decision(
                run_id, {"action": "request_changes", "reviewer": "Arnav", "notes": note}
            )
        # Still at the gate, and now the reviewer has to approve or reject.
        assert view.status == "awaiting_approval"
        assert view.revisions == core.MAX_REVISIONS
        assert any("revision limit" in e["message"] for e in view.trace)
        assert "Three." not in view.brief["revision_notes"]

    async def test_approving_after_a_revision_still_works(self, graph_env):
        run_id, _ = await run_to_gate()
        await core.submit_decision(
            run_id, {"action": "request_changes", "reviewer": "Arnav", "notes": "More detail."}
        )
        view = await core.submit_decision(run_id, {"action": "approve", "reviewer": "Arnav"})
        assert view.status == "approved"


class TestReviewerEdits:
    async def test_an_allowed_edit_is_applied(self, graph_env):
        run_id, _ = await run_to_gate()
        view = await core.submit_decision(
            run_id,
            {
                "action": "approve",
                "reviewer": "Arnav",
                "edits": {"recommendation": "Proposed: re-measure before deciding."},
            },
        )
        assert view.brief["recommendation"] == "Proposed: re-measure before deciding."

    async def test_editing_a_protected_field_is_refused(self, graph_env):
        run_id, _ = await run_to_gate()
        with pytest.raises(ValidationError, match="cannot be edited"):
            await core.submit_decision(
                run_id,
                {
                    "action": "approve",
                    "reviewer": "Arnav",
                    "edits": {"recommendation_level": "GREEN"},
                },
            )


class TestAudit:
    async def test_a_decision_writes_a_verifiable_audit_entry(self, graph_env):
        run_id, _ = await run_to_gate()
        await core.submit_decision(
            run_id, {"action": "approve", "reviewer": "Arnav", "notes": "ok"}
        )

        entries = core.read_audit(run_id)
        assert len(entries) == 1
        assert entries[0]["action"] == "approve"
        assert entries[0]["reviewer"] == "Arnav"
        assert entries[0]["brief_sha256"]

        valid, problems = core.verify_audit_chain()
        assert valid, problems

    async def test_a_rejection_is_recorded_as_carefully_as_an_approval(self, graph_env):
        """Both outcomes have to be auditable, or the log only records agreement."""
        run_id, _ = await run_to_gate()
        await core.submit_decision(
            run_id, {"action": "reject", "reviewer": "Arnav", "notes": "not enough evidence"}
        )

        entries = core.read_audit(run_id)
        assert len(entries) == 1
        assert entries[0]["action"] == "reject"
        assert entries[0]["reviewer"] == "Arnav"
        assert entries[0]["brief_sha256"]

        valid, problems = core.verify_audit_chain()
        assert valid, problems

    async def test_the_chain_links_successive_runs(self, graph_env):
        for _ in range(2):
            run_id, _ = await run_to_gate()
            await core.submit_decision(run_id, {"action": "approve", "reviewer": "Arnav"})

        entries = core.read_audit()
        assert len(entries) == 2
        assert entries[1]["prev_hash"] == entries[0]["hash"]
        assert core.verify_audit_chain()[0]

    async def test_tampering_is_detected(self, graph_env):
        run_id, _ = await run_to_gate()
        await core.submit_decision(run_id, {"action": "approve", "reviewer": "Arnav"})

        entries = core.read_audit()
        entries[0]["reviewer"] = "Someone Else"
        valid, problems = core.verify_audit_chain(entries)
        assert not valid
        assert any("altered" in p for p in problems)


class TestFailureHandling:
    async def test_an_unknown_workflow_is_refused_before_starting(self, graph_env):
        with pytest.raises(ValueError, match="no workflow"):
            await core.start_run("space", "space.nope", "hi", {})

    async def test_missing_inputs_are_recorded_but_do_not_stop_the_run(self, graph_env):
        _, view = await run_to_gate(inputs={})
        assert view.status == "awaiting_approval"
        assert any("incomplete" in e["message"] for e in view.trace)

    async def test_an_unknown_run_id_is_a_clear_error(self, graph_env):
        with pytest.raises(KeyError, match="Run expired"):
            await core.get_run("does-not-exist")

    async def test_streaming_yields_events_then_stops(self, graph_env):
        run_id, _ = await run_to_gate()
        seen = [event async for event in core.stream_events(run_id)]
        assert seen and seen[0]["node"] == "intake"


class TestPlanSize:
    """A workflow's own plan is the shape its author designed."""

    async def test_an_oversized_plan_falls_back_to_the_workflows_own(self, graph_env):
        """Falling back costs nothing; asking for a repair costs the call being saved."""
        designed = len(testsector.DEFAULT_PLAN.steps)
        oversized = {
            "objective": "Do more than the workflow asks for.",
            "steps": [
                {"id": f"x{n}", "agent": "executor", "instruction": "Do a thing.",
                 "depends_on": []}
                for n in range(designed + 2)
            ]
        }
        # The run installs the workflow's own script, so the override belongs there.
        spec = graph_env.workflow(testsector.WORKFLOW_ID)
        spec.fake_script = {
            "steps": testsector.FAKE_SCRIPT,
            "structured": {**testsector.STRUCTURED, "Plan": oversized},
        }
        _, view = await run_to_gate()
        assert any("more than the" in e["message"] for e in view.trace)
        ran = {e["step_id"] for e in view.trace if e.get("step_id")}
        assert len(ran) <= designed

    async def test_the_prompt_states_the_workflows_own_ceiling(self, graph_env):
        """The planner is told the number it should plan to, not the global backstop."""
        assert "{max_plan_steps}" in core.COORDINATOR_PLAN_PROMPT
