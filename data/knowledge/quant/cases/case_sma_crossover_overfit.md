---
title: SMA crossover that did not survive deflation
doc_type: case
workflow_ids: [quant.alpha_audit]
license_note: synthetic case — fictional details written for this project
---

# SMA crossover that did not survive deflation

Synthetic case. Details are fictional.

**Situation.** A researcher presented a moving-average crossover on five liquid equities with an
annualised Sharpe of 1.9 over eight years, selected from a grid of 240 parameter combinations.

**What the analysis showed.** Applying five basis points of cost per turnover reduced the Sharpe
to 1.4. Deflating for 240 trials, with the observed variance of Sharpe ratios across the grid,
produced a deflated Sharpe of 0.31 — far below the 0.95 threshold. CSCV over twelve blocks
returned a PBO of 0.61, meaning the in-sample best landed in the bottom half out of sample more
often than not. Walk-forward analysis showed three of five folds with negative out-of-sample
Sharpe.

**What the reviewer decided.** The strategy was returned to the researcher with a request for an
economic rationale and a pre-registered parameter choice, rather than being rejected outright.
No capital was allocated.

**Lesson.** A headline Sharpe computed over a parameter grid is a maximum, not an estimate.
Reporting the trial count alongside it is what makes the number interpretable.
