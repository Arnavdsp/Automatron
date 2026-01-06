
import time

def measure_throughput(task_fn, n_tasks=100):
    """Returns tasks per minute for n_tasks sequential runs."""
    start = time.monotonic()
    for _ in range(n_tasks):
        task_fn()
    elapsed = time.monotonic() - start
    return (n_tasks / elapsed) * 60
