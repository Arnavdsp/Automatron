"""Provider routing: classification, cooldowns, quota reservation, failover."""

import asyncio
import datetime as dt

import pytest
from pydantic import BaseModel

import automatron_core as core


class Reply(BaseModel):
    verdict: str = "ok"


def slot(name, provider=None, **overrides):
    """A fake-backed slot paced fast enough that the limiter never gates a test."""
    options = {
        "provider": provider or name,
        "model": f"{name}-model",
        "kind": "fake",
        "api_key": "test",
        "context_tokens": 100_000,
        "rpm": 6000,
        "rpd": 1000,
        "supports_structured": True,
    }
    options.update(overrides)
    return core.ProviderSlot(name=name, **options)


def router(*slots, chains=None, reservation=None):
    names = [s.name for s in slots]
    return core.ProviderRouter(
        list(slots),
        chains or {role: list(names) for role in core.AGENT_ROLES},
        reservation or {},
    )


@pytest.fixture(autouse=True)
def backoffs(monkeypatch):
    """Skip the jitter wait, and record each backoff so retries can be counted."""
    recorded = []

    def instant(low, high):
        recorded.append((low, high))
        return 0

    monkeypatch.setattr(core.random, "uniform", instant)
    return recorded


class TestClassification:
    def make(self, name, message="", status=None, headers=None):
        namespace = {}
        if status is not None:
            namespace["status_code"] = status
        if headers is not None:
            namespace["response"] = type("R", (), {"headers": headers})()
        exc_type = type(name, (Exception,), namespace)
        return exc_type(message)

    def test_rate_limit_from_status(self):
        assert core.classify_error(self.make("APIStatusError", "slow down", 429)) == core.RATE_LIMIT

    def test_rate_limit_from_message(self):
        assert core.classify_error(self.make("Boom", "Rate limit reached")) == core.RATE_LIMIT

    def test_resource_exhausted_is_a_rate_limit(self):
        assert core.classify_error(self.make("Boom", "RESOURCE_EXHAUSTED")) == core.RATE_LIMIT

    def test_daily_quota_beats_plain_rate_limit(self):
        exc = self.make("APIStatusError", "quota exceeded: requests per day", 429)
        assert core.classify_error(exc) == core.DAILY_QUOTA

    def test_auth_from_status(self):
        assert core.classify_error(self.make("AuthError", "nope", 401)) == core.AUTH
        assert core.classify_error(self.make("AuthError", "nope", 403)) == core.AUTH

    def test_payment_required_is_auth(self):
        exc = self.make("APIStatusError", "Payment required to access this resource", 402)
        assert core.classify_error(exc) == core.AUTH

    def test_model_gone(self):
        exc = self.make("NotFoundError", "model is no longer available", 404)
        assert core.classify_error(exc) == core.MODEL_GONE

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_errors_are_transient(self, status):
        assert core.classify_error(self.make("ServerError", "upstream", status)) == core.TRANSIENT

    def test_timeout_is_transient(self):
        assert core.classify_error(TimeoutError("timed out")) == core.TRANSIENT

    def test_connection_error_is_transient(self):
        assert core.classify_error(self.make("APIConnectionError", "reset")) == core.TRANSIENT

    def test_context_overflow(self):
        exc = self.make("BadRequestError", "maximum context length exceeded", 400)
        assert core.classify_error(exc) == core.CONTEXT

    def test_unclassified_is_other(self):
        assert core.classify_error(self.make("Weird", "something", 418)) == core.OTHER

    def test_retry_after_seconds_header(self):
        exc = self.make("APIStatusError", "slow", 429, {"retry-after": "5"})
        assert core.retry_after_seconds(exc) == 5.0

    def test_retry_after_http_date(self):
        when = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
        stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
        exc = self.make("APIStatusError", "slow", 429, {"retry-after": stamp})
        assert 20 <= core.retry_after_seconds(exc) <= 40

    def test_missing_retry_after(self):
        assert core.retry_after_seconds(self.make("APIStatusError", "slow", 429)) is None


