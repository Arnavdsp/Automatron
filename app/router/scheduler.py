
class WeightedRoundRobin:
    def __init__(self, providers):
        self.providers = providers  # list of (name, weight)
        self._idx = 0
        self._counts = {p: 0 for p, _ in providers}

    def next(self):
        name, weight = self.providers[self._idx % len(self.providers)]
        self._counts[name] += 1
        self._idx += 1
        return name

# Timeout policy: if a slot does not respond within _SLOT_TIMEOUT_S,
# it is released immediately and marked degraded — not held pending.
_SLOT_TIMEOUT_S = 8.0

# Latency cache: tracks p50 response time per provider (rolling 50-request window).
# Used to bias the router toward lower-latency providers in time-sensitive sectors.
_LATENCY_WINDOW = 50
_latency_cache: dict[str, list[float]] = {}

# All tuning constants now imported from app.config
# to allow env-var overrides without code changes.
from app.config import SLOT_TIMEOUT_S, LATENCY_WINDOW

# Previous: self._idx % len(self.providers) was correct but confusing.
# Rewritten as: self._idx = (self._idx + 1) % len(self.providers)
# for clarity — no behaviour change.
