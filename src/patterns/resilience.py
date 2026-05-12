"""Resilience patterns — retry with exponential backoff."""

from __future__ import annotations

import functools
import logging
import time
import threading
from enum import Enum
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


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """Per-key circuit breaker."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 20.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._state: dict[str, CircuitState] = {}
        self._opened_at: dict[str, float] = {}

    def _get_state(self, key: str) -> CircuitState:
        state = self._state.get(key, CircuitState.CLOSED)
        if state == CircuitState.OPEN:
            if time.time() - self._opened_at.get(key, 0.0) >= self.cooldown_seconds:
                self._state[key] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        return state

    def call(self, key: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        with self._lock:
            state = self._get_state(key)
            if state == CircuitState.OPEN:
                raise CircuitOpenError(f"Circuit open for '{key}'")
        try:
            result = func(*args, **kwargs)
        except Exception:
            with self._lock:
                self._failures[key] = self._failures.get(key, 0) + 1
                if self._failures[key] >= self.failure_threshold:
                    self._state[key] = CircuitState.OPEN
                    self._opened_at[key] = time.time()
            raise
        else:
            with self._lock:
                self._failures[key] = 0
                self._state[key] = CircuitState.CLOSED
            return result

    def status(self) -> dict[str, str]:
        return {k: self._get_state(k).value for k in self._state}
