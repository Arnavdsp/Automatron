"""The REST API, exercised through a test client against the scripted model."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import automatron_core as core
from tests import testsector

API = core.API_PREFIX


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    # An empty data dir: startup seeding has nothing to do, so each test does not
    # re-index the whole bundled knowledge base.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_run_service()
    core.reset_rate_limits()
    testsector.install()

    with TestClient(core.create_app()) as test_client:
        yield test_client

    core.clear_fake_script()
    core.clear_registry()
    core.reset_run_service()
    try:
        core.get_qdrant().close()
    except Exception:
        pass
    core.reset_rag_cache()
    core.reset_settings_cache()


def start(client, **overrides):
    form = {
        "sector": "space",
        "workflow_id": testsector.WORKFLOW_ID,
        "request": "Assess probe-1.",
        "inputs_json": json.dumps({"subject": "probe-1"}),
    }
    form.update(overrides)
    return client.post(f"{API}/runs", data=form)


def run_to_gate(client):
    response = start(client)
    assert response.status_code == 200, response.text
    thread_id = response.json()["thread_id"]
    # The run continues in the background after the POST returns, so poll with a
    # pause rather than spinning: a tight loop finishes before the graph does.
    for _ in range(100):
        view = client.get(f"{API}/runs/{thread_id}").json()
        if view["status"] in ("awaiting_approval", "failed"):
            return thread_id, view
        time.sleep(0.2)
    raise AssertionError(f"run never settled; last status {view['status']}")


class TestDiscovery:
    def test_health_lists_registered_sectors(self, client):
        body = client.get(f"{API}/health").json()
        assert body["status"] == "ok"
        assert body["fake_mode"] is True
        assert body["sectors"] == ["space"]
        assert body["version"]

    def test_providers_reports_state_without_leaking_keys(self, client):
        rows = client.get(f"{API}/providers").json()
        assert rows
        for row in rows:
            assert set(row) >= {"name", "provider", "model", "state", "calls_today"}
            assert "api_key" not in row

    def test_sectors_describe_their_workflows(self, client):
        sectors = client.get(f"{API}/sectors").json()
        assert [s["id"] for s in sectors] == ["space"]
        workflow = sectors[0]["workflows"][0]
        assert workflow["id"] == testsector.WORKFLOW_ID
        assert "subject" in workflow["inputs"]
        assert sectors[0]["display_name"] == "Automatron Space"

    def test_sample_endpoint_returns_inputs(self, client):
        body = client.get(f"{API}/sectors/space/workflows/{testsector.WORKFLOW_ID}/sample").json()
        assert body["request"] == "Assess probe-1."
        assert "subject" in body["inputs"]

    def test_unknown_workflow_sample_is_a_problem_document(self, client):
        response = client.get(f"{API}/sectors/space/workflows/space.nope/sample")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["title"] == "unknown workflow"


class TestRuns:
    def test_a_run_reaches_the_gate(self, client):
        _, view = run_to_gate(client)
        assert view["status"] == "awaiting_approval"
        assert view["awaiting_approval"] is True
        assert view["brief"]["recommendation_level"] == "RED"

    def test_trace_is_returned(self, client):
        _, view = run_to_gate(client)
        assert {e["node"] for e in view["trace"]} >= {"intake", "plan", "synthesize"}

    def test_brief_downloads_in_both_formats(self, client):
        thread_id, _ = run_to_gate(client)

        as_json = client.get(f"{API}/runs/{thread_id}/brief.json")
        assert as_json.status_code == 200
        assert as_json.json()["workflow_id"] == testsector.WORKFLOW_ID

        as_md = client.get(f"{API}/runs/{thread_id}/brief.md")
        assert as_md.status_code == 200
        assert "Decision support" in as_md.text

    def test_approve_finalises_the_run(self, client):
        thread_id, _ = run_to_gate(client)
        response = client.post(
            f"{API}/runs/{thread_id}/decision",
            json={"action": "approve", "reviewer": "Arnav", "notes": "ok"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_a_decision_without_a_reviewer_is_rejected(self, client):
        thread_id, _ = run_to_gate(client)
        response = client.post(
            f"{API}/runs/{thread_id}/decision",
            json={"action": "approve", "reviewer": "   "},
        )
        assert response.status_code == 422

    def test_deciding_twice_conflicts(self, client):
        thread_id, _ = run_to_gate(client)
        client.post(
            f"{API}/runs/{thread_id}/decision", json={"action": "approve", "reviewer": "Arnav"}
        )
        again = client.post(
            f"{API}/runs/{thread_id}/decision", json={"action": "reject", "reviewer": "Arnav"}
        )
        assert again.status_code == 409

    def test_unknown_run_is_a_problem_document(self, client):
        response = client.get(f"{API}/runs/does-not-exist")
        assert response.status_code == 404
        assert "Run expired" in response.json()["detail"]

    def test_invalid_inputs_json_is_refused(self, client):
        response = start(client, inputs_json="{not json")
        assert response.status_code == 400
        assert response.json()["title"] == "invalid inputs_json"

    def test_unknown_sector_is_refused(self, client):
        response = start(client, sector="aviation")
        assert response.status_code == 400

    def test_events_stream_ends(self, client):
        thread_id, _ = run_to_gate(client)
        with client.stream("GET", f"{API}/runs/{thread_id}/events") as stream:
            assert stream.status_code == 200
            body = "".join(chunk for chunk in stream.iter_text())
        assert "data:" in body
        assert "event: end" in body


class TestUploads:
    def test_an_unsupported_file_type_is_refused(self, client):
        response = client.post(
            f"{API}/runs",
            data={
                "sector": "space",
                "workflow_id": testsector.WORKFLOW_ID,
                "request": "x",
                "inputs_json": "{}",
            },
            files={"files": ("payload.exe", b"binary", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert response.json()["title"] == "unsupported file type"

    def test_too_many_files_is_refused(self, client):
        files = [("files", (f"note{i}.md", b"hello", "text/markdown")) for i in range(6)]
        response = client.post(
            f"{API}/runs",
            data={
                "sector": "space",
                "workflow_id": testsector.WORKFLOW_ID,
                "request": "x",
                "inputs_json": "{}",
            },
            files=files,
        )
        assert response.status_code == 400
        assert response.json()["title"] == "too many files"

    def test_an_oversized_file_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_MB", "0")
        core.reset_settings_cache()
        response = client.post(
            f"{API}/runs",
            data={
                "sector": "space",
                "workflow_id": testsector.WORKFLOW_ID,
                "request": "x",
                "inputs_json": "{}",
            },
            files={"files": ("note.md", b"hello world", "text/markdown")},
        )
        assert response.status_code == 400
        assert response.json()["title"] == "file too large"


class TestRateLimiting:
    def test_runs_are_capped_per_address(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_IP_PER_HOUR", "2")
        core.reset_settings_cache()
        core.reset_rate_limits()

        assert start(client).status_code == 200
        assert start(client).status_code == 200
        blocked = start(client)
        assert blocked.status_code == 429
        assert blocked.json()["title"] == "too many runs"

    def test_the_forwarded_address_is_used_behind_a_proxy(self):
        class Request:
            headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
            client = type("C", (), {"host": "10.0.0.1"})()

        assert core.client_ip(Request()) == "203.0.113.7"

    def test_a_zero_limit_disables_the_cap(self):
        core.reset_rate_limits()
        assert all(core.rate_limit_ok("1.2.3.4", limit_per_hour=0) for _ in range(50))


class TestAuth:
    def test_a_password_protects_every_route(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
        monkeypatch.setenv("APP_PASSWORD", "letmein")
        monkeypatch.setenv("APP_USERNAME", "arnav")
        core.reset_settings_cache()
        core.reset_run_service()
        testsector.install()

        with TestClient(core.create_app()) as guarded:
            assert guarded.get(f"{API}/providers").status_code == 401
            ok = guarded.get(f"{API}/providers", auth=("arnav", "letmein"))
            assert ok.status_code == 200
            wrong = guarded.get(f"{API}/providers", auth=("arnav", "nope"))
            assert wrong.status_code == 401

        core.clear_registry()
        core.reset_run_service()
        core.reset_settings_cache()
