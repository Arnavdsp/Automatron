"""Envelope encryption: what opens, and everything that must not."""

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import automatron_core as core

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()
KMS_KEY = "projects/p/locations/global/keyRings/automatron/cryptoKeys/runs"


@pytest.fixture(autouse=True)
def keyring(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_ENCRYPTION_KEYS", f"a:{KEY_A}")
    monkeypatch.delenv("RUN_KMS_KEY", raising=False)
    core.reset_settings_cache()
    core.reset_vault()
    yield
    core.reset_vault()
    core.reset_settings_cache()


async def sealed(run_id="run-1", owner="alice", field="input", value=None):
    key_id, wrapped = await core.new_run_key(run_id, owner)
    text = await core.seal_field(run_id, owner, key_id, wrapped, field,
                                 value or {"request": "triage SAT-7"})
    return key_id, wrapped, text


def forget_cached_keys():
    """Each test that changes who is opening starts without the process's cache, as
    another instance or a restarted one would."""
    core._RUN_KEYS.clear()


class TestARunsOwnFieldsOpen:
    async def test_a_sealed_field_opens_to_what_was_sealed(self):
        key_id, wrapped, text = await sealed()
        forget_cached_keys()
        assert await core.open_field("run-1", "alice", key_id, wrapped, "input", text) \
            == {"request": "triage SAT-7"}

    async def test_the_sealed_text_carries_nothing_readable(self):
        _, wrapped, text = await sealed()
        assert text.startswith("v1.")
        assert "SAT-7" not in text and "triage" not in text
        assert "SAT-7" not in wrapped

    async def test_sealing_twice_gives_different_ciphertext(self):
        key_id, wrapped, first = await sealed()
        again = await core.seal_field("run-1", "alice", key_id, wrapped, "input",
                                      {"request": "triage SAT-7"})
        assert first != again


class TestNothingElseOpens:
    async def refused(self, *args):
        forget_cached_keys()
        with pytest.raises(core.SealError):
            await core.open_field(*args)

    async def test_another_owner(self):
        key_id, wrapped, text = await sealed()
        await self.refused("run-1", "bob", key_id, wrapped, "input", text)

    async def test_another_run(self):
        key_id, wrapped, text = await sealed()
        await self.refused("run-2", "alice", key_id, wrapped, "input", text)

    async def test_another_field_of_the_same_run(self):
        """A sealed input pasted over the sealed result must not read as a result."""
        key_id, wrapped, text = await sealed()
        await self.refused("run-1", "alice", key_id, wrapped, "result", text)

    async def test_an_altered_ciphertext(self):
        key_id, wrapped, text = await sealed()
        flipped = text[:-2] + ("A" if text[-2] != "A" else "B") + text[-1]
        await self.refused("run-1", "alice", key_id, wrapped, "input", flipped)

    async def test_an_altered_wrapped_key(self):
        key_id, wrapped, text = await sealed()
        raw = bytearray(base64.urlsafe_b64decode(wrapped + "=" * (-len(wrapped) % 4)))
        raw[-1] ^= 1
        bent = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
        await self.refused("run-1", "alice", key_id, bent, "input", text)

    async def test_a_keyring_without_the_key(self, monkeypatch):
        key_id, wrapped, text = await sealed()
        monkeypatch.setenv("RUN_ENCRYPTION_KEYS", f"b:{KEY_B}")
        core.reset_settings_cache()
        await self.refused("run-1", "alice", key_id, wrapped, "input", text)

    async def test_plaintext_is_not_a_sealed_value(self):
        key_id, wrapped, _ = await sealed()
        await self.refused("run-1", "alice", key_id, wrapped, "input", '{"request": "x"}')


class TestRotation:
    async def test_a_new_key_seals_while_the_old_one_still_opens(self, monkeypatch):
        old_id, old_wrapped, old_text = await sealed("run-old")
        monkeypatch.setenv("RUN_ENCRYPTION_KEYS", f"b:{KEY_B},a:{KEY_A}")
        core.reset_settings_cache()
        forget_cached_keys()
        assert await core.open_field("run-old", "alice", old_id, old_wrapped, "input",
                                     old_text) == {"request": "triage SAT-7"}
        new_id, _, _ = await sealed("run-new")
        assert (old_id, new_id) == ("local:a", "local:b")


class TestTheKeyringSetting:
    @pytest.mark.parametrize("bad", ["no-separator", "a:not base64!", f"a:{KEY_A[:-8]}",
                                     f"bad id!:{KEY_A}"])
    def test_a_malformed_keyring_stops_startup(self, monkeypatch, bad):
        monkeypatch.setenv("RUN_ENCRYPTION_KEYS", bad)
        core.reset_settings_cache()
        with pytest.raises(ValueError):
            core.check_encryption_configured()

    def test_multi_user_mode_needs_a_key(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_x")
        monkeypatch.delenv("RUN_ENCRYPTION_KEYS")
        core.reset_settings_cache()
        with pytest.raises(ValueError, match="RUN_KMS_KEY or RUN_ENCRYPTION_KEYS"):
            core.check_encryption_configured()

    def test_the_key_material_is_redacted(self):
        assert KEY_A not in core.redact(f"loaded {KEY_A}")


class FakeKms:
    """Cloud KMS's encrypt and decrypt, with its own key and the AAD it was given."""

    def __init__(self):
        self.key = AESGCM.generate_key(bit_length=256)
        self.token_requests = 0
        self.calls = []
        self.deny = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "metadata.google.internal":
            assert request.headers["metadata-flavor"] == "Google"
            self.token_requests += 1
            return httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.x"
        if self.deny:
            return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})
        verb = request.url.path.rsplit(":", 1)[1]
        assert request.url.path.startswith(f"/v1/{KMS_KEY}:")
        body = json.loads(request.content)
        aad = base64.b64decode(body["additionalAuthenticatedData"])
        self.calls.append(verb)
        if verb == "encrypt":
            nonce = b"n" * 12
            sealed = AESGCM(self.key).encrypt(nonce, base64.b64decode(body["plaintext"]), aad)
            return httpx.Response(200, json={"ciphertext": base64.b64encode(nonce + sealed)
                                             .decode()})
        blob = base64.b64decode(body["ciphertext"])
        try:
            plain = AESGCM(self.key).decrypt(blob[:12], blob[12:], aad)
        except Exception:
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        return httpx.Response(200, json={"plaintext": base64.b64encode(plain).decode()})


