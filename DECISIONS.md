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

## D24 — The health endpoint is unauthenticated and deliberately uninformative

A container platform's health check cannot present credentials, so `/health` is the one route
outside the basic-auth dependency. It returns only that the process is up and how many sectors
registered: no provider state, no configuration, nothing about which keys are present. Basic
auth is also skipped entirely when no password is configured, which is convenient locally and
unsafe anywhere reachable, so the process now warns at startup when that is the case and the
deploy workflow passes the password as a required secret, which fails the deploy rather than
publishing an open service.

## D25 — Releases go out through the same checks a pull request gets

The deploy workflow calls the CI workflow and deploys only if it passes, so a red build cannot
reach the running service. Authentication uses workload identity federation rather than a
service account key, so nothing long-lived is stored in the repository's secrets, and the job
mints a short-lived token per run. After the revision is live the workflow polls the health
endpoint, allowing for this image's cold start, and fails the deploy if the new revision never
answers.

## D26 — Claim photos are generated shapes, and the match threshold was measured

The bundled claim images are coloured rectangles drawn from a fixed seed, not
photographs of anything, so nothing here depends on redistributing a real image. The
distance at which two files count as the same picture was measured rather than
assumed: across the bundled set, the same image re-saved, recompressed or rescaled
lands between 0 and 6, while different images land at 20 or more. Ten sits in the
empty gap. Real photographs would narrow that gap, so the tool reports the measured
distance alongside the verdict and the threshold is configuration rather than a
constant in code.

## D27 — Personal data is masked at the tool boundary

The core redaction pass already masks logs and rendered output. The e-commerce tools
mask before returning instead, so a full email address, phone number, card number or
street address never enters a step result, an evidence entry or a brief at all.
Masking after the fact would be one missed code path away from a leak, and the brief
is the artefact most likely to be copied elsewhere. A test sweeps every dispute tool's
output against every contact detail in the sample files.

## D28 — Every risk factor carries the innocent reading of the same observation

The scoring rules file records, for each factor, an ordinary explanation for the
behaviour it fires on: a new account can simply be new, a high return rate is normal
in apparel, urgency is what a person sounds like when a delivery has genuinely failed.
The tool returns that explanation next to the weight whenever the factor contributes,
so the brief cannot present a signal without its counter-reading. The score routes a
claim to a reviewer and never decides it, which is why the fast-track level still
stops at the approval gate.

## D29 — An assumed chargeback deadline is labelled as assumed

Response windows differ by network, processor and merchant agreement. When a notice
does not state one, the tool falls back to a configured default and says so in the
result, because missing the real deadline forfeits the dispute however strong the
packet is. The same reasoning applies to the evidence lists: they are generic
categories, and every result repeats that the processor is the authority.

## D30 — The brief's number table judges a key by its words

The extractor matched key names as substrings, so `account_opened` and `discount_code`
both counted as measurements because each contains "count", and the values beside them
were dates, which passed a loose numeric pattern because of their hyphens. A date then
appeared in a brief's quantitative table as though it were a measured quantity. Keys
are now split into words and matched against a vocabulary, and date-shaped strings are
excluded before the numeric test rather than after.

## D31 — The level on a brief is the one a tool decided, not one merely mentioned

Choosing the recommendation level by scanning a run's results for the first term in
the workflow's vocabulary worked only while a single tool ever produced one. The
permit pre-screen has two: the use table reports the level its answer would suggest
on its own, and the outcome tool reports the level the whole screen reached. Because
the use table's suggestion happened to be first in the vocabulary, a project with a
failing setback was presented as ready for the examiner. The level is now taken from
a result that names itself "level", so the tool making the call decides, and a bare
mention is only a fallback. A brief showing a level nothing decided is worse than no
level at all, since the reader has no way to tell.

## D32 — Findings are one per category per page, and headings are not findings

Reading a document sentence by sentence produced several near-identical findings from
one paragraph, and thirty rows buried the four that mattered. Findings are now
collapsed to one per category per page, keeping the longest excerpt and counting the
rest. Headings are dropped line by line before sentences are assembled: a title page
carries the document's subject words, so an environmental report's letterhead was
producing a finding about itself. Dropping headings after assembly does not work,
because a title line glued to the mixed-case lines beneath it no longer looks like one.

## D33 — A clause's category is scored, with the document breaking ties

Taking the first category whose keyword appeared put a declaration's restriction under
"easement" because the clause mentioned one, and put a title commitment's general
survey exception under "encroachment" for the same reason. Categories are now scored by
how many of their markers match, and a tie is broken by what the document mostly
contains: a restriction in a declaration is a restriction. The document type also has
to match the names in the expected-documents list, or a document that was supplied is
announced as missing.

## D34 — Zoning comparisons treat equal as compliant

Dimensional standards are written as "not less than" and "not more than", so a value
exactly on its limit complies. One bundled project sits exactly on four limits at once
while failing a fifth by two feet, so an off-by-one comparison fails the tests rather
than quietly failing a compliant project. Sections are invented and belong to a
fictional city, and every row reports the required value, the proposed value and the
section it came from so an examiner can redo the arithmetic.

## D35 — Notice periods are placeholders and are labelled on every date

Notice periods differ by agreement and jurisdiction and are among the most
jurisdiction-specific numbers in the sector. The rules file carries invented periods so
the workflow can compute a date and show its arithmetic, and every computed date is
returned carrying the words "placeholder — confirm local law". Eviction, apparent
threats and apparent discriminatory language escalate to counsel regardless of anything
else in the record, because those are not calls this should be making.

## D36 — A run's ceiling allows for a queueing provider, not a healthy one

The first live evaluation failed two workflows, both by exceeding the 300 second run
ceiling. The logs showed why: free provider tiers queue rather than refuse, and single
calls were observed taking 258 and 229 seconds while the run produced no output at
all. Forcing every one of the eleven slots to fail offline showed the degradation path
itself is sound — the run still finished in 43 seconds with a brief marked low
confidence — so the ceiling, not the failover, was what ended those runs. It is now a
setting, `RUN_TIMEOUT_S`, defaulting to 600 seconds, and a timeout records which steps
had completed: a run that stalled on its first call and one that was nearly finished
need different answers, and "exceeded the time limit" does not tell them apart.

## D37 — An unclassified provider failure keeps the provider's own words

Provider failures were logged with the provider, the model and the classification, but
not the error text. Since `other` is the catch-all, the one case with nothing to
diagnose it from was the case that most needed it: a live run produced four `other`
classifications that could not be told apart afterwards. The detail is now logged,
passed through the same redaction as everything else, because provider errors
sometimes quote the key back.
