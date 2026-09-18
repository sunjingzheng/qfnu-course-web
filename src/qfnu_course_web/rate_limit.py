import asyncio
import time
from collections.abc import Awaitable, Callable


class GlobalRateLimiter:
    def __init__(
        self,
        requests_per_second: float = 5.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not 0.1 <= requests_per_second <= 5:
            raise ValueError("requests_per_second must be between 0.1 and 5")
        self.interval = 1 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_started: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._last_started is not None:
                delay = self.interval - (now - self._last_started)
                if delay > 0:
                    await self._sleep(delay)
            self._last_started = self._clock()
