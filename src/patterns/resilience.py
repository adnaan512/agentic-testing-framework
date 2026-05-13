"""
Resilience patterns for agentic systems.

These are deliberately implemented as small, dependency-free, reusable primitives
rather than baked into the agent logic. The motivation: in self-adaptive systems,
the feedback/control mechanisms (how the system detects and recovers from failure)
should be swappable and testable independently of *what* the system is adapting
(here, exploring and testing a web app). Each pattern below addresses a distinct
failure mode that shows up constantly when an LLM is put in a control loop with a
flaky external system (a browser, a network, a non-deterministic model):

- RetryWithBackoff   -> transient failures (flaky selector, slow network, model timeout)
- CircuitBreaker      -> persistent failures (a page/action that is *always* broken --
                         stop hammering it, fail fast, and let the agent move on)
- Checkpoint          -> crash recovery (resume exploration from last good state
                         instead of restarting from scratch)
- Bulkhead            -> fault isolation (one bad test session can't take down the
                         whole exploration run)
"""

from __future__ import annotations

import functools
import json
import logging
import threading
import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger("agentic_testing.patterns.resilience")

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Retry with exponential backoff
# --------------------------------------------------------------------------- #

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator implementing exponential backoff with jitter.

    Use this around any call that talks to something outside the process'
    control: a browser action, an LLM completion, a network request. It will
    NOT swallow the final failure -- after exhausting retries, the original
    exception propagates so the CircuitBreaker / Supervisor above it can react.
    """

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
                        logger.warning(
                            "%s failed after %d retries: %s", func.__name__, max_retries, exc
                        )
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    logger.info(
                        "%s failed (attempt %d/%d): %s -- retrying in %.1fs",
                        func.__name__, attempt, max_retries, exc, delay,
                    )
                    time.sleep(delay)

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Circuit Breaker
# --------------------------------------------------------------------------- #

class CircuitState(str, Enum):
    CLOSED = "closed"      # normal operation
    OPEN = "open"           # failing -- reject calls immediately
    HALF_OPEN = "half_open"  # cooldown elapsed -- allow one trial call


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """
    Per-key circuit breaker (e.g. keyed by selector, URL, or action signature).

    Why per-key rather than global: a single broken modal on a page shouldn't
    stop the agent from testing the rest of the application. Each distinct
    action gets its own failure budget.
    """

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
            opened_at = self._opened_at.get(key, 0.0)
            if time.time() - opened_at >= self.cooldown_seconds:
                self._state[key] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        return state

    def call(self, key: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        with self._lock:
            state = self._get_state(key)
            if state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"Circuit open for '{key}' -- skipping until cooldown elapses."
                )

        try:
            result = func(*args, **kwargs)
        except Exception:
            with self._lock:
                self._failures[key] = self._failures.get(key, 0) + 1
                if self._failures[key] >= self.failure_threshold:
                    self._state[key] = CircuitState.OPEN
                    self._opened_at[key] = time.time()
                    logger.warning(
                        "Circuit OPENED for '%s' after %d consecutive failures.",
                        key, self._failures[key],
                    )
            raise
        else:
            with self._lock:
                self._failures[key] = 0
                self._state[key] = CircuitState.CLOSED
            return result

    def status(self) -> dict[str, str]:
        return {key: self._get_state(key).value for key in self._state}


# --------------------------------------------------------------------------- #
# Checkpointing
# --------------------------------------------------------------------------- #

def _to_serializable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_serializable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj


class CheckpointManager:
    """
    Periodically persists agent state to disk so a crashed run (browser crash,
    LLM API outage, OOM) can resume from the last good checkpoint instead of
    re-exploring the entire application from scratch.
    """

    def __init__(self, output_dir: str):
        self.path = Path(output_dir) / "checkpoint.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: dict[str, Any]) -> None:
        serializable = _to_serializable(state)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(serializable, indent=2, default=str))
        tmp_path.replace(self.path)  # atomic on POSIX -- avoids a corrupted checkpoint
        logger.debug("Checkpoint saved to %s", self.path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Checkpoint at %s unreadable, ignoring: %s", self.path, exc)
            return None


# --------------------------------------------------------------------------- #
# Bulkhead
# --------------------------------------------------------------------------- #

class Bulkhead:
    """
    Limits how many exploration/test sessions run concurrently and isolates
    failures between them, so one stuck or crashing session doesn't exhaust
    resources needed by the rest of the run.
    """

    def __init__(self, max_concurrent: int = 3):
        self._semaphore = threading.Semaphore(max_concurrent)

    def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        acquired = self._semaphore.acquire(timeout=60)
        if not acquired:
            raise TimeoutError("Bulkhead capacity exhausted -- too many concurrent sessions.")
        try:
            return func(*args, **kwargs)
        finally:
            self._semaphore.release()
