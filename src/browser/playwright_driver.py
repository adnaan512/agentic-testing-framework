"""
Thin wrapper around Playwright. This is the only module that talks to a real
browser -- every other component depends on PageState/Action (see src/models.py),
not on Playwright directly. That separation is what lets you swap Playwright for
Selenium, or swap a live browser for a recorded fixture in tests, without
touching the agent logic at all.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from src.models import Action, ActionType, InteractiveElement, PageState
from src.patterns.mape_k import Executor, Monitor
from src.patterns.resilience import retry_with_backoff

logger = logging.getLogger("agentic_testing.browser")

# Elements worth surfacing to the planner. Kept intentionally small -- dumping the
# entire DOM into the LLM context on every step is the single fastest way to burn
# tokens and degrade decision quality.
_INTERACTIVE_SELECTOR = (
    "a, button, input, select, textarea, [role=button], [role=link], [role=tab], "
    "[role=menuitem], [onclick]"
)


class PlaywrightDriver(Monitor, Executor):
    def __init__(self, headless: bool = True, screenshot_dir: Optional[str] = None,
                 timeout_seconds: float = 30.0):
        self._headless = headless
        self._timeout_ms = timeout_seconds * 1000
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        if self._screenshot_dir:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._console_errors: list[str] = []
        self._network_errors: list[str] = []
        self._step_counter = 0

    # -- lifecycle ---------------------------------------------------------- #

    def start(self, start_url: str) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        self._page.on("console", self._on_console)
        self._page.on("requestfailed", self._on_request_failed)
        self._page.on("pageerror", self._on_page_error)
        self.navigate(start_url)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self) -> "PlaywrightDriver":
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # -- event listeners ------------------------------------------------------ #

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            self._console_errors.append(msg.text)

    def _on_request_failed(self, request) -> None:
        failure = request.failure
        self._network_errors.append(f"{request.method} {request.url} -> {failure}")

    def _on_page_error(self, exc) -> None:
        self._console_errors.append(f"Uncaught exception: {exc}")

    # -- Monitor implementation ---------------------------------------------- #

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def observe(self) -> PageState:
        assert self._page is not None, "Driver not started. Call start() first."
        page = self._page

        dom_content = page.content()
        dom_hash = hashlib.sha256(dom_content.encode("utf-8", errors="ignore")).hexdigest()[:16]

        elements = self._extract_interactive_elements()
        screenshot_path = self._take_screenshot()

        state = PageState(
            url=page.url,
            title=page.title(),
            dom_hash=dom_hash,
            interactive_elements=elements,
            console_errors=list(self._console_errors),
            network_errors=list(self._network_errors),
            screenshot_path=screenshot_path,
        )
        # Errors are observed once per state snapshot, then cleared so the next
        # snapshot reflects only *new* activity rather than re-reporting the same error.
        self._console_errors.clear()
        self._network_errors.clear()
        return state

    def _extract_interactive_elements(self, limit: int = 25) -> list[InteractiveElement]:
        assert self._page is not None
        handles = self._page.query_selector_all(_INTERACTIVE_SELECTOR)
        elements: list[InteractiveElement] = []
        for i, handle in enumerate(handles[:limit]):
            try:
                if not handle.is_visible():
                    continue
                tag = handle.evaluate("el => el.tagName.toLowerCase()")
                text = (handle.inner_text() or "").strip()[:80]
                role = handle.get_attribute("role")
                input_type = handle.get_attribute("type")
                selector = f"{_INTERACTIVE_SELECTOR.split(',')[0].strip()}:nth-match-{i}"
                # Prefer a stable attribute-based selector when available.
                test_id = handle.get_attribute("data-testid")
                el_id = handle.get_attribute("id")
                if test_id:
                    selector = f'[data-testid="{test_id}"]'
                elif el_id:
                    selector = f"#{el_id}"
                elements.append(
                    InteractiveElement(
                        selector=selector,
                        tag=tag,
                        role=role,
                        text=text or None,
                        input_type=input_type,
                        is_visible=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001 -- a single bad handle shouldn't kill observation
                logger.debug("Skipping element %d during extraction: %s", i, exc)
        return elements

    def _take_screenshot(self) -> Optional[str]:
        if not self._screenshot_dir or not self._page:
            return None
        self._step_counter += 1
        path = self._screenshot_dir / f"state_{self._step_counter:04d}.png"
        try:
            self._page.screenshot(path=str(path))
            return str(path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Screenshot failed: %s", exc)
            return None

    # -- Executor implementation ---------------------------------------------- #

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def execute(self, action: Action) -> None:
        assert self._page is not None, "Driver not started. Call start() first."
        page = self._page
        logger.info("Executing action: %s %s", action.action_type.value, action.description)

        if action.action_type == ActionType.NAVIGATE:
            page.goto(action.value or "")
        elif action.action_type == ActionType.CLICK:
            page.locator(action.selector).first.click()
        elif action.action_type == ActionType.FILL:
            page.locator(action.selector).first.fill(action.value or "")
        elif action.action_type == ActionType.SELECT:
            page.locator(action.selector).first.select_option(action.value or "")
        elif action.action_type == ActionType.HOVER:
            page.locator(action.selector).first.hover()
        elif action.action_type == ActionType.SCROLL:
            page.mouse.wheel(0, 800)
        elif action.action_type == ActionType.PRESS_KEY:
            page.keyboard.press(action.value or "Enter")
        elif action.action_type == ActionType.WAIT:
            page.wait_for_timeout(int(float(action.value or "1000")))
        elif action.action_type == ActionType.ASSERT:
            pass  # Assertions are evaluated by the Analyzer against PageState, not here.
        else:
            raise ValueError(f"Unsupported action type: {action.action_type}")

    def navigate(self, url: str) -> None:
        self.execute(Action(action_type=ActionType.NAVIGATE, value=url, description=f"goto {url}"))
