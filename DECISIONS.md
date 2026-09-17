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

## D3 — Gemini stays on the 2.5 Flash model

Newer 3.x Flash models are free-tier eligible, but their published free daily request
caps are an order of magnitude tighter. The coordinator is the heaviest caller in every
run, so a larger daily request budget matters more here than newer model capabilities.
`gemini-2.5-flash` remains free-tier eligible and keeps roughly 250 requests per day
against roughly 20 for the newest Flash model, which is the difference between a demo
that serves dozens of runs a day and one that serves three. `GEMINI_MODEL` overrides it
without a code change.

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
