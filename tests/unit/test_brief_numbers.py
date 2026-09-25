"""What counts as a number worth putting in a brief's quantitative table."""

import automatron_core as core


def test_a_key_is_judged_by_its_words_not_its_characters():
    """'account' and 'discount' both contain 'count', and neither is a measurement."""
    assert core._is_measure("account_opened") is False
    assert core._is_measure("discount_code") is False
    assert core._is_measure("account_age_days") is True
    assert core._is_measure("factor_count") is True


def test_measures_across_the_sectors_are_still_recognised():
    for key in ("pc", "miss_distance_m", "deflated_sharpe", "notional_usd",
                "approval_threshold_usd", "risk_score", "completeness", "value_usd"):
        assert core._is_measure(key) is True, key


def test_a_date_is_not_a_measurement():
    """An ISO date reads as numeric to a loose pattern, hyphens and all."""
    extracted = core._flatten_numbers({"t": {"filed_on": "2026-03-23", "days_open": 20}})
    assert "t days open" in extracted
    assert not any("2026-03-23" == value for value in extracted.values())


def test_booleans_and_prose_stay_out():
    extracted = core._flatten_numbers(
        {"t": {"high_value": True, "level": "RED", "score": 42}})
    assert extracted == {"t score": "42"}


def test_the_table_stays_small_enough_to_read():
    wide = {f"metric_{i}_count": i for i in range(50)}
    assert len(core._flatten_numbers({"t": wide})) <= 12


def test_the_level_shown_is_the_one_a_tool_decided():
    """A term mentioned elsewhere must not outrank the tool that made the call.

    A use table can report the level its own answer would suggest in isolation. If
    the brief picks the first vocabulary term it finds anywhere, that suggestion wins
    on vocabulary order alone and the brief shows a level nothing decided.
    """
    spec = _level_spec(["READY_FOR_EXAMINER", "CORRECTIONS_LIKELY", "HEARING_LIKELY"])
    completed = {
        "s3": {"data": {"use_permission": {"status": "permitted",
                                           "suggested_level": "READY_FOR_EXAMINER"}}},
        "s4": {"data": {"prescreen_outcome": {"level": "CORRECTIONS_LIKELY",
                                              "fail_count": 1}}},
    }
    assert core._level_from(completed, spec) == "CORRECTIONS_LIKELY"


def test_a_mention_is_still_used_when_no_tool_declared_a_level():
    spec = _level_spec(["READY_FOR_EXAMINER", "CORRECTIONS_LIKELY"])
    completed = {"s1": {"data": {"t": {"suggested_level": "CORRECTIONS_LIKELY"}}}}
    assert core._level_from(completed, spec) == "CORRECTIONS_LIKELY"


def test_the_first_vocabulary_entry_is_the_last_resort():
    spec = _level_spec(["ALPHA", "BETA"])
    assert core._level_from({"s1": {"data": {"t": {"note": "nothing here"}}}}, spec) == "ALPHA"


def _level_spec(vocabulary):
    """A minimal workflow spec carrying only the vocabulary under test."""
    from tests import testsector

    spec = testsector.build_pack().workflows[0]
    return spec.model_copy(update={"level_vocab": vocabulary})


