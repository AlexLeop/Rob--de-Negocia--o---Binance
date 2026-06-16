import collections
import time

class ApiHealthTracker:
    def __init__(self, window=20, threshold=0.40):
        self._calls = collections.deque(maxlen=window)
        self._thresh = threshold

    def record(self, success: bool):
        self._calls.append((time.monotonic(), success))

    def is_healthy(self) -> bool:
        if len(self._calls) < 5:
            return True
        recent = [s for _, s in self._calls]
        fail_rate = recent.count(False) / len(recent)
        return fail_rate < self._thresh

    def fail_rate(self) -> float:
        if not self._calls: return 0.0
        return [s for _, s in self._calls].count(False) / len(self._calls)
