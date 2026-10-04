"""The interface assembles, and the sector switch changes what the spec says it should."""

import asyncio
import re

import gradio as gr
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

    def test_the_accordion_header_cannot_grow_a_scrollbar(self):
        """Its padding puts it a few pixels wider than its box, and a few pixels is
        enough for a scrollbar the full width of the panel with nothing to scroll to."""
        rule = next((line for line in core.UI_CSS.splitlines()
                     if ".label-wrap" in line and "overflow-x" in line), "")
        assert "hidden" in rule, "nothing stops the structured-inputs header scrolling"

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
        """Restraint is about how many rules there are, not how well they are
        explained. Counting raw lines pushed toward deleting the comments that say
        why a rule exists, so count the lines that actually style something."""
        rules = [
            line for line in core.UI_CSS.splitlines()
            if line.strip() and not line.strip().startswith(("/*", "*", "*/"))
        ]
        assert len(rules) < 200, f"{len(rules)} styling lines"


def events_of(demo):
    """The handlers a built interface wired up, whichever shape Gradio stores them in."""
    fns = demo.fns
    return list(fns.values()) if isinstance(fns, dict) else list(fns)


class TestItReportsProgressOnlyWhereThereIsAny:
    """Gradio's default paints a spinner over every output of every event. On a
    page whose handlers mostly read state already in memory, that reads as the
    interface stalling on work it is not doing."""

    def test_no_handler_dims_all_of_its_outputs(self, ui_env):
        loud = [fn for fn in events_of(core.build_interface()) if fn.show_progress == "full"]
        assert not loud, f"{len(loud)} handler(s) still report full progress"

    def test_the_sector_switch_reports_nothing(self, ui_env):
        # It reads the registry and returns; there is no round trip worth showing.
        assert events_of(core.build_interface())[0].show_progress == "hidden"

    def test_a_run_reports_on_the_status_line_alone(self, ui_env):
        run = next(fn for fn in events_of(core.build_interface())
                   if fn.show_progress == "minimal" and len(fn.outputs) == 10)
        assert [getattr(c, "elem_id", None) for c in run.show_progress_on] == [None]
        assert run.show_progress_on[0] is run.outputs[0]


class TestSwitchingSectorLeavesNothingOfTheLastRun:
    def test_the_previous_run_is_let_go_of(self, ui_env):
        switch = events_of(core.build_interface())[0]
        returned = dict(zip(switch.outputs, switch.fn("space"), strict=True))
        held = [component for component in switch.outputs
                if type(component).__name__ == "State"]
        assert held, "the run id is not among the outputs"
        assert all(returned[component] == "" for component in held)

    def test_the_previous_run_s_downloads_go(self, ui_env):
        switch = events_of(core.build_interface())[0]
        returned = dict(zip(switch.outputs, switch.fn("space"), strict=True))
        buttons = [component for component in switch.outputs
                   if type(component).__name__ == "DownloadButton"]
        assert len(buttons) == 2
        assert all(returned[button].get("visible") is False for button in buttons)


def running_view(trace):
    return core.RunView(run_id="run-1", sector="space", workflow_id="space.probe",
                        status="running", brief=None, trace=trace,
                        awaiting_approval=False)


class TestTheTraceRepaintsOnAClockNotPerEvent:
    """Steps report in bursts. Redrawing the whole trace once per row arriving is
    what makes a long run feel heavier the further into it you get."""

    def run_handler(self, demo):
        return next(fn for fn in events_of(demo)
                    if fn.show_progress == "minimal" and len(fn.outputs) == 10)

    async def drain(self, ui_env, monkeypatch, events, view, gap=0.0):
        async def fake_stream(run_id, poll_seconds=0.4, owner_id=None, durable=None):
            for index, event in enumerate(events):
                if gap and index:
                    await asyncio.sleep(gap)
                yield event

        monkeypatch.setattr(core, "start_run", lambda *a, **k: _resolved("run-1"))
        monkeypatch.setattr(core, "stream_events", fake_stream)
        monkeypatch.setattr(core, "get_run", lambda run_id, **_: _resolved(view))
        handler = self.run_handler(core.build_interface()).fn
        return [frame async for frame in handler("space", "space.probe", "go", "{}", [])]

    async def test_a_burst_of_events_is_one_frame(self, ui_env, monkeypatch):
        view = running_view([])
        frames = await self.drain(ui_env, monkeypatch, [{"kind": "done"}] * 40, view)
        # One reset, at most one throttled frame for the burst, one final frame.
        assert len(frames) <= 3, f"{len(frames)} repaints for one burst of 40 events"

    async def test_the_panels_built_from_the_brief_wait_for_one(self, ui_env, monkeypatch):
        """Until synthesis there is no brief, so sending the evidence table and the
        JSON view their own unchanged empty state every frame is wasted payload."""
        view = running_view([{"kind": "done", "message": "m", "agent": "analyst",
                              "at": "2026-01-01T00:00:00Z"}])
        # Spread over more than one repaint window, so frames do get through and
        # the assertion is about what they carry rather than that there are none.
        frames = await self.drain(ui_env, monkeypatch, [{"kind": "done"}] * 3, view,
                                  gap=core.UI_REPAINT_SECONDS + 0.1)
        streamed = frames[1:-1]
        assert streamed, "the run never painted a frame while it was working"
        for frame in streamed:
            for index in (1, 3, 4):  # brief, evidence, JSON
                assert isinstance(frame[index], type(gr.skip())), (
                    f"output {index} was re-sent with nothing new in it")


