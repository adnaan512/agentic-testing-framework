"""Core data models for the agentic testing framework."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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


@dataclass
class InteractiveElement:
    """Clickable/fillable element from the DOM."""
    selector: str
    tag: str
    role: Optional[str] = None
    text: Optional[str] = None
    input_type: Optional[str] = None
    is_visible: bool = True


@dataclass
class PageState:
    """A snapshot produced by the Monitor."""
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
        raw = f"{self.url}|{self.dom_hash}|{len(self.interactive_elements)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
