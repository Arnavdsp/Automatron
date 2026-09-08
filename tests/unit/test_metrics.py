
def test_latency_p50():
    from app.metrics import record_latency, summary
    for ms in [100, 200, 300, 400, 500]:
        record_latency('test_provider', ms/1000)
    s = summary('test_provider')
    assert 290 < s['p50'] < 310  # p50 of [100,200,300,400,500] ms = 300 ms
