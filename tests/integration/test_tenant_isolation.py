"""One user can never see, stream, download, decide or replay another user's run.

Every route that takes a run id is exercised with a second, fully authenticated
user holding the first user's id. A run id is an identifier, not a credential:
someone else's run must be indistinguishable from one that does not exist.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

import automatron_core as core
from tests import supabase_fake, testsector
from tests.supabase_fake import bearer

API = core.API_PREFIX


@pytest.fixture
def tenants(tmp_path, monkeypatch):
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
        yield {
            "client": client,
            "fake": fake,
            "alice": bearer(fake.token("alice@example.com")),
            "bob": bearer(fake.token("bob@example.com")),
            "alice_id": alice,
            "bob_id": bob,
        }

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


def start(client, headers, **extra_headers):
    form = {
        "sector": "space",
        "workflow_id": testsector.WORKFLOW_ID,
        "request": "Assess probe-1.",
        "inputs_json": json.dumps({"subject": "probe-1"}),
    }
    response = client.post(f"{API}/runs", data=form, headers={**headers, **extra_headers})
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def to_gate(client, headers):
    thread_id = start(client, headers)
    for _ in range(100):
        view = client.get(f"{API}/runs/{thread_id}", headers=headers).json()
        if view["status"] in ("awaiting_approval", "failed"):
            assert view["status"] == "awaiting_approval", view
            return thread_id
        time.sleep(0.2)
    raise AssertionError("run never reached the gate")


def not_found_detail(client, headers, path):
    response = client.get(path, headers=headers)
    assert response.status_code == 404, response.text
    return response.json()["detail"]


class TestWithoutATokenThereIsNothing:
    def test_every_run_route_wants_a_bearer_token(self, tenants):
        client = tenants["client"]
        for method, path in (("get", f"{API}/runs"), ("get", f"{API}/runs/x"),
                             ("get", f"{API}/runs/x/events"), ("get", f"{API}/audit"),
                             ("post", f"{API}/runs")):
            response = getattr(client, method)(path)
            assert response.status_code == 401, (method, path)
            assert response.headers["www-authenticate"] == "Bearer"

    def test_basic_credentials_are_not_a_user(self, tenants):
        response = tenants["client"].get(f"{API}/runs", auth=("admin", "anything"))
        assert response.status_code == 401


class TestAnotherUsersRunDoesNotExist:
    def test_reading_it_looks_exactly_like_a_missing_run(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        foreign = not_found_detail(client, bob, f"{API}/runs/{thread_id}")
        missing = not_found_detail(client, bob, f"{API}/runs/{'0' * 32}")
        assert foreign.replace(thread_id, "ID") == missing.replace("0" * 32, "ID")

    def test_its_events_cannot_be_streamed(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        not_found_detail(client, bob, f"{API}/runs/{thread_id}/events")

    def test_its_brief_cannot_be_downloaded(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        assert client.get(f"{API}/runs/{thread_id}/brief.json", headers=alice).status_code == 200
        for kind in ("json", "md"):
            not_found_detail(client, bob, f"{API}/runs/{thread_id}/brief.{kind}")

    def test_it_cannot_be_decided_and_stays_waiting_for_its_owner(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        response = client.post(f"{API}/runs/{thread_id}/decision", headers=bob,
                               json={"action": "approve", "reviewer": "Bob"})
        assert response.status_code == 404
        view = client.get(f"{API}/runs/{thread_id}", headers=alice).json()
        assert view["status"] == "awaiting_approval"

    def test_it_is_not_in_their_list(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        assert [r["run_id"] for r in client.get(f"{API}/runs", headers=alice).json()] \
            == [thread_id]
        assert client.get(f"{API}/runs", headers=bob).json() == []

    def test_the_refusal_is_counted_for_the_operator(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        client.get(f"{API}/runs/{thread_id}", headers=bob)
        events = [e["event"] for e in core.ops_snapshot()["security"]]
        assert "cross_tenant_read_blocked" in events


class TestTheOwnerIsTheAuthenticatedUser:
    def test_a_run_belongs_to_whoever_started_it(self, tenants):
        client, alice = tenants["client"], tenants["alice"]
        thread_id = to_gate(client, alice)
        view = client.get(f"{API}/runs/{thread_id}", headers=alice).json()
        assert view["owner_id"] == tenants["alice_id"]

    def test_an_owner_named_in_the_form_is_ignored(self, tenants):
        client, bob = tenants["client"], tenants["bob"]
        form = {"sector": "space", "workflow_id": testsector.WORKFLOW_ID,
                "request": "Assess probe-1.", "owner_id": tenants["alice_id"],
                "inputs_json": json.dumps({"subject": "probe-1", "owner_id": tenants["alice_id"]})}
        thread_id = client.post(f"{API}/runs", data=form, headers=bob).json()["thread_id"]
        view = client.get(f"{API}/runs/{thread_id}", headers=bob).json()
        assert view["owner_id"] == tenants["bob_id"]

    def test_the_decision_is_audited_under_the_owner_and_the_principal(self, tenants):
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        decided = client.post(f"{API}/runs/{thread_id}/decision", headers=alice,
                              json={"action": "approve", "reviewer": "Someone Else"})
        assert decided.status_code == 200, decided.text
        entries = client.get(f"{API}/audit", headers=alice).json()
        assert [e["run_id"] for e in entries] == [thread_id]
        assert entries[0]["owner_id"] == tenants["alice_id"]
        # The typed name says one thing; the record also says who really signed.
        assert entries[0]["reviewer"] == "Someone Else"
        assert entries[0]["decided_by_principal"] == tenants["alice_id"]
        assert client.get(f"{API}/audit", headers=bob).json() == []
        assert client.get(f"{API}/audit", headers=bob,
                          params={"thread_id": thread_id}).json() == []


class TestReplayIsPerUser:
    def test_the_same_key_from_two_users_is_two_runs(self, tenants):
        """A shared idempotency key must never hand one user the other's run."""
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        key = {"Idempotency-Key": "same-key"}
        first = start(client, alice, **key)
        assert start(client, alice, **key) == first
        assert start(client, bob, **key) != first


