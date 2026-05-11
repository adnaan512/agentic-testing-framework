"""
MAPE-K: the canonical reference architecture for self-adaptive systems (autonomic
computing). It separates a system into four loosely-coupled control functions plus
a shared knowledge base:

    Monitor   -- observe the managed system (here: the live web page)
    Analyze   -- interpret observations (is this state novel? is something broken?)
    Plan      -- decide what to do next (explore further? synthesize a test? stop?)
    Execute   -- carry out the decision against the managed system
    Knowledge -- shared state all four stages read/write (visited states, bugs found,
                 test history) -- this is what makes the loop *adaptive* over time
                 instead of memoryless

Mapping this framework onto an autonomous web-testing agent is the central design
choice of this project: instead of one LLM call that "does everything", each stage
is a distinct, independently testable, independently swappable component. This
also happens to be the reference model most resilience-pattern literature for
self-adaptive agentic systems builds on (circuit breakers and retries live in
Execute; checkpointing lives in Knowledge; the Analyze stage is where you decide
*whether* a failure is worth adapting to at all).

These are abstract base classes -- see src/agent/*.py for the concrete
implementations used by this project, and swap in your own to experiment with
different exploration or oracle strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.models import Action, Anomaly, PageState, TestCase


class KnowledgeBase(ABC):
    """Shared memory across the loop. See src/knowledge/state_memory.py."""

    @abstractmethod
    def has_visited(self, state: PageState) -> bool: ...

    @abstractmethod
    def record_visit(self, state: PageState) -> None: ...

    @abstractmethod
    def record_anomaly(self, anomaly: Anomaly) -> None: ...

    @abstractmethod
    def record_test_case(self, test_case: TestCase) -> None: ...

    @abstractmethod
    def visited_count(self) -> int: ...


class Monitor(ABC):
    """Observes the managed system and produces a PageState snapshot."""

    @abstractmethod
    def observe(self) -> PageState: ...


class Analyzer(ABC):
    """
    Interprets a PageState: decides novelty (for the Planner) and flags anomalies
    (the testing 'oracle' problem -- deciding whether observed behavior is a bug).
    """

    @abstractmethod
    def detect_anomalies(self, state: PageState) -> list[Anomaly]: ...

    @abstractmethod
    def is_novel(self, state: PageState, knowledge: KnowledgeBase) -> bool: ...


class Planner(ABC):
    """Decides the next action given the current state and accumulated knowledge."""

    @abstractmethod
    def next_action(
        self, state: PageState, knowledge: KnowledgeBase, depth: int
    ) -> Optional[Action]: ...

    @abstractmethod
    def synthesize_test_case(
        self, states: list[PageState], actions: list[Action]
    ) -> TestCase: ...


class Executor(ABC):
    """Carries out an Action against the managed system."""

    @abstractmethod
    def execute(self, action: Action) -> None: ...
