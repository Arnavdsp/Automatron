"""Settings, YAML configuration, and the overrides the environment may apply."""

import pytest

import automatron_core as core


@pytest.fixture
def fresh_settings():
    """Let a test change the environment and see the effect, then restore."""
    core.reset_settings_cache()
    yield core.reset_settings_cache
    core.reset_settings_cache()


class TestSettings:
    def test_defaults_match_the_documented_environment(self):
        settings = core.get_settings()
        assert settings.port == 7860
        assert settings.max_upload_mb == 10
        assert settings.max_parallel_steps == 2
        assert settings.rate_limit_per_ip_per_hour == 30
        assert settings.embed_model == "BAAI/bge-small-en-v1.5"

    def test_upload_limit_is_exposed_in_bytes(self):
        assert core.get_settings().max_upload_bytes == 10 * 1024 * 1024

    def test_relative_paths_resolve_against_the_repository_root(self):
        settings = core.get_settings()
        assert settings.data_path.is_absolute()
        assert settings.data_path == core.ROOT / "data"

    def test_absolute_paths_are_left_alone(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("RUNTIME_DIR", "/var/tmp/automatron-test")
        fresh_settings()
        assert str(core.get_settings().runtime_path) == "/var/tmp/automatron-test"

    def test_no_keys_means_fake_mode(self, monkeypatch, fresh_settings):
        for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "0")
        fresh_settings()

        settings = core.get_settings()
        assert settings.configured_providers == []
        assert settings.fake_mode is True

    def test_a_key_leaves_fake_mode_off(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "0")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_not_a_real_key_0123456789")
        fresh_settings()

        settings = core.get_settings()
        assert settings.configured_providers == ["groq"]
        assert settings.has_key("groq")
        assert settings.has_key("gemini") is False
        assert settings.fake_mode is False

    def test_fake_mode_can_be_forced_even_with_keys(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_not_a_real_key_0123456789")
        fresh_settings()
        assert core.get_settings().fake_mode is True

    def test_blank_key_does_not_count(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        fresh_settings()
        assert core.get_settings().has_key("gemini") is False

    def test_keys_are_not_printed_by_repr(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_not_a_real_key_0123456789")
        fresh_settings()
        assert "gsk_not_a_real_key" not in repr(core.get_settings())


class TestProviderConfig:
    def test_every_role_has_a_chain_of_known_providers(self):
        config = core.load_provider_config()
        providers = set(config["providers"])
        for role in core.AGENT_ROLES:
            chain = config["roles"][role]
            assert chain, f"role {role} has an empty chain"
            assert set(chain) <= providers

    def test_openrouter_lists_free_models(self):
        openrouter = core.load_provider_config()["providers"]["openrouter"]
        assert openrouter["models"], "the chain would be empty without configured models"
        assert all(model.endswith(":free") for model in openrouter["models"])

    def test_model_ids_can_be_overridden_from_the_environment(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
        monkeypatch.setenv("OPENROUTER_MODELS", "vendor/a:free, vendor/b:free")
        fresh_settings()

        providers = core.load_provider_config()["providers"]
        assert providers["gemini"]["model"] == "gemini-3.8-flash"
        assert providers["openrouter"]["models"] == ["vendor/a:free", "vendor/b:free"]

    def test_quota_reservation_is_always_present(self):
        assert isinstance(core.load_provider_config()["quota_reservation"], dict)


class TestSectorConfig:
    def test_all_four_sectors_are_described(self):
        config = core.load_sector_config()
        assert set(config) == set(core.SECTOR_ORDER)

    def test_display_names_follow_the_product_naming(self):
        names = {key: core.sector_identity(key)["display_name"] for key in core.SECTOR_ORDER}
        assert names == {
            "space": "Automatron Space",
            "quant": "Automatron Quant",
            "ecommerce": "Automatron E-commerce",
            "realestate": "Automatron Real Estate",
        }

    def test_disclaimer_is_collapsed_to_one_line(self):
        assert "\n" not in core.sector_identity("quant")["disclaimer"]

    def test_thresholds_are_reachable(self):
        assert core.sector_threshold("space", "pc_red") == pytest.approx(1e-4)
        assert core.sector_threshold("quant", "trade_approval_usd") == 100000
        assert core.sector_threshold("ecommerce", "risk_high") == 70

    def test_missing_threshold_returns_the_default(self):
        assert core.sector_threshold("realestate", "nope", "fallback") == "fallback"

    def test_thresholds_can_be_overridden_from_the_environment(self, monkeypatch, fresh_settings):
        monkeypatch.setenv("TRADE_APPROVAL_THRESHOLD_USD", "250000")
        monkeypatch.setenv("ECOM_HIGH_VALUE_THRESHOLD_USD", "750")
        fresh_settings()

        assert core.sector_threshold("quant", "trade_approval_usd") == 250000
        assert core.sector_threshold("ecommerce", "high_value_usd") == 750

    def test_unknown_sector_is_a_clear_error(self):
        with pytest.raises(KeyError, match="unknown sector"):
            core.sector_settings("aviation")
