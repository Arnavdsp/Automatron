
import time

def check_provider(provider_fn, retries=3, base_delay=1.0):
    """
    Poll provider with exponential backoff.
    Returns True if provider responds within retries.
    """
    for attempt in range(retries):
        try:
            provider_fn()
            return True
        except Exception:
            time.sleep(base_delay * (2 ** attempt))
    return False

_DEAD_SLOT_REPROBE_S = 60

# Dead slots are moved to a quarantine list.
# A background task re-probes them every 60 s and promotes them if healthy.
_quarantined: list[str] = []
