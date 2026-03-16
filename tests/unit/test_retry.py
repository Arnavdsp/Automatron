
import pytest

def test_retry_raises_after_max():
    from app.tasks.retry import retry_with_backoff
    call_count = [0]
    def always_fail():
        call_count[0] += 1
        raise ValueError('always')
    with pytest.raises(ValueError):
        retry_with_backoff(always_fail, max_retries=3, base_delay=0.01)
    assert call_count[0] == 3
