"""Supabase access tokens: what is accepted as a user, and everything that is not."""

import base64
import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import automatron_core as core
from tests import supabase_fake
from tests.supabase_fake import ISSUER, PROJECT_URL, PUBLISHABLE_KEY, FakeSupabase


@pytest.fixture
def project():
    fake = FakeSupabase()
    fake.add_user("alice@example.com")
    verifier = core.SupabaseVerifier(PROJECT_URL, PUBLISHABLE_KEY, transport=fake.transport())
    return fake, verifier


class TestAValidTokenIsAUser:
    async def test_the_subject_becomes_the_user_id(self, project):
        fake, verifier = project
        principal = await verifier.verify(fake.token("alice@example.com"))
        assert principal.user_id == fake.users["alice@example.com"]["id"]
        assert principal.method == "supabase"

    async def test_the_key_set_is_fetched_once_and_reused(self, project):
        """Verification is local: a signed-in user's requests cost no call to the
        auth server once the project's keys are cached."""
        fake, verifier = project
        for _ in range(5):
            await verifier.verify(fake.token("alice@example.com"))
        assert fake.jwks_requests == 1


class TestEverythingElseIsRefused:
    async def refused(self, verifier, token):
        with pytest.raises(core.AuthError):
            await verifier.verify(token)

    async def test_an_expired_token(self, project):
        fake, verifier = project
        await self.refused(verifier, fake.token("alice@example.com", exp=1, iat=0))

    async def test_a_token_for_another_audience(self, project):
        fake, verifier = project
        await self.refused(verifier, fake.token("alice@example.com", aud="anon"))

    async def test_a_token_from_another_project(self, project):
        fake, verifier = project
        await self.refused(verifier, fake.token(
            "alice@example.com", iss="https://elsewhere.supabase.co/auth/v1"))

    async def test_a_token_without_a_subject(self, project):
        fake, verifier = project
        await self.refused(verifier, fake.token("alice@example.com", sub=None))

    async def test_a_token_signed_by_someone_else(self, project):
        """Same key id, different key: the signature is what proves the issuer."""
        fake, verifier = project
        stranger = ec.generate_private_key(ec.SECP256R1())
        await self.refused(verifier, fake.token("alice@example.com", signing_key=stranger))

    async def test_a_token_with_an_altered_claim(self, project):
        fake, verifier = project
        header, body, signature = fake.token("alice@example.com").split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        claims["sub"] = "someone-else"
        forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        await self.refused(verifier, f"{header}.{forged}.{signature}")

    async def test_an_unsigned_token(self, project):
        fake, verifier = project
        claims = {"sub": "x", "aud": "authenticated", "iss": ISSUER, "exp": 9999999999}
        await self.refused(verifier, jwt.encode(claims, None, algorithm="none"))

    async def test_a_public_key_used_as_an_hmac_secret(self, project):
        """The classic confusion attack: sign with HS256 using the published key as
        the secret. Shared-secret tokens are never verified locally, so the auth
        server is asked instead, and it says no."""
        fake, verifier = project
        public = json.dumps(fake.jwks()["keys"][0]).encode()
        claims = {"sub": "x", "aud": "authenticated", "iss": ISSUER, "exp": 9999999999}
        # Signed by hand: the library itself refuses to use a JWK as an HMAC secret.
        def part(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        signing_input = f"{part({'alg': 'HS256', 'kid': fake.kid})}.{part(claims)}"
        mac = hmac.new(public, signing_input.encode(), hashlib.sha256).digest()
        token = f"{signing_input}.{base64.urlsafe_b64encode(mac).decode().rstrip('=')}"
        await self.refused(verifier, token)
        assert fake.user_requests == 1

    async def test_garbage(self, project):
        _, verifier = project
        await self.refused(verifier, "not-a-token")


class TestKeyRotation:
    async def test_an_unknown_key_id_refetches_but_not_on_every_request(self, project):
        """A rotated key must be picked up, but a stream of made-up key ids must not
        turn into a stream of requests to the auth server."""
        fake, verifier = project
        await verifier.verify(fake.token("alice@example.com"))
        for _ in range(5):
            with pytest.raises(core.AuthError):
                await verifier.verify(fake.token("alice@example.com", kid="made-up"))
        assert fake.jwks_requests == 1

    async def test_a_new_key_is_found_once_the_floor_has_passed(self, project, monkeypatch):
        fake, verifier = project
        await verifier.verify(fake.token("alice@example.com"))
        fake.key = ec.generate_private_key(ec.SECP256R1())
        fake.kid = "rotated"
        verifier._fetched_at -= core.JWKS_REFETCH_FLOOR_S + 1
        principal = await verifier.verify(fake.token("alice@example.com"))
        assert principal.user_id == fake.users["alice@example.com"]["id"]


class TestPasswordLogin:
    async def test_right_password_signs_in_as_that_user(self, project):
        fake, verifier = project
        principal = await verifier.password_login("alice@example.com", "correct horse")
        assert principal.user_id == fake.users["alice@example.com"]["id"]

    async def test_wrong_password_signs_in_as_nobody(self, project):
        _, verifier = project
        assert await verifier.password_login("alice@example.com", "wrong") is None


class TestTheKeySetting:
    """A secret key in the publishable slot would work, silently, and give every
    user the run of the database. It stops the deployment instead."""

    def configure(self, monkeypatch, key):
        monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", key)
        core.reset_settings_cache()

    def teardown_method(self):
        core.reset_settings_cache()

    def test_a_publishable_key_is_accepted(self, monkeypatch):
        self.configure(monkeypatch, PUBLISHABLE_KEY)
        core.check_supabase_key()

    def test_a_secret_key_is_refused(self, monkeypatch):
        self.configure(monkeypatch, "sb_secret_abcdefghijklmnop")
        with pytest.raises(ValueError, match="secret or service-role"):
            core.check_supabase_key()

    def test_a_legacy_service_role_key_is_refused(self, monkeypatch):
        legacy = jwt.encode({"role": "service_role", "iss": "supabase"}, "x" * 32,
                            algorithm="HS256")
        self.configure(monkeypatch, legacy)
        with pytest.raises(ValueError, match="secret or service-role"):
            core.check_supabase_key()

    def test_the_key_is_redacted_from_logs(self, monkeypatch):
        self.configure(monkeypatch, PUBLISHABLE_KEY)
        assert PUBLISHABLE_KEY not in core.redact(f"key={PUBLISHABLE_KEY}")


def test_the_helper_switches_the_app_into_multi_user_mode(monkeypatch):
    supabase_fake.install(core, monkeypatch)
    try:
        assert core.get_settings().supabase_auth_enabled
    finally:
        monkeypatch.undo()
        core.reset_settings_cache()
        core.reset_identity()
