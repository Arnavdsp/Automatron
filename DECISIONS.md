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
