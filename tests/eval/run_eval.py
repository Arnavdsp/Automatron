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


def load_scenarios(only: list[str] | None) -> list[dict]:
    scenarios = []
    for path in sorted(GOLDEN.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not only or scenario["workflow_id"] in only:
            scenarios.append(scenario)
    return scenarios


def score(scenario: dict, view, core) -> list[tuple[str, bool, str]]:
    """Each check returns its name, whether it passed, and a short reason.

    The checks themselves live in the core module, where they also score every
    live run; this adds only the scenario's own expectations.
    """
    report = core.evaluate_run(view, expect=scenario["expect"])
    return [(c["name"], c["passed"], c["detail"]) for c in report["checks"]]


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
    parser.add_argument("--out", type=pathlib.Path, default=None,
                        help="also write the full result as JSON to this path")
    parser.add_argument("--no-record", action="store_true",
                        help="do not append this suite to the dashboard's history")
    parser.add_argument("--history", type=pathlib.Path, default=None,
                        help="history file to append to; defaults to the runtime directory's. "
                             "Point it at a running server's file to show the suite there, "
                             "since the suite cannot share that server's runtime directory")
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

    # The app seeds the knowledge base at startup, so a run that skips it is not
    # measuring the system anyone deploys: every retrieval misses, and the briefs
    # come back hedged because the researcher found nothing.
    indexed = core.seed_knowledge()
    if not sum(indexed.values()):
        print("warning: knowledge base is empty; retrieval-backed checks will be weak")
    else:
        print(f"knowledge base ready: {indexed}")

    started = core.utcnow_iso()
    passed_count = 0
    results = []
    for scenario in scenarios:
        ok, checks = await run_one(scenario, core)
        passed_count += ok
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  {scenario['workflow_id']}")
        for name, check_ok, reason in checks:
            if not check_ok:
                print(f"        {name}: {reason}")
        results.append({
            "workflow_id": scenario["workflow_id"],
            "passed": ok,
            "score": round(sum(c[1] for c in checks) / len(checks), 3) if checks else 0.0,
            "failed_checks": {name: reason for name, check_ok, reason in checks if not check_ok},
        })

    await core.close_run_service()
    suite = {
        "started_at": started,
        "finished_at": core.utcnow_iso(),
        "mode": args.mode,
        "passed": passed_count,
        "total": len(scenarios),
        "mean_score": round(sum(r["score"] for r in results) / len(results), 3),
        "scenarios": results,
    }
    if not args.no_record:
        core.record_eval_suite(suite, path=args.history)
    if args.out:
        args.out.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    print(f"\n{passed_count}/{len(scenarios)} scenarios passed")
    return 0 if passed_count == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
