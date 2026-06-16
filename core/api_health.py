import collections
import time

class ApiHealthTracker:
    def __init__(self, window=20, threshold=0.40):
        self._calls = collections.deque(maxlen=window)
        self._thresh = threshold

    def record(self, success: bool):
        self._calls.append((time.monotonic(), success))

    def _clean_old_records(self):
        now = time.monotonic()
        # Expira registros com mais de 120 segundos para não causar deadlock
        while self._calls and (now - self._calls[0][0] > 120):
            self._calls.popleft()

    def is_healthy(self) -> bool:
        self._clean_old_records()
        if len(self._calls) < 5:
            return True
        recent = [s for _, s in self._calls]
        fail_rate = recent.count(False) / len(recent)
        return fail_rate < self._thresh

    def fail_rate(self) -> float:
        self._clean_old_records()
        if not self._calls: return 0.0
        return [s for _, s in self._calls].count(False) / len(self._calls)
