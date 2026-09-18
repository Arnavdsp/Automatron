"""Contracts every sector pack must honour, checked across all twelve workflows.

Each sector was built and tested on its own. These check the things that are easy to
get subtly wrong once and never notice: a sample name that does not resolve, a demo
script that silently skips a step, a level a tool can never actually produce.
"""

import importlib

import pytest

import automatron_core as core

SECTOR_MODULES = ("automatron_space", "automatron_quant", "automatron_ecommerce",
                  "automatron_realestate")


# Registered at import time, not in a fixture: the parametrize calls below run during
# collection, so a fixture would leave them reading whatever the previous test module
# happened to leave in the registry.
for _name in SECTOR_MODULES:
    core.register_sector(importlib.import_module(_name).SECTOR_PACK)

# Tools a sector offers that no plan hints at and no demo script calls. They stay
# available because a live model may still choose them, but demo mode never exercises
# them, so they are listed here deliberately: a new one shows up as a failure and has
# to be either used or removed.
NOT_EXERCISED_BY_DEMO = {
    "space": {
        # pc_trend calls this per message, so it is covered through that path.
        "compute_pc_2d",
        # Reaches the network for catalogue elements, which a demo run must not do.
        "fetch_gp_elements",
        # Available for an operator asking for a timeline directly; the anomaly plan
        # does not need one to rank hypotheses.
        "build_timeline",
    },
    "quant": set(),
    "ecommerce": set(),
    "realestate": set(),
}


@pytest.fixture(autouse=True)
def all_sectors():
    """Re-register after any test module that cleared the registry."""
    for name in SECTOR_MODULES:
        core.register_sector(importlib.import_module(name).SECTOR_PACK)
    yield


def every_workflow():
    return [(pack, workflow) for pack in core.list_sectors() for workflow in pack.workflows]


def workflow_ids():
    return [w.id for _, w in every_workflow()]


def test_all_four_sectors_and_twelve_workflows_are_registered():
    packs = core.list_sectors()
    assert {p.id for p in packs} == {"space", "quant", "ecommerce", "realestate"}
    assert len(workflow_ids()) == 12
    assert len(set(workflow_ids())) == 12


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_the_demo_script_covers_every_step_of_the_plan(workflow_id):
    """A step with no scripted answer is skipped in demo mode without saying so."""
    _, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    scripted = set(workflow.fake_script.get("steps", {}))
    planned = {step.id for step in workflow.default_plan.steps}
    assert planned - scripted == set(), f"{workflow_id}: unscripted steps {planned - scripted}"
    assert scripted - planned == set(), f"{workflow_id}: script has steps the plan lacks"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_every_scripted_tool_is_one_the_sector_offers(workflow_id):
    """A scripted call to a tool the pack does not expose fails only at run time."""
    pack, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    available = {spec.name for spec in pack.tools} | {"search_knowledge"}
    for step_id, script in workflow.fake_script.get("steps", {}).items():
        for entry in script:
            if not isinstance(entry, dict):
                continue
            for call in entry.get("tool_calls", []):
                assert call["name"] in available, \
                    f"{workflow_id} {step_id} calls unknown tool {call['name']}"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_every_planned_tool_hint_is_a_real_tool(workflow_id):
    pack, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    available = {spec.name for spec in pack.tools} | {"search_knowledge"}
    for step in workflow.default_plan.steps:
        for hint in step.tool_hints:
            assert hint in available, f"{workflow_id} {step.id} hints at unknown tool {hint}"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_each_step_is_assigned_to_a_role_that_may_call_its_tools(workflow_id):
    """A step hinting at a tool its own role is not allowed to call cannot succeed."""
    pack, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    for step in workflow.default_plan.steps:
        allowed = pack.tool_names_for(step.agent) | {"search_knowledge"}
        for hint in step.tool_hints:
            assert hint in allowed, \
                f"{workflow_id} {step.id}: {step.agent} may not call {hint}"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_the_workflow_declares_what_a_reviewer_needs(workflow_id):
    _, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    assert workflow.level_vocab, f"{workflow_id} has no levels"
    assert len(set(workflow.level_vocab)) == len(workflow.level_vocab)
    assert workflow.forbidden_phrases, f"{workflow_id} forbids nothing"
    assert workflow.example_request.strip()
    assert workflow.description.strip()
    assert workflow.default_plan.issues() == []


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_the_forbidden_phrases_compile_and_match_nothing_innocuous(workflow_id):
    """A pattern that matches ordinary prose would block every brief."""
    import re

    _, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    innocuous = ("The reviewer should consider the options below. "
                 "Findings are set out with their sources and the thresholds used.")
    for pattern in workflow.forbidden_phrases:
        compiled = re.compile(pattern, re.IGNORECASE)
        assert compiled.search(innocuous) is None, \
            f"{workflow_id}: {pattern!r} matches ordinary prose"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_the_named_sample_resolves(workflow_id):
    """A sample name that does not resolve turns the example into a dead end."""
    pack, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    if not workflow.sample_name:
        pytest.skip(f"{workflow_id} names no sample")
    if pack.ensure_samples:
        pack.ensure_samples()
    directory = core.get_settings().data_path / "samples" / pack.id
    matches = list(directory.glob(f"{workflow.sample_name}.*"))
    assert matches, f"{workflow_id}: no file for sample '{workflow.sample_name}' in {directory}"