class TestCloudKms:
    @pytest.fixture
    def kms(self, monkeypatch):
        fake = FakeKms()
        monkeypatch.setenv("RUN_KMS_KEY", KMS_KEY)
        core.reset_settings_cache()
        core.reset_vault()
        keyring = core.CloudKmsKeyring(KMS_KEY, transport=httpx.MockTransport(fake.handler))
        monkeypatch.setattr(core, "_KEYRING", keyring)
        monkeypatch.setattr(core, "_KEYRING_SOURCE", f"{KMS_KEY}|" + core.hashlib.sha256(
            f"a:{KEY_A}".encode()).hexdigest())
        return fake

    async def test_run_keys_are_wrapped_by_the_key_service(self, kms):
        key_id, wrapped, text = await sealed()
        assert key_id == f"kms:{KMS_KEY}"
        forget_cached_keys()
        assert await core.open_field("run-1", "alice", key_id, wrapped, "input", text) \
            == {"request": "triage SAT-7"}
        assert kms.calls == ["encrypt", "decrypt"]

    async def test_the_service_identity_token_is_fetched_once(self, kms):
        await sealed("run-1")
        await sealed("run-2")
        assert kms.token_requests == 1

    async def test_the_run_and_owner_are_bound_by_the_key_service_too(self, kms):
        key_id, wrapped, text = await sealed()
        forget_cached_keys()
        with pytest.raises(core.SealError):
            await core.open_field("run-1", "bob", key_id, wrapped, "input", text)

    async def test_revoked_access_opens_nothing(self, kms):
        key_id, wrapped, text = await sealed()
        forget_cached_keys()
        kms.deny = True
        with pytest.raises(core.SealError):
            await core.open_field("run-1", "alice", key_id, wrapped, "input", text)

    def test_a_malformed_key_name_is_refused(self):
        with pytest.raises(ValueError):
            core.CloudKmsKeyring("my-key")


class TestCheckpoints:
    async def test_state_round_trips_and_the_bytes_are_ciphertext(self):
        serde = await core.checkpoint_serializer()
        kind, blob = serde.dumps_typed({"request": "triage SAT-7"})
        assert b"SAT-7" not in blob and kind.endswith("+aesgcm")
        assert serde.loads_typed((kind, blob)) == {"request": "triage SAT-7"}

    async def test_an_unencrypted_checkpoint_is_refused(self):
        """The library would read it as-is; here it could be planted state."""
        serde = await core.checkpoint_serializer()
        plain = core.JsonPlusSerializer().dumps_typed({"status": "approved"})
        with pytest.raises(core.SealError):
            serde.loads_typed(plain)

    async def test_an_altered_checkpoint_is_refused(self):
        serde = await core.checkpoint_serializer()
        kind, blob = serde.dumps_typed({"status": "awaiting_approval"})
        with pytest.raises(core.SealError):
            serde.loads_typed((kind, blob[:-1] + bytes([blob[-1] ^ 1])))

    async def test_the_checkpoint_key_is_stored_only_wrapped(self, tmp_path):
        await core.checkpoint_serializer()
        stored = json.loads((tmp_path / core.CHECKPOINT_KEY_FILE).read_text())
        assert set(stored) == {"key_id", "wrapped"}
        assert oct((tmp_path / core.CHECKPOINT_KEY_FILE).stat().st_mode & 0o777) == "0o600"

    async def test_the_same_runtime_reopens_its_own_checkpoints(self):
        kind, blob = (await core.checkpoint_serializer()).dumps_typed({"n": 1})
        core.reset_vault()
        assert (await core.checkpoint_serializer()).loads_typed((kind, blob)) == {"n": 1}