class TestOwnershipSurvivesARestart:
    async def test_a_recovered_run_still_belongs_to_its_owner(self, tenants):
        """The run index is in memory and is lost on restart; the checkpoint is not.
        A run rebuilt from its checkpoint must come back with its owner, not as a run
        anyone can open."""
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        thread_id = to_gate(client, alice)
        core._RUNS.clear()
        not_found_detail(client, bob, f"{API}/runs/{thread_id}")
        core._RUNS.clear()
        view = client.get(f"{API}/runs/{thread_id}", headers=alice).json()
        assert view["owner_id"] == tenants["alice_id"]
        assert view["awaiting_approval"]


class TestSharedKnowledgeIsOperatorManaged:
    def test_a_user_cannot_write_to_the_shared_knowledge_base(self, tenants):
        response = tenants["client"].post(f"{API}/knowledge/ingest", headers=tenants["alice"],
                                          data={"sector": "space"})
        assert response.status_code == 403


class TestRateLimitsArePerUser:
    def test_one_user_spending_their_budget_leaves_the_other_theirs(self, tenants, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_IP_PER_HOUR", "1")
        core.reset_settings_cache()
        client, alice, bob = tenants["client"], tenants["alice"], tenants["bob"]
        start(client, alice)
        form = {"sector": "space", "workflow_id": testsector.WORKFLOW_ID, "request": "x"}
        assert client.post(f"{API}/runs", data=form, headers=alice).status_code == 429
        start(client, bob)


class TestTheInterfaceSignsInSupabaseUsers:
    async def test_a_signed_in_user_owns_their_interface_runs(self, tenants):
        assert await core.interface_login("alice@example.com", "correct horse")

        class Request:
            username = "alice@example.com"

        assert core.interface_owner(Request()) == tenants["alice_id"]

    async def test_a_wrong_password_is_refused(self, tenants):
        assert not await core.interface_login("alice@example.com", "wrong")

    def test_a_session_this_process_did_not_sign_in_owns_nothing(self, tenants):
        class Request:
            username = "mallory@example.com"

        with pytest.raises(PermissionError):
            core.interface_owner(Request())
        with pytest.raises(PermissionError):
            core.interface_owner(None)
