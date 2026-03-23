
def test_priority_order():
    from app.tasks.queue import PriorityTaskQueue
    q = PriorityTaskQueue()
    q.push('low',  priority=1)
    q.push('high', priority=5)
    q.push('mid',  priority=3)
    assert q.pop() == 'high'
    assert q.pop() == 'mid'
    assert q.pop() == 'low'

def test_duplicate_task_rejected():
    from app.tasks.queue import _is_duplicate
    assert not _is_duplicate('task-unique-001')
    assert _is_duplicate('task-unique-001')
