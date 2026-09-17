---
title: Lookahead bias hidden in a feature
doc_type: case
workflow_ids: [quant.code_compliance]
license_note: synthetic case — fictional details written for this project
---

# Lookahead bias hidden in a feature

Synthetic case. Details are fictional.

**Situation.** A strategy file submitted for pre-deployment review reported implausibly smooth
equity growth in its own backtest.

**What the review showed.** Static analysis flagged a negative shift on a rolling z-score
feature, so the signal at each bar incorporated the following bar's price. A second finding
noted the absence of any maximum position constant before the order-sending call. Neither was
visible in the strategy's own performance report.

**What the reviewer decided.** Both findings were raised as blocking for live deployment. The
backtest was treated as uninformative until the feature was corrected and re-run.

**Lesson.** Static review catches a class of error that performance statistics cannot, because a
leaked feature makes the statistics look better rather than worse.
