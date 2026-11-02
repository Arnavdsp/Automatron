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


def slow_tools(delay):
    """Three tools that each take a while, as a data fetch or an embedding would."""
    import time

    made = []
    for name in ("first", "second", "third"):
        def body(subject: str = "x", _name=name) -> dict:
            """Report on the subject."""
            time.sleep(delay)
            return {"tool": _name, "subject": subject, "value": len(_name)}
        body.__name__ = name
        made.append(core.tool(body))
    return made


class TestOneReplysToolsRunTogether:
    """A model that asks for several tools in one reply has said none depends on
    another. Their waits overlap; what is recorded does not change."""

    def reply(self, tools, *, repeat_first=False):
        calls = [{"name": t.name, "args": {"subject": "probe-1"}, "id": f"c{i}"}
                 for i, t in enumerate(tools)]
        if repeat_first:
            calls.append({**calls[0], "id": "c-repeat"})
        return core.AIMessage(content="", tool_calls=calls)

    async def test_three_slow_tools_take_about_as_long_as_one(self, pack):
        import time

        tools = slow_tools(0.4)
        stub = StubRouter([self.reply(tools), core.AIMessage(content="done")])
        started = time.monotonic()
        await run_with(stub, pack, tools)
        assert time.monotonic() - started < 0.9, "the tool calls ran one after another"

    async def test_evidence_keeps_the_order_the_calls_were_asked_in(self, pack):
        tools = slow_tools(0.0)
        # The slowest first: finishing order must not decide the evidence order.
        tools[0] = slow_tools(0.3)[0]
        stub = StubRouter([self.reply(tools), core.AIMessage(content="done")])
        result = await run_with(stub, pack, tools)
        assert [(e.id, e.label) for e in result.evidence] == [
            ("T1", "first"), ("T2", "second"), ("T3", "third")]

    async def test_a_call_repeated_in_the_same_reply_runs_once(self, pack):
        calls = []
        tools = slow_tools(0.0)
        original = tools[0].func

        def counted(subject: str = "x") -> dict:
            """Report on the subject."""
            calls.append(subject)
            return original(subject)

        counted.__name__ = "first"
        tools[0] = core.tool(counted)
        stub = StubRouter([self.reply(tools, repeat_first=True),
                           core.AIMessage(content="done")])
        result = await run_with(stub, pack, tools)
        assert calls == ["probe-1"]
        assert len(result.evidence) == 3
