
def load_sector_config(path='config/sectors.yaml'):
    import yaml
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return {s['name']: s for s in cfg.get('sectors', [])}

def get_priority(sector_name, cfg):
    return cfg.get(sector_name, {}).get('priority', 1)
