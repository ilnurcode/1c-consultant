from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def ensure_playwright_installed() -> bool:
    """Ensure playwright chromium browser is installed; auto-install if missing."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                return True
            except Exception:
                logger.info("Chromium not found in Playwright cache, downloading...")
                res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True)
                return res.returncode == 0
    except ImportError:
        logger.warning("playwright package is not installed.")
        return False
    except Exception as e:
        logger.error(f"Playwright verification failed: {e}")
        return False


class Playwright1CClient:
    """Browser automation client specifically designed for 1C:Enterprise Web Client."""

    def __init__(
        self,
        web_url: str,
        username: str = "",
        password: str = "",
        headless: bool = False,
        browser_type: str = "chromium",
    ) -> None:
        self.web_url = web_url
        self.username = username
        self.password = password
        self.headless = headless
        self.browser_type = browser_type
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        browser_name = (self.browser_type or "chromium").lower()
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        if browser_name == "msedge":
            launcher = self._playwright.chromium
            launch_kwargs["channel"] = "msedge"
        elif browser_name in {"chromium", "firefox", "webkit"}:
            launcher = getattr(self._playwright, browser_name)
        else:
            launcher = self._playwright.chromium
        try:
            self._browser = launcher.launch(**launch_kwargs)
        except Exception as exc:
            raise RuntimeError(
                "Не удалось запустить браузер Playwright. "
                "Для автономного EXE рекомендуется выбрать browser=msedge (если Microsoft Edge установлен) "
                "или установить браузеры командой: python -m playwright install chromium. "
                f"Исходная ошибка: {exc}"
            ) from exc
        self._context = self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
        )
        self._page = self._context.new_page()

    def stop(self) -> None:
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    @property
    def page(self):
        if not self._page:
            self.start()
        return self._page

    def navigate(self, url: str | None = None) -> dict[str, Any]:
        target_url = url or self.web_url
        self.page.goto(target_url, wait_until="networkidle", timeout=60000)
        self._handle_1c_auth()
        return {
            "title": self.page.title(),
            "url": self.page.url,
            "status": "ready",
        }

    def _handle_1c_auth(self) -> None:
        """Automatically fills login form if 1C Web Client displays authorization prompt."""
        if not self.username:
            return
        try:
            # 1C Web Client login selectors
            user_input = self.page.locator("input[type='text'], input#userName, input[name='userName']").first
            if user_input.is_visible(timeout=3000):
                user_input.fill(self.username)
                if self.password:
                    pass_input = self.page.locator("input[type='password'], input#userPassword, input[name='userPassword']").first
                    if pass_input.is_visible(timeout=1000):
                        pass_input.fill(self.password)
                # Press Enter or click OK
                ok_btn = self.page.locator("button:has-text('ОК'), button:has-text('Войти'), div[role='button']:has-text('ОК')").first
                if ok_btn.is_visible(timeout=1000):
                    ok_btn.click()
                else:
                    self.page.keyboard.press("Enter")
                self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            # Non-blocking if auth form was not present or already authenticated
            pass

    def get_accessibility_snapshot(self) -> dict[str, Any]:
        """Returns accessibility tree representing the currently visible 1C controls."""
        try:
            snapshot = self.page.accessibility.snapshot()
            return snapshot or {}
        except Exception as e:
            return {"error": str(e)}

    def get_interactive_elements(self) -> list[dict[str, Any]]:
        """Scans page for visible clickable/input elements with their texts and bounding roles."""
        js_code = """
        () => {
            const elements = [];
            const candidates = document.querySelectorAll('button, input, textarea, select, a, [role="button"], [role="tab"], [role="menuitem"], [role="gridcell"], .v8-item, .gridRow');
            for (const el of candidates) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
                    elements.push({
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        role: el.getAttribute('role') || '',
                        text: (el.innerText || el.value || el.getAttribute('title') || el.getAttribute('aria-label') || '').trim().slice(0, 100),
                        type: el.getAttribute('type') || '',
                        name: el.getAttribute('name') || '',
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    });
                }
            }
            return elements.slice(0, 150); // limit to top 150 elements for context window
        }
        """
        try:
            return self.page.evaluate(js_code)
        except Exception as e:
            return [{"error": str(e)}]

    def click(self, text_or_selector: str) -> dict[str, Any]:
        """Click on element by text or CSS selector with fallback strategies for 1C DOM."""
        p = self.page
        # Strategy 1: exact text locator
        loc = p.get_by_text(text_or_selector, exact=True).first
        if loc.is_visible():
            loc.click()
            p.wait_for_timeout(500)
            return {"status": "clicked", "target": text_or_selector, "strategy": "exact_text"}

        # Strategy 2: partial text locator
        loc = p.get_by_text(text_or_selector, exact=False).first
        if loc.is_visible():
            loc.click()
            p.wait_for_timeout(500)
            return {"status": "clicked", "target": text_or_selector, "strategy": "contains_text"}

        # Strategy 3: CSS / XPath selector
        try:
            loc = p.locator(text_or_selector).first
            if loc.is_visible():
                loc.click()
                p.wait_for_timeout(500)
                return {"status": "clicked", "target": text_or_selector, "strategy": "selector"}
        except Exception:
            pass

        raise ValueError(f"Could not find visible element to click: '{text_or_selector}'")

    def fill(self, selector_or_label: str, value: str) -> dict[str, Any]:
        """Fill input element by label or selector."""
        p = self.page
        try:
            loc = p.get_by_label(selector_or_label).first
            if loc.is_visible():
                loc.fill(value)
                return {"status": "filled", "field": selector_or_label, "value": value}
        except Exception:
            pass

        try:
            loc = p.locator(selector_or_label).first
            if loc.is_visible():
                loc.fill(value)
                return {"status": "filled", "field": selector_or_label, "value": value}
        except Exception:
            pass

        raise ValueError(f"Could not find visible input field: '{selector_or_label}'")

    def take_screenshot(self) -> str:
        """Capture screenshot and return base64 png string."""
        raw_bytes = self.page.screenshot(full_page=False)
        return base64.b64encode(raw_bytes).decode("ascii")
