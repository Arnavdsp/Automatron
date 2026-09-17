"""Real calls against each configured provider. Run with: pytest -q -m live

Skipped entirely when no keys are present, and per provider when that provider's
key is missing. Every test here spends free-tier quota, so each one is tiny.
"""

import pytest
from pydantic import BaseModel, Field

import automatron_core as core

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="module")]

PROMPT = [core.HumanMessage(content="Reply with the single word: ok")]


class Verdict(BaseModel):
    level: str = Field(description="one of GREEN, AMBER, RED")


@pytest.fixture(scope="module")
def live_settings():
    """Undo the hermetic fixture so real keys are read for this module only."""
    import os

    from dotenv import load_dotenv

    env_file = core.ROOT / ".env"
    if not env_file.is_file():
        pytest.skip("no .env file; live tests need provider keys")

    load_dotenv(env_file, override=True)
    previous = os.environ.get("AUTOMATRON_FAKE_LLM")
    os.environ["AUTOMATRON_FAKE_LLM"] = "0"
    core.Settings.model_config["env_file"] = str(env_file)
    core.reset_settings_cache()

    settings = core.get_settings()
    if not settings.configured_providers:
        pytest.skip("no provider keys configured")
    yield settings

    if previous is None:
        os.environ.pop("AUTOMATRON_FAKE_LLM", None)
    else:
        os.environ["AUTOMATRON_FAKE_LLM"] = previous
    core.Settings.model_config["env_file"] = None
    core.reset_settings_cache()


@pytest.fixture
def live_router(live_settings):
    router = core.build_router(live_settings)
    assert not router.fake, "live tests must not run against the scripted model"
    return router


def skip_if_account_blocked(exc: BaseException, slot) -> None:
    """Billing and an exhausted daily allowance are account states, not defects."""
    kind = core.classify_error(exc)
    if kind == core.AUTH and "payment" in str(exc).lower():
        pytest.skip(f"{slot.name}: provider needs billing enabled on the account")
    if kind == core.DAILY_QUOTA:
        pytest.skip(f"{slot.name}: free daily allowance is used up")
    raise exc


def slots_of(router, provider):
    return [s for s in router.slots.values() if s.provider == provider]


@pytest.fixture(params=core.PROVIDER_ORDER)
def provider_slot(request, live_router, live_settings):
    if not live_settings.has_key(request.param):
        pytest.skip(f"no key for {request.param}")
    slots = slots_of(live_router, request.param)
    if not slots:
        pytest.skip(f"{request.param} has no configured slot")
    return slots[0]


async def test_provider_answers_a_tiny_call(provider_slot):
    """A plain completion round-trip, which is the minimum a provider must do."""
    model = provider_slot.build_model()
    try:
        reply = await model.ainvoke(PROMPT)
    except Exception as exc:
        skip_if_account_blocked(exc, provider_slot)
    assert core.message_text(reply).strip(), f"{provider_slot.name} returned empty content"


async def test_provider_round_trips_a_tool_call(provider_slot):
    """The agent loop depends on tool calls, so each provider has to offer them."""
    if not provider_slot.supports_tools:
        pytest.skip(f"{provider_slot.name} is not configured for tools")

    from langchain_core.tools import tool

    @tool
    def miss_distance_m(primary: str, secondary: str) -> float:
        """Return the miss distance in metres between two catalogued objects."""
        return 412.0

    model = provider_slot.build_model().bind_tools([miss_distance_m])
    try:
        ask = "Use the tool to get the miss distance for SAT-1 and DEB-9."
        reply = await model.ainvoke([core.HumanMessage(content=ask)])
    except Exception as exc:
        skip_if_account_blocked(exc, provider_slot)
    assert reply.tool_calls, f"{provider_slot.name} did not request the tool"
    assert reply.tool_calls[0]["name"] == "miss_distance_m"


async def test_router_prefers_a_healthy_provider_for_each_role(live_router):
    """One call per role through the router, exercising the real chains."""
    for role in core.AGENT_ROLES:
        reply = await live_router.ainvoke(role, PROMPT)
        assert core.message_text(reply).strip(), f"role {role} produced nothing"


async def test_router_fails_over_when_the_primary_is_forced_to_fail(live_router):
    """Force the head of the coordinator chain to 429 and confirm the run survives."""
    chain = live_router.chain("coordinator")
    if len(chain) < 2:
        pytest.skip("need at least two providers to test failover")

    head = chain[0]
    live_router.force_error(head.name, core.RATE_LIMIT, retry_after=5)
    try:
        events = []
        reply = await live_router.ainvoke("coordinator", PROMPT, on_event=events.append)
    finally:
        live_router.force_error(head.name, None)
        head.state = "ok"
        head.cooldown_until = None

    assert core.message_text(reply).strip()
    assert any(event["kind"] == "failover" for event in events)
