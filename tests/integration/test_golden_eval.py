"""The golden scenarios, scored the same way run_eval.py scores them."""

import importlib
import sys

import pytest
import yaml

import automatron_core as core

EVAL_DIR = core.ROOT / "tests" / "eval"
sys.path.insert(0, str(EVAL_DIR))

import run_eval  # noqa: E402


def scenarios():
    return [
        yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted((EVAL_DIR / "golden").glob("*.yaml"))
    ]


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_run_service()
    core.clear_registry()
    # A module registers its pack on first import only, and imports are cached, so
    # re-register explicitly after clearing rather than re-importing.
    for name in ("automatron_space",):
        core.register_sector(importlib.import_module(name).SECTOR_PACK)
    yield
    core.clear_fake_script()
    core.clear_registry()
    core.reset_run_service()
    core.reset_settings_cache()


def test_there_is_a_scenario_for_every_registered_workflow(eval_env):
    covered = {s["workflow_id"] for s in scenarios()}
    for pack in core.list_sectors():
        for workflow in pack.workflows:
            assert workflow.id in covered, f"no golden scenario for {workflow.id}"


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s["workflow_id"])
async def test_scenario_passes_every_check(scenario, eval_env):
    ok, checks = await run_eval.run_one(scenario, core)
    failures = [f"{name}: {reason}" for name, passed, reason in checks if not passed]
    assert ok, "; ".join(failures)
