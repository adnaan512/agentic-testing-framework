"""Thin Playwright wrapper — browser lifecycle and event listeners."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from src.models import Action, ActionType, InteractiveElement, PageState

logger = logging.getLogger("agentic_testing.browser")

_INTERACTIVE_SELECTOR = (
    "a, button, input, select, textarea, [role=button], [role=link], "
    "[role=tab], [role=menuitem], [onclick]"
)


class PlaywrightDriver:
    def __init__(self, headless=True, screenshot_dir=None, timeout_seconds=30.0):
        self._headless = headless
        self._timeout_ms = timeout_seconds * 1000
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        if self._screenshot_dir: self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._browser = None
        self._page = None
        self._console_errors = []
        self._network_errors = []
        self._step_counter = 0

    def start(self, start_url):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        self._page.on("console", self._on_console)
        self._page.on("requestfailed", self._on_request_failed)
        self._page.on("pageerror", self._on_page_error)
        self._page.goto(start_url)

    def stop(self):
        if self._browser: self._browser.close()
        if self._playwright: self._playwright.stop()

    def _on_console(self, msg):
        if msg.type == "error": self._console_errors.append(msg.text)

    def _on_request_failed(self, request):
        self._network_errors.append(f"{request.method} {request.url} -> {request.failure}")

    def _on_page_error(self, exc):
        self._console_errors.append(f"Uncaught exception: {exc}")

    def navigate(self, url):
        assert self._page is not None
        self._page.goto(url)
