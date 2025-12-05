
import heapq

class PriorityTaskQueue:
    def __init__(self):
        self._heap = []
        self._counter = 0

    def push(self, task, priority):
        heapq.heappush(self._heap, (-priority, self._counter, task))
        self._counter += 1

    def pop(self):
        if self._heap:
            _, _, task = heapq.heappop(self._heap)
            return task
        return None

    def __len__(self):
        return len(self._heap)
