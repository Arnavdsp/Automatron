---
title: "Backtest overfitting: DSR, PBO and multiple testing"
doc_type: reference
source_url: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
workflow_ids: [quant.alpha_audit]
license_note: authored summary — verify against the official source
---

# Backtest overfitting: DSR, PBO and multiple testing

Summary written for this project. Verify against the cited literature before relying on it.

## The problem

A researcher who tries many strategy variants and reports the best one is reporting the maximum
of a sample, not an estimate of future performance. With enough trials, an impressive Sharpe
ratio arises from noise alone. The number of trials is therefore part of the result, and a
backtest reported without it cannot be assessed.

## Probabilistic and deflated Sharpe ratio

The probabilistic Sharpe ratio asks how likely it is that the true Sharpe exceeds a benchmark,
given the observed Sharpe, the sample length, and the skew and kurtosis of returns. Non-normal
returns matter: negative skew and fat tails both reduce confidence in an observed Sharpe.

The deflated Sharpe ratio extends this by replacing the zero benchmark with an expected maximum
Sharpe under the null, computed from the number of trials attempted and the variance of Sharpe
ratios across those trials. A strategy clears the bar only if it beats what the best of that
many random trials would have produced. With a single trial the deflated ratio reduces to the
probabilistic one.

## Probability of backtest overfitting

The probability of backtest overfitting is estimated by combinatorially symmetric
cross-validation. The return series is cut into an even number of blocks; every way of splitting
those blocks into an in-sample and an out-of-sample half is enumerated; for each split the
variant that performed best in sample is identified and its out-of-sample rank recorded. The
probability that the in-sample best lands in the bottom half out of sample is the PBO. A value
above one half means the selection procedure is worse than picking at random.

## Reading the numbers together

DSR and PBO answer different questions. DSR asks whether this result survives the multiplicity
of trials. PBO asks whether the selection procedure generalises at all. A strategy can post a
respectable DSR and still show a high PBO if the search process is unstable. Both should be read
alongside walk-forward results, transaction costs, and above all an economic rationale for why
the edge should exist.

## Practical cautions

Trials must be counted honestly, including variants discarded early and parameter sweeps run
before the recorded experiment. Under-reporting trials inflates DSR. Costs must be applied
before the metrics, not after, and signals must be lagged so that a decision uses only
information available when it was made.
