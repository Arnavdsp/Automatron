"""Anyone can create an account, sign in, and reach only their own work.

The browser holds one thing: an encrypted, HttpOnly session cookie. Everything
about an account lives with Supabase Auth, which the fake project stands in for
here, while the tokens are verified exactly as production verifies them.
"""

import time

import pytest
from fastapi.testclient import TestClient

import automatron_core as core
from tests import supabase_fake, testsector

ORIGIN = {"Origin": "http://testserver"}
GOOD_PASSWORD = "harbour-lights-42"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    fake = supabase_fake.install(core, monkeypatch)
    core.reset_rag_cache()
    core.reset_run_service()
    core.reset_rate_limits()
    core.reset_telemetry()
    testsector.install()
    with TestClient(core.create_app()) as client:
        yield client, fake
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


def post(client, path, body, headers=None):
    return client.post(path, json=body, headers={**ORIGIN, **(headers or {})})


def sign_up(client, email="new@example.com", password=GOOD_PASSWORD, name="New Person"):
    return post(client, "/auth/sign-up",
                {"email": email, "password": password, "display_name": name})


def page(client):
    return client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)


def replace_cookie(client, value):
    client.cookies.clear()
    client.cookies.set(core.SESSION_COOKIE, value)


def cookie_of(response):
    return response.headers.get("set-cookie", "")


class TestTheInterfaceIsForSignedInPeople:
    def test_a_visitor_is_sent_to_sign_in(self, site):
        client, _ = site
        response = page(client)
        assert response.status_code == 303 and response.headers["location"] == "/login"

    def test_the_interface_api_refuses_a_visitor(self, site):
        client, _ = site
        assert client.get("/gradio_api/info").status_code in (401, 403)

    def test_the_sign_in_page_is_locked_down(self, site):
        client, _ = site
        response = client.get("/login")
        assert response.status_code == 200
        assert "Create account" in response.text and "Forgot your password?" in response.text
        policy = response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in policy and "'unsafe-inline'" not in policy
        nonce = policy.split("'nonce-")[1].split("'")[0]
        assert f'nonce="{nonce}"' in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"


class TestCreatingAnAccount:
    def test_a_new_account_is_signed_straight_in(self, site):
        client, fake = site
        response = sign_up(client)
        assert response.status_code == 200 and response.json()["next"] == "/"
        cookie = cookie_of(response)
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert page(client).status_code == 200
        me = client.get("/auth/me").json()
        assert me["email"] == "new@example.com" and me["display_name"] == "New Person"

    def test_the_cookie_carries_no_readable_token(self, site):
        client, _ = site
        sign_up(client)
        value = client.cookies.get(core.SESSION_COOKIE)
        assert value and "eyJ" not in value and "new@example.com" not in value

    def test_behind_https_the_cookie_is_host_locked_and_secure(self, site):
        client, _ = site
        response = post(
            client, "/auth/sign-up",
            {"email": "tls@example.com", "password": GOOD_PASSWORD},
            {"X-Forwarded-Proto": "https"})
        cookie = cookie_of(response)
        assert cookie.startswith(f"{core.SECURE_SESSION_COOKIE}=") and "Secure" in cookie

    def test_an_address_that_already_has_an_account_is_not_revealed(self, site):
        """The answer for a taken address is the answer for one awaiting
        confirmation, so sign-up cannot be used to discover who is registered."""
        client, fake = site
        fake.add_user("taken@example.com")
        fake.confirm_email = True
        taken = sign_up(client, email="taken@example.com")
        pending = sign_up(client, email="fresh@example.com")
        assert taken.status_code == pending.status_code == 202
        assert taken.json() == pending.json()
        assert core.SESSION_COOKIE not in cookie_of(taken)

    @pytest.mark.parametrize("password, reason", [
        ("short1!", "at least"),
        ("onlyletterspassword", "digit or symbol"),
        ("newperson-2024", "email address"),
        ("x" * 70 + "é1", "at most"),
    ])
    def test_a_weak_password_is_refused_with_a_reason(self, site, password, reason):
        client, _ = site
        response = sign_up(client, email="newperson@example.com", password=password)
        assert response.status_code == 400 and reason in response.json()["message"]

    def test_a_password_the_provider_knows_is_common_is_refused(self, site):
        client, _ = site
        response = sign_up(client, password="qwertyuiop1")
        assert response.status_code == 400 and "easy to guess" in response.json()["message"]

    def test_a_malformed_address_is_refused(self, site):
        client, _ = site
        assert sign_up(client, email="not-an-address").status_code == 400


