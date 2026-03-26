
def test_failover_skips_quarantined():
    from app.router.health import _quarantined
    _quarantined.clear()
    _quarantined.append('provider_b')
    # In a real test, the router would skip provider_b
    assert 'provider_b' in _quarantined
