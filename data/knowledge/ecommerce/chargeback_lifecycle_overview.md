---
title: Chargeback dispute lifecycle and evidence types
doc_type: reference
source_url: https://www.federalreserve.gov/supervisionreg/regzcg.htm
workflow_ids: [ecommerce.chargeback_packet]
license_note: authored summary — verify against your processor's current rules
---

# Chargeback dispute lifecycle and evidence types

Summary written for this project. Card network rules differ and change; verify against your
processor's current documentation.

## Sequence

A cardholder disputes a transaction with the issuing bank. The issuer raises a chargeback under
a reason code and provisionally credits the cardholder. The acquirer notifies the merchant, who
may accept the loss or contest it by submitting representment evidence within a deadline. The
issuer reviews. Depending on the network and the reason, a second presentment, pre-arbitration
and arbitration stages may follow, each with its own deadline and fees.

Deadlines are short and are set by the processor and network, not by the merchant. Missing one
ends the dispute regardless of the evidence.

## Generic evidence by reason category

Fraud, unauthorised: address and card verification results, any 3-D Secure authentication
result, device and IP match against the account's earlier orders, delivery confirmation to the
billing address, and prior undisputed orders from the same account.

Item not received: carrier tracking with scan events, proof of delivery including signature
where captured, the shipping address as provided by the cardholder, and any communication about
delivery timing.

Not as described: the listing as it appeared at purchase, photographs, the returns policy shown
at checkout, and correspondence about the complaint.

Duplicate processing: records of both transactions showing distinct authorisations, or evidence
that one was already refunded.

Cancelled recurring: the cancellation policy accepted at signup, the cancellation record, and
the notice given before each renewal.

Credit not processed: the refund record with its date and reference.

## What a packet brief should say

A packet brief lists exhibits, names what is missing, states the deadline with its source, and
gives a likelihood band as a labelled heuristic. It never states that a packet has been
submitted or that a dispute has been won.
