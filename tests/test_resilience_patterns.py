"""Unit tests for resilience patterns."""

from __future__ import annotations
import pytest
from src.patterns.resilience import retry_with_backoff


def test_retry_succeeds_after_transient_failures():
    attempts = {"count": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3: raise ValueError("transient")
        return "ok"

    assert flaky() == "ok"
    assert attempts["count"] == 3


def test_retry_raises_after_exhausting():
    @retry_with_backoff(max_retries=2, base_delay=0.01)
    def always_fails(): raise ValueError("permanent")

    with pytest.raises(ValueError): always_fails()