class TestCooldownPolicy:
    def test_rate_limit_uses_retry_after(self):
        s = slot("groq")
        s.apply_policy(core.RATE_LIMIT, core.ForcedError(core.RATE_LIMIT, retry_after=5))
        assert s.state == "cooldown"
        remaining = (s.cooldown_until - dt.datetime.now(dt.UTC)).total_seconds()
        assert 3 <= remaining <= 7

    def test_rate_limit_backs_off_further_on_repeats(self):
        s = slot("groq")
        s.apply_policy(core.RATE_LIMIT)
        first = (s.cooldown_until - dt.datetime.now(dt.UTC)).total_seconds()
        s.apply_policy(core.RATE_LIMIT)
        second = (s.cooldown_until - dt.datetime.now(dt.UTC)).total_seconds()
        assert second > first

    def test_rate_limit_backoff_is_capped(self):
        s = slot("groq")
        for _ in range(12):
            s.apply_policy(core.RATE_LIMIT)
        remaining = (s.cooldown_until - dt.datetime.now(dt.UTC)).total_seconds()
        assert remaining <= core.RATE_LIMIT_COOLDOWN_MAX + 1

    def test_daily_quota_waits_for_utc_midnight(self):
        s = slot("gemini")
        s.apply_policy(core.DAILY_QUOTA)
        assert s.state == "cooldown"
        assert s.cooldown_until.date() == core.next_utc_midnight().date()
        assert s.cooldown_until.hour == 0

    def test_auth_disables_for_the_process(self):
        s = slot("groq")
        s.apply_policy(core.AUTH, Exception("invalid api key"))
        assert s.state == "disabled"
        assert s.available_now()[0] is False

    def test_model_gone_disables(self):
        s = slot("gemini")
        s.apply_policy(core.MODEL_GONE)
        assert s.state == "disabled"

    def test_context_does_not_cool_the_slot_down(self):
        s = slot("cerebras")
        s.apply_policy(core.CONTEXT)
        assert s.state == "ok"
        assert s.available_now()[0] is True

    def test_other_errors_cool_down_only_after_three(self):
        s = slot("groq")
        s.apply_policy(core.OTHER)
        s.apply_policy(core.OTHER)
        assert s.state == "ok"
        s.apply_policy(core.OTHER)
        assert s.state == "cooldown"

    def test_slot_recovers_once_the_cooldown_passes(self):
        s = slot("groq")
        s.apply_policy(core.RATE_LIMIT)
        assert s.available_now()[0] is False
        s.cooldown_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        assert s.available_now()[0] is True
        assert s.state == "ok"

    def test_success_clears_the_failure_streak(self):
        s = slot("groq")
        s.apply_policy(core.OTHER)
        s.on_success()
        assert s.failures_in_row == 0
        assert s.calls_today == 1

    def test_missing_key_slot_is_never_tried(self):
        s = core.ProviderSlot(name="groq", provider="groq", model="m", kind="groq", api_key="")
        assert s.state == "missing_key"
        assert s.available_now()[0] is False


