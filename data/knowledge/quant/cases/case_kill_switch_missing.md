---
title: No kill switch before live deployment
doc_type: case
workflow_ids: [quant.code_compliance]
license_note: synthetic case — fictional details written for this project
---

# No kill switch before live deployment

Synthetic case. Details are fictional.

**Situation.** A strategy scheduled to move from paper to live trading was reviewed.

**What the review showed.** The file contained no circuit breaker or halt path, order calls sat
inside an unbounded loop without rate limiting, and a bare exception handler wrapped the order
submission so a rejected order would be swallowed silently. Logging around order calls was
absent, leaving no reconstruction trail.

**What the reviewer decided.** The findings were mapped to control themes covering system halt
capability, rate control and record keeping, and all were marked blocking for live deployment
while none blocked continued paper trading.

**Lesson.** Separating findings that block live deployment from those that do not gives the
owner a usable path forward rather than a flat refusal.
