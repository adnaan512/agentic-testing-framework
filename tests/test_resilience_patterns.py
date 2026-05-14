"""
Unit tests for the resilience patterns. These are fast (sub-second), pure
Python, no Playwright/LLM/network dependency. A reviewer or CI can run them
with `pytest tests/test_resilience_patterns.py -v`.
"""

from __future__ import annotations

import time

import pytest

from src.patterns.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitOpenError,
    CheckpointManager,
    retry_with_backoff,
)


# --------------------------------------------------------------------------- #
# retry_with_backoff
# --------------------------------------------------------------------------- #

def test_retry_with_backoff_succeeds_after_transient_failures():
    attempts = {"count": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("transient")
        return "ok"

    assert flaky() == "ok"
    assert attempts["count"] == 3


def test_retry_with_backoff_raises_after_exhausting_retries():
    @retry_with_backoff(max_retries=2, base_delay=0.01)
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        always_fails()


def test_retry_selective_exception_filter():
    @retry_with_backoff(max_retries=5, base_delay=0.01, retry_on=(TypeError,))
    def fails_with_value_error():
        raise ValueError("not retried")

    with pytest.raises(ValueError):
        fails_with_value_error()  # should not retry since ValueError != TypeError


# --------------------------------------------------------------------------- #
# CircuitBreaker
# --------------------------------------------------------------------------- #

def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.05)

    def bad():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call("k1", bad)

    with pytest.raises(CircuitOpenError):
        cb.call("k1", bad)


def test_circuit_per_key_isolation():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)

    def bad():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        cb.call("k1", bad)

    # k1 is open, but k2 should still be closed
    with pytest.raises(RuntimeError):
        cb.call("k2", bad)  # this *raises* RuntimeError (first failure), but the circuit for k2 was CLOSED, not OPEN


def test_circuit_half_open_recovery():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)

    def bad():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        cb.call("k1", bad)

    # k1 is open now; wait for cooldown
    time.sleep(0.06)

    # After cooldown the circuit is HALF_OPEN -- a success should close it
    result = cb.call("k1", lambda: "recovered")
    assert result == "recovered"
    assert cb.status()["k1"] == "closed"


# --------------------------------------------------------------------------- #
# CheckpointManager
# --------------------------------------------------------------------------- #

def test_checkpoint_save_and_load(tmp_path):
    mgr = CheckpointManager(output_dir=str(tmp_path))
    state = {"step": 5, "visited": ["a", "b"]}
    mgr.save(state)
    loaded = mgr.load()
    assert loaded == state


def test_checkpoint_returns_none_when_missing(tmp_path):
    mgr = CheckpointManager(output_dir=str(tmp_path / "nonexistent"))
    assert mgr.load() is None


# --------------------------------------------------------------------------- #
# Bulkhead
# --------------------------------------------------------------------------- #

def test_bulkhead_allows_within_capacity():
    bh = Bulkhead(max_concurrent=2)
    result = bh.run(lambda: "ok")
    assert result == "ok"
