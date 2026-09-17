---
title: Model risk management themes
doc_type: policy
source_url: https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
workflow_ids: [quant.alpha_audit, quant.code_compliance]
license_note: authored summary — verify against the official source
---

# Model risk management themes

Summary written for this project. Verify against the official source before relying on it.

Supervisory guidance on model risk treats a model as a source of risk in its own right, arising
from a model that is wrong or from a model used in a way it was not built for.

## Three recurring elements

Development and implementation, covering the design rationale, the data, the assumptions and the
testing performed. A model whose economic rationale is unstated is hard to review whatever its
statistics say.

Validation, performed by people independent of development. It covers conceptual soundness,
ongoing monitoring against live outcomes, and outcomes analysis comparing predictions to
results. Effective challenge is the operative phrase: the reviewer is expected to probe, not
confirm.

Governance, covering policies, an inventory of models in use, defined roles, and documentation
sufficient for someone who did not build the model to understand and reproduce it.

## Consequences for a signal review

A review that reports only statistics is incomplete. It should record what the model assumes,
what data it was fitted on, what would invalidate it, and what monitoring would detect that
happening. Where the economic rationale is missing, that is itself a finding to put to the
researcher, not a gap for the reviewer to fill.

Findings are proposals for the validation function and the model owner. The decision to approve,
reject or restrict a model rests with people holding that authority.
