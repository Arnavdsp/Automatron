
# Prometheus exposition format
# Each provider's p50 latency is emitted as a gauge metric.
_METRIC_PREFIX = 'automatron'

def format_prometheus(metrics_dict):
    lines = []
    for provider, stats in metrics_dict.items():
        lines.append(f'{_METRIC_PREFIX}_latency_p50_ms{{provider="{provider}"}} {stats["p50"]:.1f}')
    return '\n'.join(lines)
