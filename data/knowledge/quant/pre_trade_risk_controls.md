---
title: Pre-trade risk control themes
doc_type: policy
source_url: https://www.sec.gov/rules/final/2010/34-63241.pdf
workflow_ids: [quant.trade_gate, quant.code_compliance]
license_note: authored summary — verify against the official source
---

# Pre-trade risk control themes

Summary written for this project. Verify against the official source before relying on it.

Rules governing market access and algorithmic trading converge on a similar set of controls.
The themes below recur across jurisdictions; the binding text differs.

## Controls applied before an order reaches the market

Credit and capital thresholds, applied per client and in aggregate, that reject orders which
would breach a limit.

Order size and price limits that block erroneous orders — a quantity or notional far outside
normal, or a price far from the prevailing market.

Duplicate and rate controls that prevent a malfunctioning system from flooding the venue.

Restricted instrument checks that prevent trading in securities the firm or the client may not
trade.

## Controls around the trading system

A kill switch able to halt order flow promptly, with clearly assigned authority to use it.

Pre-deployment testing in an environment separated from production, and a documented change
process.

Records sufficient to reconstruct what the system did and why, retained for the required period.

Monitoring by people with the authority and the means to intervene while the system runs.

## Independence

A recurring requirement is that risk controls sit under the direct and exclusive control of the
firm's risk function rather than the trading desk, so that a limit cannot be relaxed by the
person it constrains.

## Consequences for a gate review

A pre-trade review should state which controls a ticket engaged, which limits it approached or
breached, and what remains unverified. It is preparation for a human approver. No output of the
review places, routes or authorises an order.