class TestSigningIn:
    def test_the_right_password_signs_in(self, site):
        client, fake = site
        fake.add_user("alice@example.com", GOOD_PASSWORD)
        response = post(client, "/auth/sign-in",
                        {"email": "alice@example.com", "password": GOOD_PASSWORD})
        assert response.status_code == 200
        assert page(client).status_code == 200

    def test_a_wrong_password_and_an_unknown_address_look_the_same(self, site):
        client, fake = site
        fake.add_user("alice@example.com", GOOD_PASSWORD)
        wrong = post(client, "/auth/sign-in", {"email": "alice@example.com", "password": "nope"})
        unknown = post(client, "/auth/sign-in", {"email": "ghost@example.com", "password": "x"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_guessing_one_accounts_password_is_slowed(self, site):
        client, fake = site
        fake.add_user("alice@example.com", GOOD_PASSWORD)
        codes = [post(client, "/auth/sign-in",
                      {"email": "alice@example.com", "password": f"guess{i}"}).status_code
                 for i in range(core.AUTH_ATTEMPTS_PER_EMAIL + 1)]
        assert codes[-1] == 429
        # Even the right password waits out the window.
        assert post(client, "/auth/sign-in", {"email": "alice@example.com",
                                              "password": GOOD_PASSWORD}).status_code == 429

    def test_a_sign_in_is_recorded_without_the_raw_address(self, site):
        client, fake = site
        user = fake.add_user("alice@example.com", GOOD_PASSWORD)
        post(client, "/auth/sign-in", {"email": "alice@example.com", "password": GOOD_PASSWORD},
             {"User-Agent": "Mozilla/5.0 (test)"})
        [event] = fake.sign_ins
        assert event["user_id"] == user and event["method"] == "password"
        assert event["user_agent"] == "Mozilla/5.0 (test)"
        # The test client's address is "testclient"; an unkeyed hash of an address
        # can be reversed by hashing every address, so it must not be what is stored.
        assert event["address_hash"] != core.hashlib.sha256(b"testclient").hexdigest()
        assert len(event["address_hash"]) == 64


class TestRequestsFromElsewhereAreRefused:
    def test_a_cross_site_post_is_refused(self, site):
        """A hostile page must not be able to sign a visitor into an attacker's
        account, or out of their own."""
        client, fake = site
        fake.add_user("alice@example.com", GOOD_PASSWORD)
        response = client.post("/auth/sign-in", json={"email": "alice@example.com",
                                                      "password": GOOD_PASSWORD},
                               headers={"Origin": "https://evil.example"})
        assert response.status_code == 400
        assert core.SESSION_COOKIE not in cookie_of(response)
        assert "auth_cross_origin_refused" in [e["event"] for e in core.ops_snapshot()["security"]]

    def test_a_plain_form_post_is_refused(self, site):
        client, _ = site
        response = client.post("/auth/sign-in", data={"email": "a@b.co", "password": "x"},
                               headers=ORIGIN)
        assert response.status_code == 400


class TestTheSessionCookie:
    def test_an_altered_cookie_is_a_signed_out_visitor(self, site):
        client, _ = site
        sign_up(client)
        value = client.cookies.get(core.SESSION_COOKIE)
        replace_cookie(client, value[:-4] + "AAAA")
        response = page(client)
        assert response.status_code == 303
        assert f"{core.SESSION_COOKIE}=" in cookie_of(response)  # cleared

    def test_a_session_ends_a_week_after_sign_in_however_often_it_is_used(self, site):
        client, _ = site
        sign_up(client)
        session = core.open_session(client.cookies.get(core.SESSION_COOKIE))
        old = session.model_copy(update={"started": time.time() - core.SESSION_MAX_AGE_S - 1})
        replace_cookie(client, core.seal_session(old))
        assert page(client).status_code == 303

    def test_a_token_near_expiry_is_refreshed_and_the_cookie_rotated(self, site):
        client, _ = site
        sign_up(client)
        session = core.open_session(client.cookies.get(core.SESSION_COOKIE))
        stale = session.model_copy(update={"access_expires": time.time() + 10})
        replace_cookie(client, core.seal_session(stale))
        response = page(client)
        assert response.status_code == 200
        renewed = core.open_session(response.cookies.get(core.SESSION_COOKIE))
        assert renewed.refresh_token != session.refresh_token
        assert renewed.started == session.started

    def test_signing_out_ends_the_session_everywhere(self, site):
        client, fake = site
        sign_up(client)
        copied = client.cookies.get(core.SESSION_COOKIE)
        response = client.post("/auth/sign-out", headers=ORIGIN, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
        assert fake.logouts and not fake.refresh_tokens
        # A copy of the cookie kept from before can no longer be refreshed.
        stale = core.open_session(copied).model_copy(update={"access_expires": 0})
        assert core.asyncio.run(core.supabase_verifier().refresh(stale.refresh_token)) is None


class TestEmailLinks:
    def test_a_reset_request_says_the_same_thing_for_any_address(self, site):
        client, fake = site
        fake.add_user("alice@example.com")
        known = post(client, "/auth/recover", {"email": "alice@example.com"})
        unknown = post(client, "/auth/recover", {"email": "ghost@example.com"})
        assert known.json() == unknown.json() and known.status_code == 202
        assert fake.recovery_requests == ["alice@example.com", "ghost@example.com"]

    def test_a_reset_link_sets_the_password_and_signs_in(self, site):
        client, fake = site
        user = fake.add_user("alice@example.com", "old-password-1")
        tokens = fake.session_for("alice@example.com")
        response = post(client, "/auth/from-link", {**tokens, "new_password": GOOD_PASSWORD})
        assert response.status_code == 200 and fake.password_changes == [user]
        assert page(client).status_code == 200

    def test_a_forged_link_is_refused(self, site):
        client, _ = site
        response = post(client, "/auth/from-link", {"access_token": "eyJforged.x.y"})
        assert response.status_code == 401


class TestTheInterfaceKnowsWhoIsAsking:
    """Handlers read the owner from the session cookie on the event's request."""

    def request_with(self, cookie, username):
        from gradio.route_utils import Request

        return Request(cookies={core.SESSION_COOKIE: cookie} if cookie else {},
                       username=username)

    def test_the_owner_is_the_signed_in_user(self, site):
        client, fake = site
        sign_up(client)
        user = fake.users["new@example.com"]["id"]
        cookie = client.cookies.get(core.SESSION_COOKIE)
        assert core.interface_owner(self.request_with(cookie, user)) == user

    def test_no_cookie_owns_nothing(self, site):
        with pytest.raises(PermissionError):
            core.interface_owner(self.request_with(None, None))

    def test_a_cookie_that_disagrees_with_the_session_owns_nothing(self, site):
        client, _ = site
        sign_up(client)
        cookie = client.cookies.get(core.SESSION_COOKIE)
        with pytest.raises(PermissionError):
            core.interface_owner(self.request_with(cookie, "someone-else"))

    def test_the_header_shows_who_is_signed_in_and_a_way_out(self, site):
        client, fake = site
        sign_up(client, email="o'brien@example.com")
        user = fake.users["o'brien@example.com"]["id"]
        cookie = client.cookies.get(core.SESSION_COOKIE)
        bar = core.account_html(self.request_with(cookie, user))
        assert "o&#x27;brien@example.com" in bar and 'action="/auth/sign-out"' in bar