class TestNumbersAreCopiedFromTools:
    """The spec has the quantitative table copied from tools, not written by a model."""

    def test_every_measured_scalar_is_carried(self):
        completed = {
            "s1": {"data": {"miss_distance_m": 570.272, "count": 4}},
            "s2": {"data": {"trend": {"latest_pc": 3.0e-4}}},
        }
        numbers = core.tool_quantities(completed)
        assert numbers["miss distance m"] == "570.272"
        assert numbers["count"] == "4"
        # Nested measures keep the path that gives them meaning.
        assert numbers["trend latest pc"] == "0.0003"

    def test_a_step_with_no_data_is_harmless(self):
        assert core.tool_quantities({"s1": {}, "s2": {"data": {}}, "s3": None}) == {}

    def test_steps_are_read_in_order(self):
        """A later step's value for the same label wins, as the step order implies."""
        completed = {"s2": {"data": {"pc": 2}}, "s1": {"data": {"pc": 1}}}
        assert list(core.tool_quantities(completed).values()) == ["2"]

    def test_synthesis_overrides_whatever_the_model_wrote(self):
        """Fake mode always builds the brief from tools, so only the live branch can
        regress here. Pin the override rather than leave it uncovered."""
        import inspect

        source = inspect.getsource(core.build_graph)
        assert "brief.quantitative_results = tool_quantities(completed)" in source, (
            "synthesis must copy the numbers from tool output, not keep the model's"
        )

    def test_live_steps_take_their_data_from_the_tools(self):
        """Fake mode already builds step data from tool output; the live branch used
        the model's copy, which is where reworded and missing figures came from."""
        import inspect

        source = inspect.getsource(core.run_tool_agent)
        assert "data = draft_from_tool_output(payloads).data" in source, (
            "a live step must report the data its tools returned, not the model's"
        )


class TestFinishingFromTheAgentsOwnAnswer:
    """A step's closing prose is its summary; restating it costs a call per step."""

    def test_the_agents_words_are_kept(self):
        prose = "Pc rose to 3.0e-04 across four messages, above the red threshold."
        draft = core.draft_from_reply(prose, [("pc_trend", {"latest_pc": 3.0e-4})])
        assert draft.summary == prose

    def test_the_numbers_still_come_from_the_tools(self):
        """The prose is the model's; the data is not."""
        draft = core.draft_from_reply(
            "I reckon the miss distance was about 900 m.",
            [("parse_cdm", {"miss_distance_m": 570.272, "count": 4})],
        )
        assert draft.data["parse_cdm"]["miss_distance_m"] == 570.272

    def test_a_failed_tool_still_makes_the_step_partial(self):
        draft = core.draft_from_reply("All good.", [("check_limits", {"error": "'quantity'"})])
        assert draft.status == "partial"

    def test_gaps_are_taken_from_what_the_tools_reported(self):
        draft = core.draft_from_reply(
            "The ticket is missing fields.",
            [("validate_ticket", {"problems": ["quantity absent", "no limit_price"]})],
        )
        assert draft.missing_inputs == ["quantity absent", "no limit_price"]

    def test_tool_gaps_are_deduplicated_and_capped(self):
        payloads = [("a", {"problems": ["x", "x"]}), ("b", {"missing": ["x", "y"]})]
        assert core.missing_from_tools(payloads) == ["x", "y"]

    def test_a_silent_agent_falls_back_to_the_tool_summary(self):
        """Nothing written means nothing to keep, so the tool account stands in."""
        draft = core.draft_from_reply("", [("parse_cdm", {"count": 4})])
        assert draft.summary and "parse_cdm" in draft.summary


class TestTheLevelComesFromTheTool:
    """The level is the decision; a tool works it out from thresholds."""

    class Spec:
        level_vocab = ["RED", "YELLOW", "GREEN"]

    def test_a_tools_classification_is_returned(self):
        completed = {"s1": {"data": {"classify": {"level": "RED", "pc": 3.0e-4}}}}
        assert core.declared_level(completed, self.Spec()) == "RED"

    def test_nothing_is_returned_when_no_tool_decided(self):
        """So a caller with a level of its own is not overruled by a guess."""
        completed = {"s1": {"data": {"pc": 3.0e-4, "note": "looks RED to me"}}}
        assert core.declared_level(completed, self.Spec()) is None

    def test_a_mention_is_not_a_decision(self):
        """A threshold named after a band is not the tool making the call."""
        completed = {"s1": {"data": {"thresholds_used": {"pc_red": 1e-4}}}}
        assert core.declared_level(completed, self.Spec()) is None

    def test_synthesis_prefers_the_tools_level(self):
        import inspect

        source = inspect.getsource(core.build_graph)
        assert "declared_level(completed, spec)" in source, (
            "synthesis must take the level from the tool that decided it"
        )
