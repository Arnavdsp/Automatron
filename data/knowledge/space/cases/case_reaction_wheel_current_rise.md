---
title: Reaction wheel current rise during momentum build
doc_type: case
workflow_ids: [space.anomaly_rca]
license_note: synthetic case — fictional details written for this project
---

# Reaction wheel current rise during momentum build

Synthetic case. Details are fictional.

**Situation.** Telemetry showed reaction wheel 1 current rising from a nominal 0.42 A to 0.78 A
over nine days, with wheel temperature up 6 C and speed oscillation growing at roughly 0.4 Hz.

**What the analysis showed.** Lagged correlation put wheel temperature behind current by about
40 minutes, consistent with heating following increased torque rather than causing it. Bus
voltage and panel temperature were unremarkable. The oscillation frequency did not match any
commanded rate. Ranked against the subsystem failure table, bearing degradation matched on
current rise, temperature rise and speed oscillation; lubricant migration matched on two of
three; a controller tuning fault matched only the oscillation and was inconsistent with the
thermal signature.

**What the engineer decided.** Bearing degradation was carried as the leading hypothesis. The
team scheduled a low-speed characterisation run and reviewed momentum management to reduce time
near the resonant speed. Root cause was not declared from telemetry alone.

**Lesson.** Correlation lag direction distinguishes a cause from a consequence when two channels
move together.
