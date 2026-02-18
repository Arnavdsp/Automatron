
import os

SLOT_TIMEOUT_S = float(os.getenv('AUTOMATRON_SLOT_TIMEOUT', '8.0'))
DEAD_REPROBE_S = float(os.getenv('AUTOMATRON_REPROBE_INTERVAL', '60'))
MAX_RETRIES    = int(os.getenv('AUTOMATRON_MAX_RETRIES', '3'))
LATENCY_WINDOW = int(os.getenv('AUTOMATRON_LATENCY_WINDOW', '50'))

_REQUIRED_PROVIDER_KEYS = ('name', 'type', 'model')

def validate_provider_config(cfg):
    for p in cfg.get('providers', []):
        missing = [k for k in _REQUIRED_PROVIDER_KEYS if k not in p]
        if missing:
            raise ValueError(f"Provider config missing keys: {missing}")
