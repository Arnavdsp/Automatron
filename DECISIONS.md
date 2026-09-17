# Decisions

Design choices made while building Automatron, with the reasoning behind them.

## D1 — Existing root commit keeps its original author

The repository was created through the GitHub web interface, so the root commit carries the
account's web identity rather than the project author identity used for every later commit.
Rewriting it would require a force push to `main`, which is not worth the disruption to
anyone who has already cloned the repository. All subsequent commits use
`Arnav <arnavhpd@gmail.com>`.

## D2 — Repository hygiene checks run locally, not in tracked files

Checks for staged credentials, stored notebook outputs, and private working files run as
local git hooks under `.git/hooks/`, which git does not track by design. Each clone installs
them separately. This keeps working-environment configuration out of the published history.

## D3 — Gemini model chosen by measurement, not by version number

An earlier revision of this entry kept `gemini-2.5-flash`, reasoning from the published
documentation that it carried a much larger free daily request budget. A live call
disproved it: the models endpoint still lists `gemini-2.5-flash`, but `generateContent`
answers 404, "no longer available to new users". Documentation and model listings both lag
the API, so model ids are confirmed by calling them.

Among the 3.x Flash models that do answer, three probes each gave `gemini-3.5-flash` three
successes averaging about 1.4 seconds, `gemini-3.8-flash` three successes averaging about
12 seconds, and `gemini-3.6-flash` two successes out of three. The coordinator makes up to
four calls per run against a 90-second budget to the approval gate, so the slowest option
would spend most of that budget before any sub-agent ran. `gemini-3.5-flash` is the default
for latency and availability; `GEMINI_MODEL` switches it without a code change, and the
quality pass is the right point to retest whether a slower, newer model plans well enough
to be worth the time.

Free-tier 3.x capacity is visibly contended: probes returned 503 "experiencing high demand"
often enough that the router's transient-error handling matters more here than the daily
quota logic.

## D4 — Cerebras free-tier figures corrected

The free tier serves a 65,536-token context window, not the ~8,000 originally assumed, and
paces at 5 requests per minute with a 1,000,000-token daily budget. The daily request value
in `config/providers.yaml` is derived from that token budget, since the provider publishes
no request-per-day cap. The larger window removes the earlier concern that analyst steps
would have to be aggressively compacted before every call.

## D5 — OpenRouter model chain

`config/providers.yaml` lists four free models that advertise tool support, tried in order
and chosen for general-purpose instruction following, a large context window, and vendor
spread so that one vendor's outage does not empty the chain. Free models are capped at 20
requests per minute for everyone, and 50 requests per day until an account has purchased
credits, at which point the daily cap rises substantially.

## D6 — Cerebras needs billing enabled before it serves traffic

The Cerebras key authenticates and the models endpoint lists `gpt-oss-120b`, but inference
returns 402, "payment required to access this resource". The free allowance is released
only once an account has a verified payment method on file. Until that is done the provider
is configured but unusable, so the router drops it after the first failure and the analyst
role falls through to Groq. The account holder enables billing; no code change applies.

## D7 — Live provider tests skip on account limits rather than failing

A provider that answers "payment required" or "daily allowance used up" is reporting the
state of an account, not a defect in this code. Those two cases skip with the provider named
in the reason, so a run of the live suite still shows at the top whether each provider is
reachable, while a genuine fault, an empty completion or a refused tool call, still fails.

## D8 — The live suite shares one event loop

The provider SDKs cache async HTTP clients globally, so a client built during one test is
reused by the next. With a fresh event loop per test that reuse raises "Event loop is
closed" partway through the run, and closing the clients between tests is worse because the
cache is shared. The live module therefore runs on a single module-scoped loop, which is
also how the application runs: one long-lived loop for the process.

## D9 — A second Groq key stands in for Cerebras

Cerebras authenticates but refuses inference until the account has billing enabled, which left
the analyst role without its intended primary. Groq serves `openai/gpt-oss-120b`, the same model
Cerebras was providing, so a second Groq key now leads the analyst chain. Two keys on one
provider matter because rate limits are counted per key: the analyst gets its own bucket rather
than competing with the executor for the first key's allowance. Cerebras stays defined and sits
at the tail of every chain, so enabling billing restores it by editing the role lists alone.

## D10 — Front matter that fails to parse is logged, not swallowed

A knowledge file whose YAML header was invalid used to be indexed with no title and no source
url, which produced passages that could be retrieved but not cited, with nothing explaining why.
A title containing an unquoted colon caused exactly this and was only noticed because a test
checked the committed files rather than the parser. Parse failures now log a warning and the
body is still indexed.

## D11 — Mistral joins the chain on the ministral models only

Of the tool-capable models the Mistral key can list, only the ministral family actually answers
on this tier. `mistral-small-latest` and `magistral-small-latest` return 429 even when calls are
spaced several seconds apart, so the 429 reflects tier access rather than pacing, and
`mistral-large-latest` returns 403 outright. The provider is therefore configured with
`ministral-14b`, `ministral-8b` and `ministral-3b`, expanding into one slot per model in the same
way as OpenRouter. Mistral sits mid-chain for every role: behind the provider each role prefers,
ahead of the ones held in reserve.

## D12 — Redaction masks configured secret values, not just recognisable shapes

Key patterns only catch credentials with a distinctive prefix. The Mistral key is a plain
32-character string that no pattern can match without also matching ordinary text, so it passed
through redaction untouched and would have appeared in logs and trace events. Redaction now also
replaces the literal value of every secret the process was configured with, which covers any
provider whose key format carries no marker. Values shorter than twelve characters are left
alone, since masking those would blank out ordinary words.
