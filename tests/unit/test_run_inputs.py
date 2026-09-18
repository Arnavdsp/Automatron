"""A step's tools inherit what the run was started with."""

import automatron_core as core
from tests import testsector


def tool_by_name(name):
    return next(spec.tool for spec in testsector.build_pack().tools if spec.name == name)


def test_a_blank_argument_is_filled_from_the_request():
    """The model names the case in prose but often omits it from the call."""
    measure = tool_by_name("measure")
    args, filled = core.apply_run_inputs(measure, {}, {"subject": "probe-9"})
    assert args == {"subject": "probe-9"}
    assert filled == ["subject"]


def test_an_empty_string_counts_as_blank():
    """A model that passes the schema default must not defeat the fallback."""
    measure = tool_by_name("measure")
    args, filled = core.apply_run_inputs(measure, {"subject": ""}, {"subject": "probe-9"})
    assert args["subject"] == "probe-9"
    assert filled == ["subject"]


def test_a_deliberate_argument_is_left_alone():
    """The model may know better than the request; it is not overridden."""
    measure = tool_by_name("measure")
    args, filled = core.apply_run_inputs(measure, {"subject": "probe-2"}, {"subject": "probe-9"})
    assert args["subject"] == "probe-2"
    assert filled == []


def test_nothing_the_tool_does_not_accept_is_passed():
    """Inputs are per workflow; tools would raise on an argument they never declared."""
    measure = tool_by_name("measure")
    args, filled = core.apply_run_inputs(
        measure, {}, {"subject": "probe-9", "threshold": 4.0, "unrelated": "x"})
    assert args == {"subject": "probe-9"}
    assert "unrelated" not in args and "threshold" not in args
    assert filled == ["subject"]


def test_blank_inputs_are_not_propagated():
    measure = tool_by_name("measure")
    args, filled = core.apply_run_inputs(measure, {}, {"subject": ""})
    assert args == {}
    assert filled == []


def test_a_tool_declaring_nothing_is_untouched():
    class Bare:
        name = "bare"

    args, filled = core.apply_run_inputs(Bare(), {"a": 1}, {"subject": "probe-9"})
    assert args == {"a": 1}
    assert filled == []


def test_the_parameters_come_from_the_tools_own_schema():
    classify = tool_by_name("classify")
    assert core.tool_parameter_names(classify) == {"value", "threshold"}
