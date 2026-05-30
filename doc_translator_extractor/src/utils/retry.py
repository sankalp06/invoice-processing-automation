"""
src/utils/retry.py
───────────────────
Decorator-based retry with exponential back-off + jitter.
Usage:
    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError,))
    def flaky_call(): ...
"""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Exponential back-off retry decorator.

    Parameters
    ----------
    max_attempts : int
        Total number of attempts (including the first).
    base_delay : float
        Initial sleep between retries (seconds).
    max_delay : float
        Upper bound on sleep duration.
    backoff : float
        Multiplier applied to the delay after each failure.
    exceptions : tuple
        Only retry on these exception types.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_attempts,
                            func.__qualname__,
                            exc,
                        )
                        raise
                    jitter = random.uniform(0, delay * 0.2)
                    sleep_for = min(delay + jitter, max_delay)
                    logger.warning(
                        "Attempt %d/%d failed for %s (%s). Retrying in %.1fs…",
                        attempt,
                        max_attempts,
                        func.__qualname__,
                        exc,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    delay = min(delay * backoff, max_delay)

        return wrapper  # type: ignore[return-value]

    return decorator
