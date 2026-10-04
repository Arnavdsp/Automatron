"""The operations plane: Prometheus metrics, the dashboard snapshot, and who may see them."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import automatron_core as core
from tests import supabase_fake, testsector

API = core.API_PREFIX
OPERATOR = ("admin", "operator-password-123")


def make_client(tmp_path, monkeypatch, password=OPERATOR[1]):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
    if password:
        monkeypatch.setenv("APP_PASSWORD", password)
    else:
        monkeypatch.delenv("APP_PASSWORD", raising=False)
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_run_service()
    core.reset_rate_limits()
    core.reset_telemetry()
    testsector.install()
    return TestClient(core.create_app())


@pytest.fixture
def ops(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        yield client
    teardown()


def teardown():
    core.clear_fake_script()
    core.clear_registry()
    core.reset_run_service()
    try:
        core.get_qdrant().close()
    except Exception:
        pass
    core.reset_rag_cache()
    core.reset_identity()
    core.reset_settings_cache()


def finish_a_run(client):
    form = {"sector": "space", "workflow_id": testsector.WORKFLOW_ID,
            "request": "Assess probe-1.", "inputs_json": json.dumps({"subject": "probe-1"})}
    thread_id = client.post(f"{API}/runs", data=form, auth=OPERATOR).json()["thread_id"]
    for _ in range(100):
        view = client.get(f"{API}/runs/{thread_id}", auth=OPERATOR).json()
        if view["status"] == "awaiting_approval":
            return thread_id, view
        time.sleep(0.2)
    raise AssertionError("run never reached the gate")


class TestOnlyTheOperatorSeesIt:
    @pytest.mark.parametrize("path", ["/metrics", "/ops", "/ops/api/snapshot"])
    def test_it_wants_the_operator_credential(self, ops, path):
        assert ops.get(path).status_code == 401
        assert ops.get(path, auth=("admin", "wrong")).status_code == 401
        assert ops.get(path, auth=OPERATOR).status_code == 200

    def test_only_a_wrong_credential_counts_as_a_security_event(self, ops):
        """A browser always asks once without credentials before the Basic prompt;
        counting that would fill the dashboard with page loads."""
        ops.get("/ops")
        ops.get(f"{API}/runs/x")
        assert core.ops_snapshot()["totals"]["security_events"] == 0
        ops.get("/ops", auth=("admin", "wrong"))
        ops.get(f"{API}/runs/x", auth=("admin", "wrong"))
        events = [e["event"] for e in core.ops_snapshot()["security"]]
        assert events == ["operator_auth_failed", "api_auth_failed"]

    def test_a_signed_in_user_is_not_an_operator(self, tmp_path, monkeypatch):
        """The dashboard shows every tenant's run metadata, so a user's own token,
        however valid, does not open it."""
        fake = supabase_fake.install(core, monkeypatch)
        fake.add_user("alice@example.com")
        with make_client(tmp_path, monkeypatch) as client:
            token = supabase_fake.bearer(fake.token("alice@example.com"))
            assert client.get("/ops/api/snapshot", headers=token).status_code == 401
            assert client.get("/metrics", headers=token).status_code == 401
            assert client.get("/metrics", auth=OPERATOR).status_code == 200
        teardown()

    def test_multi_user_mode_without_an_operator_password_keeps_it_closed(
            self, tmp_path, monkeypatch):
        supabase_fake.install(core, monkeypatch)
        with make_client(tmp_path, monkeypatch, password=None) as client:
            assert client.get("/ops").status_code == 403
        teardown()


class TestARunIsMeasured:
    def test_the_metrics_count_the_run_its_calls_and_its_tools(self, ops):
        finish_a_run(ops)
        text = ops.get("/metrics", auth=OPERATOR).text
        assert 'automatron_runs_started_total{sector="space",workflow="space.probe"} 1.0' in text
        assert 'outcome="awaiting_approval"' in text
        assert "automatron_provider_calls_total" in text
        assert 'automatron_tool_calls_total{outcome="ok",tool="measure"}' in text
        assert 'automatron_eval_checks_total{check="grounding",result="pass"}' in text
        assert "automatron_active_runs 0.0" in text

    def test_http_routes_are_labelled_by_template_not_by_run(self, ops):
        """A label per run id would grow the metric without bound."""
        thread_id, _ = finish_a_run(ops)
        text = ops.get("/metrics", auth=OPERATOR).text
        assert 'route="/api/v1/runs/{thread_id}"' in text
        assert thread_id not in text

    def test_every_response_carries_a_request_id(self, ops):
        response = ops.get(f"{API}/health", headers={"X-Request-ID": "trace-me"})
        assert response.headers["x-request-id"] == "trace-me"
        assert ops.get(f"{API}/health").headers["x-request-id"]

    def test_the_run_is_scored_and_the_score_is_on_its_view(self, ops):
        _, view = finish_a_run(ops)
        assert view["evaluation"]["passed"] is True
        assert view["evaluation"]["score"] == 1.0


class TestTheDashboardSnapshot:
    def test_it_reports_the_run_with_its_latency_and_score(self, ops):
        finish_a_run(ops)
        snapshot = ops.get("/ops/api/snapshot", auth=OPERATOR).json()
        assert snapshot["totals"]["runs"] == 1
        assert snapshot["active_runs"] == 0
        assert snapshot["latency"]["time_to_brief_p50_s"] is not None
        assert snapshot["evaluation"]["runs_scored"] == 1
        assert snapshot["evaluation"]["mean_score"] == 1.0
        assert sum(snapshot["series"]["runs_per_minute"]) == 1
        run = snapshot["recent_runs"][0]
        assert run["workflow_id"] == "space.probe" and run["eval_passed"] is True
        assert {t["tool"] for t in snapshot["tools"]} >= {"measure", "classify"}
        assert {p["provider"] for p in snapshot["providers"]}

    def test_it_carries_no_user_content_and_no_user_id(self, ops):
        thread_id, view = finish_a_run(ops)
        raw = ops.get("/ops/api/snapshot", auth=OPERATOR).text
        assert "Assess probe-1" not in raw
        assert view["brief"]["summary"] not in raw
        assert core.LOCAL_TENANT not in json.loads(raw)["recent_runs"][0]["owner"]

    def test_the_page_renders_its_sections(self, ops):
        page = ops.get("/ops", auth=OPERATOR).text
        for section in ("Providers", "Online evaluation", "Recent runs",
                        "Offline evaluation suites", "Security events"):
            assert section in page
        assert "/ops/api/snapshot" in page

    def test_offline_suites_appear_once_recorded(self, ops):
        core.record_eval_suite({"finished_at": "2026-10-04T10:00:00+00:00", "mode": "fake",
                                "passed": 12, "total": 12, "mean_score": 1.0})
        suites = ops.get("/ops/api/snapshot", auth=OPERATOR).json()["eval_suites"]
        assert suites[-1]["passed"] == 12


class TestPercentiles:
    def test_nearest_rank(self):
        values = [float(v) for v in range(1, 101)]
        assert core.percentile(values, 0.5) == 50.0
        assert core.percentile(values, 0.95) == 95.0
        assert core.percentile([], 0.5) is None
        assert core.percentile([3.0], 0.95) == 3.0
