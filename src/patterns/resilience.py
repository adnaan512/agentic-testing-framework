"""Resilience patterns — retry with exponential backoff."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger("agentic_testing.patterns.resilience")
T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: exponential backoff with jitter."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    attempt += 1
                    if attempt > max_retries:
                        logger.warning("%s failed after %d retries: %s", func.__name__, max_retries, exc)
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    logger.info("%s failed (attempt %d/%d) -- retrying in %.1fs", func.__name__, attempt, max_retries, delay)
                    time.sleep(delay)
        return wrapper
    return decorator
