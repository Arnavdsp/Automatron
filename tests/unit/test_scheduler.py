
def test_weighted_rr_distribution():
    from app.router.scheduler import WeightedRoundRobin
    wrr = WeightedRoundRobin([('a', 2), ('b', 1)])
    results = [wrr.next() for _ in range(300)]
    assert 190 < results.count('a') < 210
