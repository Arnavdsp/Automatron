"""A tiny sector pack used only by tests, to exercise the graph without a real sector."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import automatron_core as core

WORKFLOW_ID = "space.probe"


class ProbeInputs(BaseModel):
    subject: str = Field(description="What to look at.")
    threshold: float = Field(default=1.0, description="Where the level flips.")


@tool
def measure(subject: str) -> dict:
    """Return a deterministic measurement for a subject."""
    return {"subject": subject, "value": 42.5, "unit": "m", "tool_version": 1}


@tool
def classify(value: float, threshold: float = 1.0) -> dict:
    """Classify a measurement against a threshold."""
    return {
        "level": "RED" if value > threshold else "GREEN",
        "value": value,
        "threshold": threshold,
        "tool_version": 1,
    }


DEFAULT_PLAN = core.Plan(
    objective="Measure the subject and classify the result.",
    steps=[
        core.PlanStep(
            id="s1",
            agent="executor",
            instruction="Measure the subject.",
            expected_output="a measurement",
        ),
        core.PlanStep(
            id="s2",
            agent="researcher",
            instruction="Find relevant context.",
            expected_output="context",
        ),
        core.PlanStep(
            id="s3",
            agent="analyst",
            instruction="Classify the measurement.",
            depends_on=["s1"],
            expected_output="a level",
        ),
    ],
)

# s1 and s2 have no dependencies, so the dispatcher runs them together and s3 waits.
FAKE_SCRIPT = {
    "s1": [{"tool_calls": [{"name": "measure", "args": {"subject": "probe-1"}}]}, "measured"],
    "s2": ["no tools needed"],
    "s3": [
        {"tool_calls": [{"name": "classify", "args": {"value": 42.5, "threshold": 1.0}}]},
        "classified",
    ],
}

STRUCTURED = {
    "Plan": DEFAULT_PLAN.model_dump(),
    "s1:StepResultDraft": {
        "status": "ok",
        "summary": "Measured 42.5 m.",
        "data": {"value": 42.5, "unit": "m"},
    },
    "s2:StepResultDraft": {
        "status": "ok",
        "summary": "No regulatory constraints found.",
        "data": {"sources": 0},
    },
    "s3:StepResultDraft": {
        "status": "ok",
        "summary": "Level is RED at 42.5 m.",
        "data": {"level": "RED", "value": 42.5, "threshold": 1.0},
    },
    "DecisionBrief": {
        "title": "Probe assessment",
        "sector": "space",
        "workflow_id": WORKFLOW_ID,
        "summary": "The probe measured 42.5 m, above the 1.0 threshold.",
        "recommendation": "Proposed: review the measurement — requires operator approval.",
        "recommendation_level": "RED",
        "confidence": "medium",
        "confidence_reason": "One measurement, no repeat observation.",
        "key_findings": [
            {"text": "Measured value is 42.5 m.", "severity": "high", "evidence_ids": ["T1"]},
            {
                "text": "Classified RED against a 1.0 threshold.",
                "severity": "high",
                "evidence_ids": ["T2"],
            },
        ],
        "quantitative_results": {"Measured value": "42.5 m", "Threshold": "1.0"},
        "data_quality_issues": ["Only one observation."],
        "missing_information": ["No repeat measurement."],
        "options": [
            {
                "name": "Re-measure",
                "description": "Take another observation before deciding.",
                "pros": ["Cheap"],
                "cons": ["Delays the decision"],
            },
            {
                "name": "Escalate",
                "description": "Send to the operator now.",
                "pros": ["Fast"],
                "cons": ["Acts on one observation"],
            },
        ],
        "reviewer_must_decide": "Whether one observation is enough to act on.",
    },
}

# A brief that should fail verification: invented number, bad citation, forbidden wording.
BAD_BRIEF = {
    **STRUCTURED["DecisionBrief"],
    "summary": "The probe measured 99.9 m and I have approved the response.",
    "key_findings": [
        {"text": "Measured value is 99.9 m.", "severity": "high", "evidence_ids": ["T99"]}
    ],
    "quantitative_results": {"Measured value": "99.9 m"},
}


def build_pack() -> core.SectorPack:
    workflow = core.WorkflowSpec(
        id=WORKFLOW_ID,
        name="Probe",
        description="Measure a subject and classify it.",
        input_schema=ProbeInputs,
        step_template="1. measure  2. context  3. classify",
        default_plan=DEFAULT_PLAN,
        fake_script=FAKE_SCRIPT,
        level_vocab=["RED", "GREEN"],
        forbidden_phrases=[r"\bprobe was launched\b"],
        sample_name="probe_sample",
        example_request="Assess probe-1.",
    )
    return core.SectorPack(
        **core.sector_identity("space"),
        tools=[
            core.ToolSpec(tool=measure, roles=["executor"]),
            core.ToolSpec(tool=classify, roles=["analyst"]),
        ],
        workflows=[workflow],
        addenda={"coordinator": "Keep it short.", "analyst": "State units."},
    )


def install(monkeypatch=None) -> core.SectorPack:
    """Register the pack and install its script for fake mode."""
    core.clear_registry()
    pack = build_pack()
    core.register_sector(pack)
    core.set_fake_script(steps=FAKE_SCRIPT, structured=STRUCTURED, default=["ok"])
    return pack
