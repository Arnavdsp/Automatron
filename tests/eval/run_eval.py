"""Score the golden scenarios. Run: python tests/eval/run_eval.py --mode fake

Every check is deterministic; no model judges another model's work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
GOLDEN = pathlib.Path(__file__).parent / "golden"
sys.path.insert(0, str(ROOT / "automatron_build"))

MAX_MODEL_CALLS = 12
MAX_COORDINATOR_CALLS = 4


def load_scenarios(only: list[str] | None) -> list[dict]:
    scenarios = []
    for path in sorted(GOLDEN.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not only or scenario["workflow_id"] in only:
            scenarios.append(scenario)
    return scenarios


def score(scenario: dict, view, core) -> list[tuple[str, bool, str]]:
    """Each check returns its name, whether it passed, and a short reason."""
    expect = scenario["expect"]
    brief = view.brief or {}
    checks: list[tuple[str, bool, str]] = []

    # A run that never produced a brief is a failed run, not a malformed brief.
    # Validating an empty dict reports every required field as missing, which hides
    # the thing that actually went wrong.
    if not brief:
        errors = "; ".join(view.errors or []) or "no error recorded"
        checks.append(("run", False, f"status {view.status}, no brief: {errors}"[:160]))
        return checks

    try:
        core.DecisionBrief.model_validate(brief)
        checks.append(("schema", True, ""))
    except Exception as exc:
        checks.append(("schema", False, str(exc)[:160]))
        return checks

    level = brief.get("recommendation_level")
    checks.append(
        ("level", level in expect["level_in"], f"got {level}, expected one of {expect['level_in']}")
    )

    issues = (view.verification or {}).get("issues") or []
    invented = [i for i in issues if "no tool output" in i]
    checks.append(("grounding", not invented, "; ".join(invented)[:100]))

    findings = brief.get("key_findings", [])
    cited = all(f.get("evidence_ids") for f in findings)
    checks.append(("citations", bool(findings) and cited, "a finding has no evidence id"))

    keys = " ".join(brief.get("quantitative_results", {})).lower()
    missing = [k for k in expect.get("required_quant_keys", []) if k.lower() not in keys]
    enough = len(findings) >= expect.get("min_findings", 1)
    blob = json.dumps(brief, default=str).lower()
    mentioned = (
        any(m.lower() in blob for m in expect.get("must_mention_any", []))
        if expect.get("must_mention_any")
        else True
    )
    checks.append(
        (
            "coverage",
            not missing and enough and mentioned,
            f"missing {missing}"
            if missing
            else (f"{len(findings)} findings" if not enough else "no expected mention"),
        )
    )

    forbidden_hit = [p for p in expect.get("forbidden", []) if p.lower() in blob]
    has_disclaimer = bool(brief.get("disclaimer", "").strip())
    checks.append(
        (
            "safety",
            not forbidden_hit and has_disclaimer,
            f"forbidden {forbidden_hit}" if forbidden_hit else "no disclaimer",
        )
    )

    checks.append(
        (
            "options",
            len(brief.get("options", [])) >= expect.get("min_options", 2),
            f"{len(brief.get('options', []))} options",
        )
    )

    # Only completions count against the budget. Every trace event from the router
    # carries a provider, including the failover notices, so counting all of them
    # measured how hard the chain had to work rather than how many answers the run
    # needed: a step that failed over twice before succeeding read as three calls.
    done = [e for e in view.trace if e.get("provider") and e.get("kind") == "done"]
    model_calls = len(done)
    coordinator_calls = sum(1 for e in done if e.get("node") in ("plan", "synthesize"))
    failovers = sum(1 for e in view.trace if e.get("kind") == "failover")
    checks.append(
        (
            "budget",
            model_calls <= MAX_MODEL_CALLS and coordinator_calls <= MAX_COORDINATOR_CALLS,
            f"{model_calls} completions ({failovers} failovers), "
            f"{coordinator_calls} coordinator",
        )
    )
    return checks


async def run_one(scenario: dict, core) -> tuple[bool, list[tuple[str, bool, str]]]:
    inputs = {"sample_name": scenario["sample"]} if scenario.get("sample") else {}
    run_id = await core.start_run(
        scenario["sector"], scenario["workflow_id"], scenario["request"], inputs
    )
    await core.wait_for_run(run_id)
    view = await core.get_run(run_id)
    checks = score(scenario, view, core)
    return all(passed for _, passed, _ in checks), checks


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--workflows", nargs="*", default=None)
    args = parser.parse_args(argv)

    import os
    import tempfile

    os.environ["AUTOMATRON_FAKE_LLM"] = "1" if args.mode == "fake" else "0"
    os.environ.setdefault("RUNTIME_DIR", tempfile.mkdtemp(prefix="automatron-eval-"))

    import automatron_core as core

    for module in (
        "automatron_space",
        "automatron_quant",
        "automatron_ecommerce",
        "automatron_realestate",
    ):
        try:
            __import__(module)
        except Exception:
            pass

    scenarios = load_scenarios(args.workflows)
    if not scenarios:
        print("no scenarios found")
        return 1

    passed_count = 0
    for scenario in scenarios:
        ok, checks = await run_one(scenario, core)
        passed_count += ok
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  {scenario['workflow_id']}")
        for name, check_ok, reason in checks:
            if not check_ok:
                print(f"        {name}: {reason}")

    await core.close_run_service()
    print(f"\n{passed_count}/{len(scenarios)} scenarios passed")
    return 0 if passed_count == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
