"""A stand-in for a Supabase project's auth server, for tests that need real tokens.

Tokens are signed with a freshly generated P-256 key and verified by the
application exactly as production tokens are: against a published key set, with
issuer, audience and expiry all checked. Only the network is replaced.
"""

import json
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

PROJECT_URL = "https://testproject.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
PUBLISHABLE_KEY = "sb_publishable_test_key_0000"


class FakeSupabase:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = uuid.uuid4().hex
        self.users: dict[str, dict] = {}
        self.jwks_requests = 0
        self.user_requests = 0

    def add_user(self, email: str, password: str = "correct horse") -> str:
        user_id = str(uuid.uuid4())
        self.users[email] = {"id": user_id, "password": password}
        return user_id

    def jwks(self) -> dict:
        public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**public, "kid": self.kid, "alg": "ES256", "use": "sig"}]}

    def token(self, email: str, **overrides) -> str:
        now = int(time.time())
        claims = {
            "sub": self.users[email]["id"],
            "email": email,
            "aud": "authenticated",
            "role": "authenticated",
            "iss": ISSUER,
            "iat": now,
            "exp": now + 3600,
        }
        headers = {"kid": overrides.pop("kid", self.kid)}
        key = overrides.pop("signing_key", self.key)
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key, algorithm="ES256", headers=headers)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/v1/.well-known/jwks.json":
            self.jwks_requests += 1
            return httpx.Response(200, json=self.jwks())
        if path == "/auth/v1/token":
            body = json.loads(request.content or b"{}")
            user = self.users.get(body.get("email", ""))
            if not user or user["password"] != body.get("password"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": self.token(body["email"])})
        if path == "/auth/v1/user":
            self.user_requests += 1
            return httpx.Response(401, json={"msg": "invalid JWT"})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def install(core, monkeypatch) -> FakeSupabase:
    """Switch the application into multi-user mode against a fake project."""
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    core.reset_settings_cache()
    core.reset_identity()
    monkeypatch.setattr(core, "_VERIFIER",
                        core.SupabaseVerifier(PROJECT_URL, PUBLISHABLE_KEY,
                                              transport=fake.transport()))
    return fake


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