def _resolved(value):
    async def wait():
        return value
    return wait()


class TestAskingTwiceDoesNotBuyTwoRuns:
    """A run costs real provider quota and a minute or two of wall time. A second
    click on an unchanged form is nearly always a mis-click or someone checking the
    page is alive."""

    def run_handler(self, demo):
        return next(fn for fn in events_of(demo)
                    if fn.show_progress == "minimal" and len(fn.outputs) == 10)

    async def press_run(self, monkeypatch, started, view, request="go", inputs="{}"):
        keys = []

        async def fake_start(sector, workflow_id, req, ins, uploads, idempotency_key="",
                             owner_id=core.LOCAL_TENANT, durable=None):
            keys.append(idempotency_key)
            return started

        async def fake_stream(run_id, poll_seconds=0.4, owner_id=None, durable=None):
            for event in []:
                yield event

        monkeypatch.setattr(core, "start_run", fake_start)
        monkeypatch.setattr(core, "stream_events", fake_stream)
        monkeypatch.setattr(core, "get_run", lambda run_id, **_: _resolved(view))
        handler = self.run_handler(core.build_interface()).fn
        frames = [frame async for frame in
                  handler("space", "space.probe", request, inputs, [])]
        return keys[0], frames

    async def test_the_same_request_carries_the_same_key(self, ui_env, monkeypatch):
        view = running_view([])
        first, _ = await self.press_run(monkeypatch, "run-1", view)
        again, _ = await self.press_run(monkeypatch, "run-1", view)
        assert first and first == again

    async def test_a_changed_request_carries_a_different_one(self, ui_env, monkeypatch):
        view = running_view([])
        first, _ = await self.press_run(monkeypatch, "run-1", view, request="go")
        other, _ = await self.press_run(monkeypatch, "run-2", view, request="go further")
        assert first != other

    async def test_changed_inputs_carry_a_different_one(self, ui_env, monkeypatch):
        view = running_view([])
        first, _ = await self.press_run(monkeypatch, "run-1", view, inputs='{"a": 1}')
        other, _ = await self.press_run(monkeypatch, "run-2", view, inputs='{"a": 2}')
        assert first != other

    async def test_a_replayed_run_says_so_instead_of_looking_instant(self, ui_env,
                                                                     monkeypatch):
        """A brief that appears at once should explain why, or a reader will fairly
        wonder whether the work happened at all."""
        view = running_view([{"kind": "done", "message": "m", "agent": "analyst",
                              "ts": "2026-01-01T09:30:00Z"}])
        monkeypatch.setattr(core, "run_for_key", lambda key: "run-earlier")
        _, frames = await self.press_run(monkeypatch, "run-earlier", view)
        assert "Replayed" in frames[-1][0]
        assert "09:30 UTC" in frames[-1][0]

    async def test_a_fresh_run_says_nothing_of_the_sort(self, ui_env, monkeypatch):
        view = running_view([])
        monkeypatch.setattr(core, "run_for_key", lambda key: None)
        _, frames = await self.press_run(monkeypatch, "run-1", view)
        assert not any("Replayed" in frame[0] for frame in frames)


class TestAReplayedRunStillTellsItsReviewerWhereItStands:
    def test_the_note_sits_beside_the_status_rather_than_over_it(self):
        view = running_view([])
        view.status = "awaiting_approval"
        rendered = core.status_line(view, note="Replayed from 09:30 UTC.")
        assert "Waiting for your decision." in rendered
        assert "Replayed from 09:30 UTC." in rendered

    def test_with_no_note_nothing_extra_is_rendered(self):
        view = running_view([])
        view.status = "awaiting_approval"
        assert core.status_line(view) == core.status_line(view, note="")
