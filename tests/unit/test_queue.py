
def test_priority_order():
    from app.tasks.queue import PriorityTaskQueue
    q = PriorityTaskQueue()
    q.push('low',  priority=1)
    q.push('high', priority=5)
    q.push('mid',  priority=3)
    assert q.pop() == 'high'
    assert q.pop() == 'mid'
    assert q.pop() == 'low'
