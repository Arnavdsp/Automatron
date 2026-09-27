"""The tool loop asks for the opening tool call instead of paying to correct prose."""

import pytest

import automatron_core as core
from tests import testsector


class StubRouter:
    """Stands in for the provider chain and records how each round was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked = []
        self.rounds = []

    async def ainvoke(self, role, messages, tools=None, schema=None, on_event=None,
                      require_tool=False):
        self.asked.append(require_tool)
        self.rounds.append({"require_tool": require_tool, "schema": schema is not None})
        if schema is not None:
            return core.StepResultDraft(status="ok", summary="done", data={},
                                        missing_inputs=[])
        return self.replies.pop(0) if self.replies else core.AIMessage(content="done")


@pytest.fixture
def pack(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    core.reset_settings_cache()
    installed = testsector.install()
    yield installed
    core.clear_registry()
    core.reset_settings_cache()


async def run_with(stub, pack, tools):
    return await core.run_tool_agent(
        "analyst", "measure the subject", pack, "s1", tools=tools, router=stub,
    )


class TestTheOpeningTurnAsksForATool:
    async def test_the_first_round_asks_and_the_rest_do_not(self, pack):
        tool = pack.tools_for("analyst")[0]
        call = {"name": tool.name, "args": {}, "id": "c1"}
        stub = StubRouter([core.AIMessage(content="", tool_calls=[call]),
                           core.AIMessage(content="that is the answer")])
        await run_with(stub, pack, [tool])
        assert stub.asked[0] is True
        assert not any(stub.asked[1:]), "a later round was still being forced"

    async def test_a_step_with_no_tools_is_never_forced(self, pack):
        stub = StubRouter([core.AIMessage(content="nothing to call")])
        await run_with(stub, pack, [])
        assert not any(stub.asked)

    async def test_nothing_is_forced_on_the_structured_finish(self, pack):
        """The finish asks for a schema; a tool call there would be the wrong shape."""
        tool = pack.tools_for("analyst")[0]
        stub = StubRouter([core.AIMessage(content="", tool_calls=[
            {"name": tool.name, "args": {}, "id": "c1"}])])
        await run_with(stub, pack, [tool])
        finishes = [r for r in stub.rounds if r["schema"]]
        assert finishes, "the step never reached its structured finish"
        assert all(r["require_tool"] is False for r in finishes)
