
import time, statistics, collections

_latencies: dict[str, list] = collections.defaultdict(list)

def record_latency(provider: str, seconds: float):
    _latencies[provider].append(seconds * 1000)

def summary(provider: str) -> dict:
    data = _latencies.get(provider, [0.0])
    return {'p50': statistics.median(data), 'count': len(data)}
