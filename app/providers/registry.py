
def load_providers(path='config/providers.yaml'):
    import yaml
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return {p['name']: p for p in cfg.get('providers', [])}
