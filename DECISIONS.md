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

## D13 — Fake slots are not rate limited

In fake mode every slot answers instantly from a script, but the slots were still built with
each provider's real requests-per-minute figure, so the client-side limiter paced calls against
a provider that was never contacted. A single run spent roughly eighteen seconds waiting, almost
all of it on the coordinator's two calls against a ten-per-minute allowance. Fake slots now use a
nominal high rate instead, which took the graph test suite from about seven minutes to seven
seconds and matters as much for the offline demo as for the tests.

## D14 — The checkpointer is closed explicitly

The SQLite checkpointer runs its connection on a non-daemon thread, so a process that never
closes it does not exit: the graph work finishes, the last line prints, and the interpreter then
hangs forever. `close_run_service()` cancels in-flight runs and closes the connection, and both
the tests and the application shutdown path call it.

## D15 — Provider dots are rendered from configuration, not fixed at four

The interface specification describes four status dots, one per provider, from when the chain
held exactly four. The chain now holds six providers across eleven slots, because OpenRouter and
Mistral each contribute one slot per model. The header therefore renders one dot per provider
taken from the live router, collapsing a provider's several models into its worst state, and a
provider added or removed in `config/providers.yaml` appears or disappears without a code change.

## D16 — Shutdown suppresses CancelledError explicitly

Startup puts knowledge seeding on a background task and shutdown cancels it. `CancelledError`
derives from `BaseException` rather than `Exception`, so suppressing `Exception` alone let it
escape and made every clean shutdown raise. The suppression now names it.

## D17 — Demo mode assembles briefs from tool output rather than scripting prose

Offline runs execute the real tools; only the model is replaced. A canned brief would
therefore cite numbers the tools did not produce, and the verifier would reject it for exactly
the right reason. Demo mode instead builds both the step results and the brief from what the
tools returned, so an offline run is checked by the same grounding rule as a live one, and the
twelve workflows stay demonstrable without hand-written prose per workflow. The same builder is
the fallback when synthesis cannot reach any provider.

## D18 — Dilution is judged by which side of the peak a report sits on

Probability of collision rises with uncertainty to a peak and falls away beyond it. The first
implementation flagged dilution whenever scaling the covariance reached a much higher value,
which also fires for a well-tracked conjunction where better data would raise the number. That
is the opposite situation and the opposite warning. The check now finds the scale at which the
probability peaks: below one means the report sits past the peak and the low number comes from
poor tracking, above one means the number is merely sensitive to tracking quality, which is
reported separately.

## D19 — Sample conjunctions are solved numerically, not from the approximation

The bundled CDM series were first generated by inverting the isotropic small-body formula, but
their covariances are anisotropic, so the probabilities landed well away from their targets and
the scenarios did not demonstrate what they were written to demonstrate. Miss distances are now
found by bisection against the same integrator the tools use, which puts each series exactly
where it is meant to be.

## D20 — Market data is simulated and labelled, not downloaded

The alpha audit reads bundled price series by default and only tries a market data provider
when a run explicitly asks for it. Committing real price history raises redistribution
questions, and a run that silently depends on a provider is neither reproducible nor free.
The bundled series are simulated from a fixed seed with a shared market factor so the names
move together, and every tool that reads them returns the note saying so, so a brief can never
present them as a real security's history.

## D21 — Demeaned noise is never used as an overfitting fixture

An obvious way to build a "no edge anywhere" matrix is to subtract each variant's full-sample
mean. That makes the statistic meaningless: with a balanced split, a column that sums to zero
has in-sample and out-of-sample means that are exactly anti-correlated, so the in-sample winner
is forced to be the out-of-sample loser and the probability of backtest overfitting reads 1.0
by arithmetic rather than by overfitting. Measured correlation between the halves is exactly
-1. The bundled matrices keep their realised means, and a test pins the degenerate case so the
shortcut is not reintroduced.

## D22 — The bundled noise matrix is a chosen draw, and says so

A single overfitting probability is a noisy statistic. Across 120 independent pure-noise
matrices of the same shape the deflated Sharpe averages 0.50 with a spread of 0.13, and the
overfitting probability averages 0.49 with a spread of 0.18; the verdict rules call pure noise
overfit in about two thirds of draws and inconclusive in the rest. That is the statistics
behaving correctly rather than a fault: a deflated Sharpe near 0.50 is the honest reading that
the best of forty trials is exactly what forty trials produce. The bundled matrix is a seed
chosen at the clear end of that spread so the sample demonstrates the failure mode without
sitting on a threshold. Nothing in the statistics is tuned, only which draw is shipped, and
this dispersion is why the brief reports the deflated Sharpe, the overfitting probability and
the walk-forward folds together rather than resting on any one.

## D23 — The sample book stays inside its own concentration limits

The first sample book was already over the single-name and sector limits before any ticket was
applied, so every ticket produced a concentration breach and the smallest sample could not
demonstrate the fast-track path. Positions are now sized so the book starts inside every limit,
which means a breach reported by the gate is caused by the ticket under review rather than by
the fixture.
