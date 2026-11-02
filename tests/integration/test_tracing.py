"""A run is traced from its request to its last tool call, without carrying content.

Spans go to an in-memory exporter here; in a deployment they go over OTLP to a
collector and on to Tempo or Cloud Trace. What is checked is the shape a person
debugging a slow or failed run relies on: one trace per leg, the graph's nodes,
each step, each model attempt and each tool call inside it.
"""

import json
import logging

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import automatron_core as core
from tests import testsector

REQUEST = "Assess probe-1. Confidential marker QX-7731."

_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def provider():
    """One provider for the module: OpenTelemetry allows setting it once a process."""
    current = otel_trace.get_tracer_provider()
    if not isinstance(current, TracerProvider):
        installed = TracerProvider()
        installed.add_span_processor(SimpleSpanProcessor(_EXPORTER))
        otel_trace.set_tracer_provider(installed)
    else:
        current.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    yield


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_run_service()
    core.reset_telemetry()
    testsector.install()
    _EXPORTER.clear()
    yield
    await core.close_run_service()
    core.clear_fake_script()
    core.clear_registry()
    core.reset_settings_cache()


async def traced_run():
    with core.tracer().start_as_current_span("POST /api/v1/runs") as request_span:
        run_id = await core.start_run("space", testsector.WORKFLOW_ID, REQUEST,
                                      {"subject": "probe-1"})
    await core.wait_for_run(run_id)
    return run_id, request_span, await core.get_run(run_id)


def spans_named(prefix):
    return [s for s in _EXPORTER.get_finished_spans() if s.name.startswith(prefix)]


class TestARunIsOneTrace:
    async def test_the_leg_is_a_root_span_linked_to_the_request(self, env):
        run_id, request_span, view = await traced_run()
        [leg] = spans_named("run ")
        assert leg.parent is None
        assert [link.context.span_id for link in leg.links] == \
            [request_span.get_span_context().span_id]
        assert leg.attributes["automatron.run_id"] == run_id
        assert leg.attributes["automatron.status"] == "awaiting_approval"
        assert leg.attributes["automatron.eval_score"] == 1.0
        assert view.trace_id == otel_trace.format_trace_id(leg.context.trace_id)

    async def test_nodes_steps_model_calls_and_tools_hang_off_it(self, env):
        await traced_run()
        [leg] = spans_named("run ")
        in_trace = [s for s in _EXPORTER.get_finished_spans()
                    if s.context.trace_id == leg.context.trace_id]
        names = {s.name for s in in_trace}
        assert {"node intake", "node plan", "node run_step", "node synthesize",
                "node verify", "node human_gate"} <= names
        assert any(n.startswith("step ") for n in names)
        assert {"tool measure", "tool classify"} <= names
        calls = [s for s in in_trace if s.name.startswith("llm ")]
        assert calls and all(s.attributes["automatron.outcome"] == "ok" for s in calls)
        assert all(s.attributes["gen_ai.system"] and s.attributes["gen_ai.request.model"]
                   for s in calls)
        assert all("automatron.rate_limit_wait_ms" in s.attributes for s in calls)

    async def test_a_model_call_sits_inside_its_step(self, env):
        await traced_run()
        steps = {s.context.span_id: s for s in spans_named("step ")}
        calls = spans_named("llm ")
        assert any(c.parent and c.parent.span_id in steps for c in calls)

    async def test_pausing_for_the_reviewer_is_not_an_error(self, env):
        await traced_run()
        [gate] = spans_named("node human_gate")
        assert gate.attributes["langgraph.interrupted"] is True
        assert gate.status.status_code != otel_trace.StatusCode.ERROR

    async def test_the_decision_is_its_own_trace(self, env):
        run_id, _, _ = await traced_run()
        await core.submit_decision(run_id, {"action": "approve", "reviewer": "Ana"})
        [decision] = spans_named("decision ")
        [leg] = spans_named("run ")
        assert decision.context.trace_id != leg.context.trace_id
        assert decision.attributes["automatron.status"] == "approved"


class TestFailuresShowWhereTheyHappened:
    async def test_a_failover_reads_as_a_failed_attempt_then_a_good_one(self, env):
        router = core.get_router()
        first = router.chain("analyst")[0].name
        router.force_error(first, core.RATE_LIMIT, retry_after=5)
        try:
            await traced_run()
        finally:
            router.force_error(first, None)
        calls = spans_named("llm ")
        failed = [s for s in calls if s.attributes.get("automatron.outcome") == "rate_limit"]
        assert failed and all(s.status.status_code == otel_trace.StatusCode.ERROR
                              for s in failed)
        assert any(s.attributes.get("automatron.outcome") == "ok" for s in calls)


class TestNothingSensitiveIsTraced:
    async def test_no_span_carries_the_request_or_its_inputs(self, env):
        await traced_run()
        for span in _EXPORTER.get_finished_spans():
            dumped = json.dumps({k: str(v) for k, v in (span.attributes or {}).items()})
            assert "QX-7731" not in dumped and "Assess probe" not in dumped, span.name


class TestSignalsAreJoined:
    async def test_a_log_line_written_in_a_span_names_its_trace(self, env):
        with core.tracer().start_as_current_span("work") as span:
            record = logging.LogRecord("automatron", logging.INFO, __file__, 1, "hello",
                                       None, None)
            line = json.loads(core.JsonFormatter().format(record))
        assert line["trace_id"] == otel_trace.format_trace_id(span.get_span_context().trace_id)
        assert line["span_id"] == otel_trace.format_span_id(span.get_span_context().span_id)

    async def test_a_latency_sample_points_at_a_trace(self, env):
        """Exemplars let a dashboard jump from a slow bucket to a trace in it. They
        exist only in OpenMetrics, which Prometheus asks for when it can store them."""
        await traced_run()
        openmetrics, kind = core.telemetry().exposition(openmetrics=True)
        assert kind.startswith("application/openmetrics-text")
        lines = [line for line in openmetrics.decode().splitlines()
                 if line.startswith("automatron_provider_latency_seconds_bucket")
                 and "trace_id=" in line]
        assert lines
        classic, _ = core.telemetry().exposition()
        assert "trace_id=" not in classic.decode()

    def test_without_a_collector_nothing_is_exported(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
        monkeypatch.setattr(core, "_TRACING_READY", False)
        assert core.setup_tracing() is False
