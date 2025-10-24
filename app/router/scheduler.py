
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
