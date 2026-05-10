"""
Core data models shared across the Monitor -> Analyze -> Plan -> Execute -> Knowledge
(MAPE-K) loop. Keeping these as plain, serializable dataclasses means every component
can be tested, logged, and replayed independently of the LLM or the browser.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    NAVIGATE = "navigate"
    SELECT = "select"
    HOVER = "hover"
    SCROLL = "scroll"
    PRESS_KEY = "press_key"
    WAIT = "wait"
    ASSERT = "assert"


@dataclass
class InteractiveElement:
    """A single clickable/fillable element extracted from the live DOM."""
    selector: str
    tag: str
    role: Optional[str] = None
    text: Optional[str] = None
    input_type: Optional[str] = None
    is_visible: bool = True


@dataclass
class PageState:
    """
    A snapshot produced by the Monitor component. `fingerprint` is what the
    KnowledgeBase uses to decide "have I seen this state before?" -- this is what
    keeps the agent from looping forever on the same page (a classic agentic-system
    failure mode: unbounded exploration with no convergence guarantee).
    """
    url: str
    title: str
    dom_hash: str
    interactive_elements: list[InteractiveElement] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def fingerprint(self) -> str:
        """Stable hash used for novelty / visited-state detection."""
        raw = f"{self.url}|{self.dom_hash}|{len(self.interactive_elements)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Action:
    """A single step the agent (or a generated test) can execute."""
    action_type: ActionType
    selector: Optional[str] = None
    value: Optional[str] = None
    description: str = ""


@dataclass
class TestStep:
    action: Action
    expected_outcome: Optional[str] = None


@dataclass
class TestCase:
    """
    A test case synthesized by the Planner from a path the agent explored.
    Designed to be exported as a standalone, replayable script -- the whole point
    of autonomous exploration is to *produce regression tests a human team keeps*,
    not just to wander around and print logs.
    """
    id: str
    title: str
    origin_url: str
    steps: list[TestStep] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


@dataclass
class Anomaly:
    """An observation the Analyzer flagged as a likely defect."""
    severity: Severity
    category: str  # e.g. "console_error", "broken_navigation", "visual_regression", "llm_flagged"
    description: str
    page_url: str
    evidence: dict[str, Any] = field(default_factory=dict)
    screenshot_path: Optional[str] = None


@dataclass
class TestResult:
    test_case_id: str
    passed: bool
    duration_seconds: float
    anomalies: list[Anomaly] = field(default_factory=list)
    error: Optional[str] = None
    retries_used: int = 0


@dataclass
class AgentConfig:
    target_url: str
    max_exploration_steps: int = 40
    max_depth: int = 6
    headless: bool = True
    model_provider: str = "anthropic"  # "anthropic" | "openai" | "mock"
    model_name: str = "claude-sonnet-4-6"
    output_dir: str = "./run_output"
    request_timeout_seconds: float = 30.0
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 20.0
    max_retries: int = 3
