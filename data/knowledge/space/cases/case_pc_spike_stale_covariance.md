---
title: Pc spike traced to stale covariance
doc_type: case
workflow_ids: [space.conjunction_triage]
license_note: synthetic case — fictional details written for this project
---

# Pc spike traced to stale covariance

Synthetic case. Details are fictional.

**Situation.** An operator received a four-message CDM series for a 620 km sun-synchronous
spacecraft against a defunct upper stage. Pc rose from 4.1e-7 to 2.8e-4 between the third and
fourth messages, crossing the operator's 1e-4 review threshold eleven hours before TCA.

**What the analysis showed.** The secondary object's OD epoch was five days before TCA and its
position covariance was roughly nine times larger than in the earlier messages. A covariance
scaling check found the maximum reachable Pc was only 3.1e-4, close to the reported value, so
dilution did not explain the number. The jump coincided with a gap in radar coverage.

**What the operator decided.** The analyst requested additional tracking rather than committing
propellant, and prepared a manoeuvre plan to execute if the next message confirmed the rise. The
following message, built on fresh tracking, reported 6.2e-6. No manoeuvre was performed.

**Lesson.** An order-of-magnitude jump between messages more often reflects new tracking data
than a changed physical situation. Where the timeline permits waiting for the next message, that
is usually more informative than acting on the spike.
