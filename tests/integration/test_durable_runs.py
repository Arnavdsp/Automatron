"""Runs in multi-user mode are recorded durably, sealed, and as the user who owns them.

The store here is the fake project's REST side, which refuses what the migration's
policies refuse. What reaches it is checked byte for byte: no request text, input
or brief may arrive in the clear, and what does arrive must only open for its own
run and owner.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

import automatron_core as core
from tests import supabase_fake, testsector
from tests.supabase_fake import bearer

API = core.API_PREFIX
REQUEST = "Assess probe-1. Confidential marker QX-7731."
SUBJECT = "probe-1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    fake = supabase_fake.install(core, monkeypatch)
    alice = fake.add_user("alice@example.com")
    bob = fake.add_user("bob@example.com")
    core.reset_rag_cache()
    core.reset_run_service()
    core.reset_rate_limits()
    core.reset_telemetry()
    testsector.install()
    with TestClient(core.create_app()) as client:
        yield {"client": client, "fake": fake, "alice_id": alice, "bob_id": bob,
               "alice": bearer(fake.token("alice@example.com")),
               "bob": bearer(fake.token("bob@example.com"))}
    core.clear_fake_script()
    core.clear_registry()
    core.reset_run_service()
    try:
        core.get_qdrant().close()
    except Exception:
        pass
    core.reset_rag_cache()
    core.reset_identity()
    core.reset_vault()
    core.reset_settings_cache()


def start(env, who="alice", **headers):
    form = {"sector": "space", "workflow_id": testsector.WORKFLOW_ID, "request": REQUEST,
            "inputs_json": json.dumps({"subject": SUBJECT})}
    return env["client"].post(f"{API}/runs", data=form, headers={**env[who], **headers})


def to_gate(env, who="alice"):
    response = start(env, who)
    assert response.status_code == 200, response.text
    thread_id = response.json()["thread_id"]
    for _ in range(100):
        view = env["client"].get(f"{API}/runs/{thread_id}", headers=env[who]).json()
        if view["status"] == "awaiting_approval":
            return thread_id, view
        time.sleep(0.2)
    raise AssertionError("run never reached the gate")


def row_of(env, thread_id):
    return env["fake"].runs[str(core.uuid.UUID(thread_id))]


def simulate_restart_without_checkpoint(monkeypatch):
    """A new instance: nothing in memory, and no checkpoint on its disk."""
    core._RUNS.clear()
    core._RUN_KEYS.clear()

    async def nothing_on_disk(run_id):
        return None

    monkeypatch.setattr(core, "_recover", nothing_on_disk)


async def opened(env, thread_id, field):
    row = row_of(env, thread_id)
    core._RUN_KEYS.clear()
    return await core.open_field(thread_id, env["alice_id"], row["key_id"], row["wrapped_key"],
                                 field, row[f"sealed_{field}"])


class TestARunIsRecordedBeforeItStarts:
    def test_the_record_is_created_as_the_user_in_their_organization(self, env):
        thread_id, _ = to_gate(env)
        row = row_of(env, thread_id)
        assert row["created_by"] == env["alice_id"]
        assert row["organization_id"] == env["fake"].organizations[env["alice_id"]]
        assert row["key_id"] == "local:k1"

    def test_nothing_readable_reaches_the_store(self, env):
        thread_id, view = to_gate(env)
        stored = json.dumps(row_of(env, thread_id))
        for secret in ("QX-7731", "Assess probe", SUBJECT, view["brief"]["summary"], "42.5"):
            assert secret not in stored

    async def test_what_was_asked_opens_for_its_owner(self, env):
        thread_id, _ = to_gate(env)
        assert (await opened(env, thread_id, "input"))["request"] == REQUEST

    def test_an_outage_means_no_run_rather_than_an_unrecorded_one(self, env):
        env["fake"].writes_fail = True
        response = start(env, **{"Idempotency-Key": "k-1"})
        assert response.status_code == 503
        assert core._RUNS == {}
        env["fake"].writes_fail = False
        # The key was not spent on the run that never started.
        retried = start(env, **{"Idempotency-Key": "k-1"})
        assert retried.status_code == 200 and "replayed" not in retried.json()


class TestTheOutcomeIsRecordedToo:
    async def test_the_gate_writes_status_and_the_sealed_brief(self, env):
        thread_id, view = to_gate(env)
        assert row_of(env, thread_id)["status"] == "awaiting_approval"
        result = await opened(env, thread_id, "result")
        assert result["brief"] == view["brief"]
        assert result["evaluation"]["passed"] is True

    async def test_a_missed_write_is_caught_up_by_the_next_request(self, env):
        thread_id, _ = to_gate(env)
        row = row_of(env, thread_id)
        row["status"], row["sealed_result"] = "running", None
        core._RUNS[thread_id]["persisted_status"] = "running"
        env["client"].get(f"{API}/runs/{thread_id}", headers=env["alice"])
        assert row["status"] == "awaiting_approval" and row["sealed_result"]

    async def test_the_decision_and_its_audit_entry_are_recorded(self, env):
        thread_id, _ = to_gate(env)
        decided = env["client"].post(f"{API}/runs/{thread_id}/decision", headers=env["alice"],
                                     json={"action": "approve", "reviewer": "Alice",
                                           "notes": "fine by QX-7731"})
        assert decided.status_code == 200, decided.text
        assert row_of(env, thread_id)["status"] == "approved"
        [entry] = env["fake"].audit
        local = env["client"].get(f"{API}/audit", headers=env["alice"]).json()[-1]
        assert entry["hash"] == local["hash"] and entry["prev_hash"] == local["prev_hash"]
        assert entry["payload"]["action"] == "approve"
        assert "QX-7731" not in json.dumps(entry) and "Alice" not in json.dumps(entry)
        row = row_of(env, thread_id)
        core._RUN_KEYS.clear()
        opened_entry = await core.open_field(
            thread_id, env["alice_id"], row["key_id"], row["wrapped_key"],
            f"audit:{entry['hash']}", entry["payload"]["sealed"])
        assert opened_entry["notes"] == "fine by QX-7731"


class TestARunOutlivesItsInstance:
    def test_the_brief_is_readable_on_an_instance_that_never_ran_it(self, env, monkeypatch):
        thread_id, view = to_gate(env)
        simulate_restart_without_checkpoint(monkeypatch)
        again = env["client"].get(f"{API}/runs/{thread_id}", headers=env["alice"])
        assert again.status_code == 200
        assert again.json()["brief"] == view["brief"]
        assert again.json()["status"] == "awaiting_approval"
        assert env["client"].get(f"{API}/runs/{thread_id}/brief.md",
                                 headers=env["alice"]).status_code == 200

    def test_it_cannot_be_decided_without_its_working_state(self, env, monkeypatch):
        thread_id, _ = to_gate(env)
        simulate_restart_without_checkpoint(monkeypatch)
        response = env["client"].post(f"{API}/runs/{thread_id}/decision", headers=env["alice"],
                                      json={"action": "approve", "reviewer": "Alice"})
        assert response.status_code == 409

    def test_it_is_still_nobody_elses(self, env, monkeypatch):
        thread_id, _ = to_gate(env)
        simulate_restart_without_checkpoint(monkeypatch)
        assert env["client"].get(f"{API}/runs/{thread_id}",
                                 headers=env["bob"]).status_code == 404

    def test_the_list_comes_from_the_store(self, env, monkeypatch):
        thread_id, _ = to_gate(env)
        simulate_restart_without_checkpoint(monkeypatch)
        listed = env["client"].get(f"{API}/runs", headers=env["alice"]).json()
        assert [r["run_id"] for r in listed] == [thread_id]
        assert env["client"].get(f"{API}/runs", headers=env["bob"]).json() == []


class TestCiphertextIsBoundToItsRun:
    def test_a_result_moved_onto_another_run_does_not_open(self, env, monkeypatch):
        """Someone with database access copies one run's sealed brief onto another
        run's row. It must not be shown as that run's brief."""
        first, _ = to_gate(env)
        second, _ = to_gate(env)
        row_of(env, second)["sealed_result"] = row_of(env, first)["sealed_result"]
        simulate_restart_without_checkpoint(monkeypatch)
        assert env["client"].get(f"{API}/runs/{second}", headers=env["alice"]).status_code == 404
        assert env["client"].get(f"{API}/runs/{first}", headers=env["alice"]).status_code == 200

    def test_an_altered_record_does_not_open(self, env, monkeypatch):
        thread_id, _ = to_gate(env)
        row = row_of(env, thread_id)
        row["sealed_result"] = row["sealed_result"][:-3] + "AAA"
        simulate_restart_without_checkpoint(monkeypatch)
        assert env["client"].get(f"{API}/runs/{thread_id}",
                                 headers=env["alice"]).status_code == 404


class TestTheStoreIsWatched:
    def test_writes_are_counted_for_the_dashboard(self, env):
        to_gate(env)
        text = core.telemetry().exposition()[0].decode()
        assert 'automatron_store_writes_total{outcome="ok"}' in text
