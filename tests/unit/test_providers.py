
def test_sanitise_removes_bearer():
    from app.providers.groq_client import _sanitise_error
    raw = 'Error: Bearer gsk_abc123xyz456longkey'
    clean = _sanitise_error(raw)
    assert 'gsk_abc123xyz456longkey' not in clean
    assert 'REDACTED' in clean
