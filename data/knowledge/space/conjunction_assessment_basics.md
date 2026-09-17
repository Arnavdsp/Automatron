---
title: Conjunction assessment basics
doc_type: reference
source_url: https://www.space-track.org/documents/CDM_Guide.pdf
workflow_ids: [space.conjunction_triage]
license_note: authored summary — verify against the official source
---

# Conjunction assessment basics

Summary written for this project. Verify against the official source before relying on it
operationally.

## Conjunction Data Messages

A Conjunction Data Message (CDM) is the CCSDS-standard record a screening provider issues when
two catalogued objects are predicted to pass close to one another. A single close approach
usually produces a series of CDMs as tracking improves, each superseding the last. The fields
an analyst reads first are the time of closest approach (TCA), the miss distance and its
components in the radial, in-track and cross-track (RTN) frame, the relative velocity, the
covariance of each object's position, and the orbit determination (OD) epoch showing how old
the underlying tracking data is.

## Probability of collision

Probability of collision (Pc) estimates how likely the two objects are to occupy the same space
at TCA. The common two-dimensional method projects the combined covariance of both objects into
the plane perpendicular to the relative velocity vector, then integrates the resulting Gaussian
over a circle whose radius is the combined hard-body radius of the two objects. The method
assumes a short encounter, a linear relative trajectory through the encounter, and Gaussian
position errors — assumptions that hold for typical high-velocity conjunctions in low Earth
orbit and degrade for slow, long encounters.

Pc is reported in scientific notation because the values span many orders of magnitude.

## Thresholds as operator policy

There is no universal Pc threshold. Values in the range of 1e-4 are frequently cited as a level
at which operators consider a manoeuvre, and values near 1e-6 or 1e-7 as a level below which a
conjunction is routinely monitored rather than acted on. These are operator policy choices that
depend on the vehicle, the remaining propellant, the mission phase and the consequence of a
collision. Any threshold a brief cites should be attributed to a named policy, not presented as
a physical constant.

## Covariance quality and probability dilution

A low Pc is only meaningful if the covariance is trustworthy. Three checks matter.

Data age: if the OD epoch is several days before TCA, the covariance is extrapolated and the
state is less certain than it appears.

Positive-definiteness: a covariance matrix that is not positive definite indicates a
computation or transmission problem and invalidates the Pc.

Probability dilution: Pc is not monotonic in covariance size. When uncertainty is very large,
the probability mass spreads out and Pc falls, so a very uncertain conjunction can report a
reassuringly small number. The standard check scales the covariance across a range of factors
and reports the maximum Pc reachable. If the maximum is far above the reported value, the low
Pc is an artefact of poor tracking rather than evidence of safety.

## Trend across a CDM series

A single CDM is a snapshot. What usually drives a decision is the trend: whether Pc is rising or
falling across successive messages, whether it has crossed a policy threshold, and whether it
has jumped by an order of magnitude or more between messages. A sharp jump often signals new
tracking data rather than a change in the physical situation, and is a reason to wait for the
next message where the timeline allows.
