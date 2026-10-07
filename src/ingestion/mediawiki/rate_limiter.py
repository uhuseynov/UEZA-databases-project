import time
from threading import Lock


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")

        self._interval = 1.0 / requests_per_second
        self._last_request: float | None = None
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()

            if self._last_request is not None:
                remaining = self._interval - (now - self._last_request)

                if remaining > 0:
                    time.sleep(remaining)

            self._last_request = time.monotonic()
