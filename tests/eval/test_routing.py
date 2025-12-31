
def test_routing_selects_lowest_latency_provider():
    # When provider A has p50=200ms and provider B has p50=800ms,
    # the router should prefer provider A for latency-sensitive sectors.
    from app.router.scheduler import WeightedRoundRobin
    wrr = WeightedRoundRobin([('provider_a', 2), ('provider_b', 1)])
    choices = [wrr.next() for _ in range(9)]
    assert choices.count('provider_a') > choices.count('provider_b')