class TestFailover:
    async def test_rate_limited_primary_falls_through_to_the_next(self):
        primary, backup = slot("gemini"), slot("groq")
        r = router(primary, backup)
        r.force_error("gemini", core.RATE_LIMIT, retry_after=5)

        events = []
        reply = await r.ainvoke(
            "coordinator", [core.HumanMessage(content="hi")], on_event=events.append
        )

        assert core.message_text(reply) == "ok"
        assert primary.state == "cooldown"
        remaining = (primary.cooldown_until - dt.datetime.now(dt.UTC)).total_seconds()
        assert 3 <= remaining <= 7
        assert backup.calls_today == 1
        assert [e["kind"] for e in events] == ["failover", "done"]

    async def test_recovered_primary_is_used_again(self):
        primary, backup = slot("gemini"), slot("groq")
        r = router(primary, backup)
        r.force_error("gemini", core.RATE_LIMIT, retry_after=5)
        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])

        r.force_error("gemini", None)
        primary.cooldown_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])

        assert primary.calls_today == 1
        assert primary.state == "ok"

    async def test_auth_failure_skips_the_slot_without_calling_it_again(self):
        primary, backup = slot("gemini"), slot("groq")
        r = router(primary, backup)
        r.force_error("gemini", core.AUTH)

        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])
        assert primary.state == "disabled"

        # Still forced to fail, but a disabled slot is never reached.
        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])
        assert backup.calls_today == 2
        assert primary.calls_today == 0

    async def test_transient_error_retries_the_same_slot_first(self, backoffs):
        primary, backup = slot("gemini"), slot("groq")
        r = router(primary, backup)
        r.force_error("gemini", core.TRANSIENT)

        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])

        # Exactly one backoff means the primary was tried twice before moving on.
        assert len(backoffs) == 1
        assert primary.state == "cooldown"
        assert backup.calls_today == 1

    async def test_rate_limit_does_not_retry_the_same_slot(self, backoffs):
        primary, backup = slot("gemini"), slot("groq")
        r = router(primary, backup)
        r.force_error("gemini", core.RATE_LIMIT)

        await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])
        assert backoffs == [], "a rate limit should fail over at once, not retry"

    async def test_context_overflow_moves_on_without_a_cooldown(self):
        small = slot("cerebras", context_tokens=100)
        big = slot("groq", context_tokens=100_000)
        r = router(small, big, chains={"analyst": ["cerebras", "groq"]})

        long_prompt = [core.HumanMessage(content="x" * 40_000)]
        await r.ainvoke("analyst", long_prompt)

        assert small.state == "ok", "a context miss is about this call, not the provider"
        assert small.cooldown_until is None
        assert big.calls_today == 1

    async def test_analyst_oversize_input_is_compacted_before_giving_up(self):
        # Fits only once the tool output has been trimmed.
        only = slot("cerebras", context_tokens=2200)
        r = router(only, chains={"analyst": ["cerebras"]})
        messages = [
            core.HumanMessage(content="assess this"),
            core.ToolMessage(content="y" * 20_000, tool_call_id="t1"),
        ]
        reply = await r.ainvoke("analyst", messages)
        assert core.message_text(reply) == "ok"

    async def test_every_slot_failing_raises_with_the_earliest_retry(self):
        a, b = slot("gemini"), slot("groq")
        r = router(a, b)
        r.force_error("gemini", core.RATE_LIMIT, retry_after=5)
        r.force_error("groq", core.RATE_LIMIT, retry_after=600)

        with pytest.raises(core.AllProvidersUnavailable) as caught:
            await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])

        error = caught.value
        assert set(error.reasons) == {"gemini", "groq"}
        assert error.earliest_retry == a.cooldown_until
        assert "earliest retry" in str(error)

    async def test_empty_chain_is_reported_clearly(self):
        r = core.ProviderRouter([], {"coordinator": []})
        with pytest.raises(core.AllProvidersUnavailable):
            await r.ainvoke("coordinator", [core.HumanMessage(content="hi")])


class TestQuotaReservation:
    def test_coordinator_is_never_blocked(self):
        s = slot("gemini", rpd=100)
        s.calls_today = 99
        r = router(s, reservation={"gemini": {"coordinator": 0.6}})
        assert r.quota_allows(s, "coordinator") is True

    def test_researcher_is_cut_off_at_the_reserved_share(self):
        s = slot("gemini", rpd=100)
        r = router(s, reservation={"gemini": {"coordinator": 0.6}})

        s.calls_today = 39
        assert r.quota_allows(s, "researcher") is True
        s.calls_today = 40
        assert r.quota_allows(s, "researcher") is False

    def test_providers_without_a_reservation_are_unrestricted(self):
        s = slot("groq", rpd=100)
        s.calls_today = 99
        r = router(s, reservation={"gemini": {"coordinator": 0.6}})
        assert r.quota_allows(s, "researcher") is True

    async def test_reserved_budget_pushes_the_researcher_to_the_next_provider(self):
        gemini, groq = slot("gemini", rpd=10), slot("groq")
        gemini.calls_today = 9
        r = router(
            gemini,
            groq,
            chains={"researcher": ["gemini", "groq"]},
            reservation={"gemini": {"coordinator": 0.6}},
        )

        await r.ainvoke("researcher", [core.HumanMessage(content="hi")])
        assert groq.calls_today == 1
        assert gemini.calls_today == 9


