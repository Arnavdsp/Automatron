---
title: Eclipse voltage sag from a stuck heater
doc_type: case
workflow_ids: [space.anomaly_rca]
license_note: synthetic case — fictional details written for this project
---

# Eclipse voltage sag from a stuck heater

Synthetic case. Details are fictional.

**Situation.** Battery voltage began dipping roughly 0.9 V lower than usual during eclipse, with
the depth of discharge worsening over five orbits.

**What the analysis showed.** The heater enable channel remained asserted through eclipse exit,
where it normally cycles off. Bus current in eclipse was up by an amount consistent with one
heater circuit remaining energised. Panel temperature during sunlight was unchanged, ruling out
a power generation shortfall. The timeline placed the first stuck-on interval immediately after
a thermal control mode change.

**What the engineer decided.** The team treated a latched heater command as the leading
hypothesis, reviewed the mode transition logic, and planned a controlled re-command during a
pass with ground coverage. Charge margin was protected in the interim by reducing a non-critical
payload duty cycle.

**Lesson.** A power symptom frequently originates outside the power subsystem. Building the
event timeline across subsystems located the cause faster than examining battery telemetry alone.
