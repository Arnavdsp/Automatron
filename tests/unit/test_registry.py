"""Sector packs register themselves on import; the registry keeps them in order."""

import pytest
from pydantic import BaseModel

import automatron_core as core


class Inputs(BaseModel):
    note: str = ""


def make_plan():
    return core.Plan(
        objective="demo",
        steps=[
            core.PlanStep(id="s1", agent="executor", instruction="parse"),
            core.PlanStep(id="s2", agent="analyst", instruction="assess", depends_on=["s1"]),
        ],
    )


def make_workflow(workflow_id):
    return core.WorkflowSpec(
        id=workflow_id,
        name="Demo",
        description="A demo workflow.",
        input_schema=Inputs,
        default_plan=make_plan(),
    )


def make_pack(sector_id, workflow_ids=None):
    ids = workflow_ids if workflow_ids is not None else [f"{sector_id}.demo"]
    return core.SectorPack(
        **core.sector_identity(sector_id),
        workflows=[make_workflow(wid) for wid in ids],
    )


@pytest.fixture(autouse=True)
def empty_registry():
    core.clear_registry()
    yield
    core.clear_registry()


def test_registering_makes_a_pack_retrievable():
    core.register_sector(make_pack("space"))
    assert core.get_sector("space").display_name == "Automatron Space"


def test_unregistered_sector_raises_a_helpful_error():
    with pytest.raises(core.UnknownSector, match="not registered"):
        core.get_sector("space")


def test_unknown_sector_is_a_subclass_of_key_error():
    assert issubclass(core.UnknownSector, KeyError)


def test_listing_follows_display_order_not_registration_order():
    for sector_id in ("realestate", "space", "ecommerce", "quant"):
        core.register_sector(make_pack(sector_id))
    assert core.registered_sector_ids() == list(core.SECTOR_ORDER)


def test_listing_only_includes_registered_packs():
    core.register_sector(make_pack("quant"))
    assert core.registered_sector_ids() == ["quant"]


def test_a_sector_outside_the_known_set_is_refused():
    pack = make_pack("space").model_copy(update={"id": "aviation"})
    with pytest.raises(ValueError, match="not a known sector"):
        core.register_sector(pack)


def test_workflow_ids_must_carry_the_sector_prefix():
    with pytest.raises(ValueError, match="prefixed"):
        core.register_sector(make_pack("space", ["conjunction_triage"]))


def test_duplicate_workflow_ids_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        core.register_sector(make_pack("space", ["space.demo", "space.demo"]))


def test_re_registering_replaces_the_pack():
    core.register_sector(make_pack("space", ["space.first"]))
    core.register_sector(make_pack("space", ["space.second"]))
    assert core.get_sector("space").has_workflow("space.second")
    assert not core.get_sector("space").has_workflow("space.first")


def test_get_workflow_reaches_through_the_registry():
    core.register_sector(make_pack("space"))
    assert core.get_workflow("space", "space.demo").name == "Demo"