@pytest.mark.parametrize("workflow_id", workflow_ids())
def test_sample_inputs_validate_against_the_input_schema(workflow_id):
    _, workflow = next(w for w in every_workflow() if w[1].id == workflow_id)
    sample = core.sample_inputs_for(workflow)
    assert isinstance(sample, dict)
    workflow.input_schema.model_validate(sample)


@pytest.mark.parametrize("sector_id", ["space", "quant", "ecommerce", "realestate"])
def test_every_sector_carries_its_disclaimer_and_identity(sector_id):
    pack = core.get_sector(sector_id)
    assert pack.display_name.strip()
    assert pack.tagline.strip()
    assert pack.accent.startswith("#")
    assert "decision support" in pack.disclaimer.lower()
    assert pack.tools and pack.workflows


@pytest.mark.parametrize("sector_id", ["space", "quant", "ecommerce", "realestate"])
def test_every_role_that_a_plan_uses_has_guidance(sector_id):
    pack = core.get_sector(sector_id)
    used = {step.agent for workflow in pack.workflows for step in workflow.default_plan.steps}
    for role in used:
        assert pack.addendum(role).strip(), f"{sector_id}: {role} has no guidance"


@pytest.mark.parametrize("sector_id", ["space", "quant", "ecommerce", "realestate"])
def test_the_tools_demo_mode_never_exercises_are_the_expected_ones(sector_id):
    """A tool no plan hints at and no script calls is never seen offline.

    That can be deliberate, so the set is written down rather than asserted empty: a
    tool that joins it has to be justified here or removed, instead of quietly
    becoming code nothing runs.
    """
    pack = core.get_sector(sector_id)
    hinted = {hint for workflow in pack.workflows
              for step in workflow.default_plan.steps for hint in step.tool_hints}
    scripted = {call["name"] for workflow in pack.workflows
                for script in workflow.fake_script.get("steps", {}).values()
                for entry in script if isinstance(entry, dict)
                for call in entry.get("tool_calls", [])}
    offered = {spec.name for spec in pack.tools}
    assert offered - (hinted | scripted) == NOT_EXERCISED_BY_DEMO[sector_id]


@pytest.mark.parametrize("sector_id", ["space", "quant", "ecommerce", "realestate"])
def test_every_tool_is_offered_to_at_least_one_role(sector_id):
    """A tool with no roles cannot be called by anything, live or offline."""
    for spec in core.get_sector(sector_id).tools:
        assert spec.roles, f"{sector_id}: {spec.name} is offered to no role"
