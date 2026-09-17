"""Credentials and personal data never reach a log line."""

import json
import logging

import automatron_core as core

FAKE_KEYS = (
    "gsk_" + "a" * 24,
    "sk-or-v1-" + "b" * 24,
    "AIza" + "c" * 24,
    # Google issues this second shape too, which shares no prefix with the first.
    "AQ." + "Ab8RN6" + "d" * 24,
    "csk-" + "e" * 24,
)


def test_masks_email_to_first_letters():
    assert core.redact("write to arnav@example.com today") == "write to a***@e***.com today"


def test_masks_card_number_to_last_four():
    assert core.redact("card 4111 1111 1111 1234 charged") == "card ****1234 charged"
    assert core.redact("card 4111111111111234 charged") == "card ****1234 charged"


def test_masks_phone_to_last_two_digits():
    assert core.redact("call 555-123-4567 now") == "call ***67 now"
    assert core.redact("call (555) 123-4567 now") == "call ***67 now"


def test_masks_provider_keys():
    for key in FAKE_KEYS:
        assert key not in core.redact(f"authorization: {key}")
        assert "[redacted-key]" in core.redact(f"authorization: {key}")


def test_leaves_ordinary_numbers_alone():
    text = "Pc 3.2e-04 at TCA 2026-03-01T12:00:00Z, miss distance 412 m, Sharpe 1.83"
    assert core.redact(text) == text


def test_empty_text_is_returned_unchanged():
    assert core.redact("") == ""


def test_formatter_emits_json_and_redacts(caplog):
    record = logging.LogRecord(
        name="automatron.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"key {FAKE_KEYS[0]} for arnav@example.com",
        args=(),
        exc_info=None,
    )
    record.provider = "groq"
    record.latency_ms = 120

    payload = json.loads(core.JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["provider"] == "groq"
    assert payload["latency_ms"] == 120
    assert FAKE_KEYS[0] not in payload["message"]
    assert "arnav@example.com" not in payload["message"]
    assert "ts" in payload


def test_logger_is_configured_once():
    logger = core.get_logger("probe")
    assert logger.name == "automatron.probe"
    assert logging.getLogger(core.LOGGER_NAME).handlers


class TestConfiguredSecretValues:
    """Some providers issue keys with no recognisable prefix, so patterns miss them."""

    def test_a_prefixless_key_is_masked_because_it_is_configured(self, monkeypatch):
        # Same shape as a real prefixless key, assembled so it is not one.
        opaque = "Zq" + "7x" * 8 + "Kt" + "4m" * 6
        assert opaque in core.redact(f"bearer {opaque}"), "no pattern should match this shape"

        monkeypatch.setenv("MISTRAL_API_KEY", opaque)
        core.reset_settings_cache()
        try:
            masked = core.redact(f"bearer {opaque}")
            assert opaque not in masked
            assert "[redacted-key]" in masked
        finally:
            core.reset_settings_cache()

    def test_short_values_are_not_masked(self, monkeypatch):
        # Masking a short value would blank out ordinary words in every log line.
        monkeypatch.setenv("MISTRAL_API_KEY", "abc")
        core.reset_settings_cache()
        try:
            assert "abc" not in core.configured_secret_values()
        finally:
            core.reset_settings_cache()

    def test_no_keys_configured_is_not_an_error(self):
        core.reset_settings_cache()
        assert isinstance(core.configured_secret_values(), tuple)
