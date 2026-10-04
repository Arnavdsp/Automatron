"""A stand-in for a Supabase project, for tests that need real tokens and storage.

Tokens are signed with a freshly generated P-256 key and verified by the
application exactly as production tokens are: against a published key set, with
issuer, audience and expiry all checked. The REST side keeps rows in memory and
applies the same visibility rules as the migration's policies, answering a
refused write the way PostgREST does. Only the network is replaced.
"""

import base64
import datetime as dt
import json
import re
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

PROJECT_URL = "https://testproject.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
PUBLISHABLE_KEY = "sb_publishable_test_key_0000"
TEST_KEYRING = "k1:" + base64.b64encode(b"k" * 32).decode()
SEALED = re.compile(r"^v1\.[A-Za-z0-9_-]+$")


class FakeSupabase:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = uuid.uuid4().hex
        self.users: dict[str, dict] = {}
        self.jwks_requests = 0
        self.user_requests = 0
        self.organizations: dict[str, str] = {}
        self.runs: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.refresh_tokens: dict[str, str] = {}
        self.writes_fail = False

    def add_user(self, email: str, password: str = "correct horse") -> str:
        user_id = str(uuid.uuid4())
        self.users[email] = {"id": user_id, "password": password}
        # What the signup trigger does: a personal organization the user owns.
        self.organizations[user_id] = str(uuid.uuid4())
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
            if request.url.params.get("grant_type") == "refresh_token":
                email = self.refresh_tokens.pop(body.get("refresh_token", ""), None)
                if email is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
            else:
                email = body.get("email", "")
                user = self.users.get(email)
                if not user or user["password"] != body.get("password"):
                    return httpx.Response(400, json={"error": "invalid_grant"})
            refresh = uuid.uuid4().hex
            self.refresh_tokens[refresh] = email
            return httpx.Response(200, json={"access_token": self.token(email),
                                             "refresh_token": refresh})
        if path == "/auth/v1/user":
            self.user_requests += 1
            return httpx.Response(401, json={"msg": "invalid JWT"})
        if path.startswith("/rest/v1/"):
            return self.rest(request, path.removeprefix("/rest/v1/"))
        return httpx.Response(404)

    # -- REST, with the migration's row-level security applied by hand ----------

    def caller(self, request: httpx.Request) -> str | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        try:
            claims = jwt.decode(token, self.key.public_key(), algorithms=["ES256"],
                                audience="authenticated")
        except jwt.PyJWTError:
            return None
        return claims["sub"]

    @staticmethod
    def eq(request: httpx.Request, name: str) -> str | None:
        value = request.url.params.get(name)
        return value.removeprefix("eq.") if value else None

    def visible_runs(self, user: str) -> list[dict]:
        orgs = {org for member, org in self.organizations.items() if member == user}
        return [row for row in self.runs.values() if row["organization_id"] in orgs]

    def rest(self, request: httpx.Request, table: str) -> httpx.Response:
        user = self.caller(request)
        if user is None:
            return httpx.Response(401, json={"message": "JWT invalid"})
        refused = httpx.Response(403, json={"code": "42501", "message":
                                            "new row violates row-level security policy"})
        if request.method != "GET" and self.writes_fail:
            return httpx.Response(503, json={"message": "unavailable"})
        if table == "organization_members" and request.method == "GET":
            asked = self.eq(request, "user_id")
            return httpx.Response(200, json=[{"organization_id": self.organizations[user]}]
                                  if asked == user else [])
        if table == "runs" and request.method == "POST":
            row = json.loads(request.content)
            if (row["created_by"] != user
                    or row["organization_id"] != self.organizations.get(user)):
                return refused
            if not SEALED.match(row["sealed_input"]):
                return httpx.Response(400, json={"code": "23514", "message": "check violation"})
            row["id"] = str(uuid.UUID(row["id"]))
            row["created_at"] = dt.datetime.now(dt.UTC).isoformat()
            row["sealed_result"] = None
            self.runs[row["id"]] = row
            return httpx.Response(201)
        if table == "runs" and request.method == "PATCH":
            row = self.runs.get(self.eq(request, "id") or "")
            if row is None or row["created_by"] != user:
                return httpx.Response(200, json=[])
            patch = json.loads(request.content)
            if set(patch) - {"status", "sealed_result", "updated_at"}:
                return httpx.Response(403, json={"code": "42501", "message": "permission denied"})
            if patch.get("sealed_result") and not SEALED.match(patch["sealed_result"]):
                return httpx.Response(400, json={"code": "23514", "message": "check violation"})
            row.update(patch)
            return httpx.Response(200, json=[row])
        if table == "runs" and request.method == "GET":
            rows = self.visible_runs(user)
            if self.eq(request, "id"):
                rows = [r for r in rows if r["id"] == self.eq(request, "id")]
            if self.eq(request, "created_by"):
                rows = [r for r in rows if r["created_by"] == self.eq(request, "created_by")]
            rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
            return httpx.Response(200, json=rows[: int(request.url.params.get("limit", 1000))])
        if table == "audit_entries" and request.method == "POST":
            row = json.loads(request.content)
            if row["actor"] != user or row["organization_id"] != self.organizations.get(user):
                return refused
            self.audit.append(row)
            return httpx.Response(201)
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def install(core, monkeypatch) -> FakeSupabase:
    """Switch the application into multi-user mode against a fake project."""
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    monkeypatch.setenv("RUN_ENCRYPTION_KEYS", TEST_KEYRING)
    monkeypatch.delenv("RUN_KMS_KEY", raising=False)
    core.reset_settings_cache()
    core.reset_identity()
    core.reset_vault()
    monkeypatch.setattr(core, "_VERIFIER",
                        core.SupabaseVerifier(PROJECT_URL, PUBLISHABLE_KEY,
                                              transport=fake.transport()))
    monkeypatch.setattr(core, "_STORE",
                        core.SupabaseRunStore(PROJECT_URL, PUBLISHABLE_KEY,
                                              transport=fake.transport()))
    return fake


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
