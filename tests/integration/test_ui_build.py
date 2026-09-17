"""The interface assembles, and the sector switch changes what the spec says it should."""

import re

import pytest

import automatron_core as core
from tests import testsector

EXPECTED_DISPLAY = {
    "space": "Automatron Space",
    "quant": "Automatron Quant",
    "ecommerce": "Automatron E-commerce",
    "realestate": "Automatron Real Estate",
}
EXPECTED_ACCENT = {
    "space": "#7C8CFF",
    "quant": "#2DD4BF",
    "ecommerce": "#F5A524",
    "realestate": "#E07A5F",
}


@pytest.fixture
def ui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    core.reset_run_service()
    pack = testsector.install()
    yield pack
    core.clear_fake_script()
    core.clear_registry()
    core.reset_run_service()
    core.reset_settings_cache()


def relative_luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def contrast(foreground: str, background: str) -> float:
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


class TestAssembly:
    def test_the_interface_builds(self, ui_env):
        demo = core.build_interface()
        assert demo.__class__.__name__ == "Blocks"

    def test_it_builds_with_no_sectors_registered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
        monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
        core.reset_settings_cache()
        core.clear_registry()
        try:
            demo = core.build_interface()
            assert demo.__class__.__name__ == "Blocks"
        finally:
            core.reset_settings_cache()

    def test_create_app_mounts_the_interface_at_the_root(self, ui_env):
        app = core.create_app()
        # Gradio mounts as a sub-application, which appears as a Mount at the
        # root rather than as a route with path "/".
        mounts = [r for r in app.routes if type(r).__name__ == "Mount"]
        assert mounts, "the interface is not mounted"
        assert mounts[0].path == ""
        api_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert f"{core.API_PREFIX}/health" in api_paths


class TestSectorSwitching:
    @pytest.mark.parametrize("sector_id,display", sorted(EXPECTED_DISPLAY.items()))
    def test_header_shows_the_exact_display_name(self, sector_id, display):
        markup = core.header_html(sector_id)
        # Tags split the name, so compare the text content.
        text = re.sub(r"<[^>]+>", "", markup)
        assert display in text

    @pytest.mark.parametrize("sector_id,accent", sorted(EXPECTED_ACCENT.items()))
    def test_each_sector_carries_its_accent(self, sector_id, accent):
        assert core.sector_identity(sector_id)["accent"] == accent

    def test_the_sector_word_is_the_accented_part(self):
        assert '<span class="sector">Space</span>' in core.header_html("space")
        assert '<span class="sector">Estate</span>' in core.header_html("realestate")

    def test_workflow_choices_follow_the_sector(self, ui_env):
        assert core.workflow_choices("space") == [("Probe", testsector.WORKFLOW_ID)]
        assert core.workflow_choices("quant") == []

    def test_switching_sector_changes_the_input_defaults(self, ui_env):
        defaults = core.default_inputs_json("space", testsector.WORKFLOW_ID)
        assert "subject" in defaults
        assert core.default_inputs_json("quant", "quant.missing") == "{}"

    def test_the_blurb_describes_the_workflow(self, ui_env):
        assert "Measure a subject" in core.workflow_blurb("space", testsector.WORKFLOW_ID)

    def test_an_unknown_sector_degrades_to_the_product_name(self):
        text = re.sub(r"<[^>]+>", "", core.header_html("aviation"))
        assert "Automatron" in text


