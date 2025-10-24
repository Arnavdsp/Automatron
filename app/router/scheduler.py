
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
