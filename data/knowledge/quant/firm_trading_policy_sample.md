---
title: Sample firm trading policy
doc_type: policy
workflow_ids: [quant.trade_gate]
license_note: synthetic policy written for this project — not a real firm's policy
---

# Sample firm trading policy

Synthetic policy. Fictional, written to give the workflow something concrete to cite.

## Scope

Applies to all orders originated by systematic strategies at the fictional firm Northbank
Systematic.

## Approval thresholds

Any single order with a notional at or above 100,000 USD equivalent requires approval by a
authorised reviewer before release. Orders below that threshold may follow the fast-track path
but are still recorded and shown to a reviewer for sign-off.

Orders for clients in the high risk, politically exposed, or newly onboarded and unverified
segments require approval regardless of notional.

## Limits

Per-instrument limits and per-strategy limits are maintained by the risk function. A breach of
either blocks fast-track handling and escalates to a reviewer. Concentration is measured against
the current book; a position taking a single instrument above 20 per cent of strategy gross
exposure is escalated.

## Restricted and watch lists

The restricted list blocks trading outright. The watch list permits trading but requires the
reason to be recorded and escalates to compliance for review after the fact.

## Risk measurement

One-day 99 per cent historical value at risk is computed for each proposed position from cached
daily prices. Where price history is insufficient, the figure is reported as unavailable rather
than estimated.

## Records

Every gate review records the ticket, the rules triggered, the reviewer, the decision and the
time. Execution happens outside this system; approval records intent, not a filled order.