class TestStatusRendering:
    def test_demo_mode_is_announced(self, ui_env):
        assert "Demo mode" in core.provider_dots_html()

    def test_one_dot_per_provider_not_per_model(self, ui_env):
        markup = core.provider_dots_html()
        slots = core.get_router().slots.values()
        providers = {slot.provider for slot in slots}
        # OpenRouter and Mistral each hold several model slots; the header must
        # still show one dot per provider.
        assert len(slots) > len(providers), "expected some providers to hold several models"
        assert markup.count('class="am-dot') == len(providers)

    def test_trace_rows_mark_failover_and_errors(self):
        events = [
            {
                "ts": "2026-01-01T00:00:00",
                "node": "plan",
                "kind": "failover",
                "message": "gemini rate limited",
                "provider": "gemini",
                "model": "flash",
            },
            {
                "ts": "2026-01-01T00:00:01",
                "node": "run_step",
                "kind": "error",
                "message": "tool failed",
            },
        ]
        markup = core.trace_html(events)
        assert 'class="row failover"' in markup
        assert 'class="row error"' in markup

    def test_an_empty_trace_says_so(self):
        assert "No activity yet" in core.trace_html([])

    def test_status_wording_covers_every_run_state(self):
        for status in (
            "queued",
            "running",
            "revising",
            "awaiting_approval",
            "approved",
            "rejected",
            "failed",
        ):
            view = core.RunView(run_id="r", sector="space", workflow_id="w", status=status)
            assert core.status_line(view).strip()


class TestBriefRendering:
    def test_an_absent_brief_shows_the_empty_state(self):
        assert "Load sample" in core.brief_markdown_for_ui(None)

    def test_a_brief_renders_its_level_and_disclaimer(self):
        brief = {
            "title": "T",
            "sector": "space",
            "workflow_id": "w",
            "summary": "S",
            "recommendation": "Proposed: review.",
            "recommendation_level": "RED",
            "confidence": "high",
            "confidence_reason": "clear",
            "key_findings": [{"text": "Pc is high.", "severity": "high", "evidence_ids": ["T1"]}],
            "options": [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}],
            "disclaimer": "Decision support only.",
        }
        markup = core.brief_markdown_for_ui(brief)
        assert 'class="am-level">RED' in markup
        assert "Decision support only." in markup
        assert "requires human approval" in markup

    def test_a_malformed_brief_does_not_raise(self):
        assert "could not be displayed" in core.brief_markdown_for_ui({"title": "only"})

    def test_evidence_rows_flatten_for_the_table(self):
        brief = {
            "evidence": [
                {
                    "id": "T1",
                    "kind": "tool",
                    "label": "measure",
                    "locator": "c1",
                    "excerpt": "x" * 400,
                }
            ]
        }
        rows = core.evidence_rows(brief)
        assert rows[0][0] == "T1"
        assert len(rows[0][4]) <= 160


class TestStyling:
    def test_dark_mode_is_forced_on_load(self):
        assert "__theme" in core.UI_JS and "dark" in core.UI_JS

    def test_the_accent_script_sets_both_the_variable_and_the_tab_title(self):
        assert "--accent" in core.SET_ACCENT_JS
        assert "document.title" in core.SET_ACCENT_JS

    def test_the_layout_responds_to_small_screens(self):
        assert "@media (max-width: 768px)" in core.UI_CSS

    def test_reduced_motion_is_respected(self):
        assert "prefers-reduced-motion" in core.UI_CSS

    def test_focus_is_visible_for_keyboard_users(self):
        assert ":focus-visible" in core.UI_CSS

    @pytest.mark.parametrize("token", ["#E6E8EE", "#8A93A6"])
    def test_body_text_meets_wcag_aa_on_both_surfaces(self, token):
        for background in ("#0B0D12", "#12151C", "#171B24"):
            ratio = contrast(token, background)
            assert ratio >= 4.5, f"{token} on {background} is {ratio:.2f}:1"

    @pytest.mark.parametrize("sector_id,accent", sorted(EXPECTED_ACCENT.items()))
    def test_every_accent_is_readable_on_the_dark_surfaces(self, sector_id, accent):
        for background in ("#0B0D12", "#12151C"):
            ratio = contrast(accent, background)
            assert ratio >= 4.5, f"{sector_id} accent {accent} is {ratio:.2f}:1 on {background}"

    def test_the_stylesheet_stays_small(self):
        assert len(core.UI_CSS.splitlines()) < 200