class TestStructuredOutput:
    async def test_structured_call_returns_the_schema(self):
        s = slot("groq")
        s.build_model().structured_result = {"verdict": "RED"}
        r = router(s)
        result = await r.ainvoke("analyst", [core.HumanMessage(content="hi")], schema=Reply)
        assert isinstance(result, Reply)
        assert result.verdict == "RED"

    def test_json_parsing_strips_code_fences(self):
        parsed = core.parse_structured(Reply, '```json\n{"verdict": "GREEN"}\n```')
        assert parsed.verdict == "GREEN"

    def test_json_parsing_tolerates_surrounding_prose(self):
        parsed = core.parse_structured(Reply, 'Here you go: {"verdict": "AMBER"} hope that helps')
        assert parsed.verdict == "AMBER"

    def test_json_instruction_carries_the_schema(self):
        instruction = core.json_instruction(Reply)
        assert "verdict" in instruction
        assert "only JSON" in instruction


class TestDaySafety:
    def test_counters_reset_when_the_day_rolls_over(self):
        s = slot("groq")
        s.calls_today = 50
        s.quota_day = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
        s.roll_day()
        assert s.calls_today == 0

    def test_status_shape_is_what_the_interface_renders(self):
        s = slot("groq")
        status = s.status()
        assert set(status) == {
            "name",
            "provider",
            "model",
            "state",
            "cooldown_until",
            "calls_today",
            "last_error",
        }


class TestEmptyStructuredOutput:
    """A provider can answer with nothing that parses. That is not an answer."""

    def empty_structured_slot(self, name, monkeypatch):
        """A slot whose structured call resolves to None, as providers sometimes do."""
        s = slot(name)

        class NoStructure:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                return None

        monkeypatch.setattr(s, "build_model", lambda: NoStructure())
        return s

    async def test_none_is_not_returned_to_the_caller(self, monkeypatch):
        """Returning None reads as success; callers only find out on attribute access."""
        empty = self.empty_structured_slot("empty", monkeypatch)
        with pytest.raises(core.AllProvidersUnavailable):
            await router(empty).ainvoke("coordinator", [], schema=Reply)

    async def test_the_next_provider_gets_a_chance(self, monkeypatch):
        """One model failing to hold a shape must not cost the run its brief."""
        empty = self.empty_structured_slot("empty", monkeypatch)
        working = slot("working")
        result = await router(empty, working).ainvoke("coordinator", [], schema=Reply)
        assert isinstance(result, Reply)


class TestTheDeadlineIsEnforced:
    """The SDKs take a timeout and do not always keep to it."""

    def stalling_slot(self, name, monkeypatch, seconds=120):
        s = slot(name)

        class Stalls:
            def bind_tools(self, tools):
                return self

            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                await asyncio.sleep(seconds)
                raise AssertionError("the deadline did not fire")

        monkeypatch.setattr(s, "build_model", lambda: Stalls())
        return s

    async def test_a_stalling_provider_does_not_hold_the_run(self, monkeypatch):
        monkeypatch.setattr(core, "REQUEST_TIMEOUT_S", 0)
        monkeypatch.setattr(core, "TIMEOUT_GRACE_S", 0.05)
        stalls = self.stalling_slot("stalls", monkeypatch)
        with pytest.raises(core.AllProvidersUnavailable):
            await router(stalls).ainvoke("coordinator", [])

    async def test_the_next_provider_answers_instead(self, monkeypatch):
        monkeypatch.setattr(core, "REQUEST_TIMEOUT_S", 0)
        monkeypatch.setattr(core, "TIMEOUT_GRACE_S", 0.05)
        stalls = self.stalling_slot("stalls", monkeypatch)
        result = await router(stalls, slot("quick")).ainvoke("coordinator", [])
        assert result is not None

    async def test_a_stalled_slot_is_not_retried_on_the_spot(self, monkeypatch):
        """Retrying it would spend the whole deadline over again."""
        monkeypatch.setattr(core, "REQUEST_TIMEOUT_S", 0)
        monkeypatch.setattr(core, "TIMEOUT_GRACE_S", 0.05)
        stalls = self.stalling_slot("stalls", monkeypatch)
        attempts = []
        original = stalls.build_model
        monkeypatch.setattr(stalls, "build_model",
                            lambda: (attempts.append(1), original())[1])
        with pytest.raises(core.AllProvidersUnavailable):
            await router(stalls).ainvoke("coordinator", [])
        assert len(attempts) == 1, f"tried the stalled slot {len(attempts)} times"
