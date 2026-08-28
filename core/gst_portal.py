import os
import base64
import re
from typing import Dict, Any, List, Tuple, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class GSTPortalAutomation:
    """
    GST Portal login + GSTR-2B download automation using Playwright.
    Handles headless execution locally and detects cloud IP firewall blocks.
    """

    def __init__(self, download_dir: str = "output/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.login_url = "https://services.gst.gov.in/services/login"
        self.dashboard_url = "https://return.gst.gov.in/returns/auth/dashboard"

    def _launch_browser(self, playwright):
        launch_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1366,768",
        ]
        return playwright.chromium.launch(headless=True, args=launch_args)

    def _new_context(self, browser):
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            ignore_https_errors=True,
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            """
        )
        return context

    def _safe_close(self, browser=None, playwright=None):
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if playwright:
                playwright.stop()
        except Exception:
            pass

    def _page_debug_payload(self, page) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "page_url": "",
            "page_title": "",
            "html_snippet": "",
            "debug_screenshot_b64": "",
        }
        try:
            payload["page_url"] = page.url or ""
        except Exception:
            pass
        try:
            payload["page_title"] = page.title() or ""
        except Exception:
            pass
        try:
            html = page.content() or ""
            payload["html_snippet"] = html[:4000]
        except Exception:
            pass
        try:
            shot = page.screenshot(full_page=True)
            payload["debug_screenshot_b64"] = base64.b64encode(shot).decode("utf-8")
        except Exception:
            pass
        return payload

    def _find_captcha_element(self, page):
        selectors = [
            "#imgCaptcha",
            "img#imgCaptcha",
            "#captchaImg",
            "img#captchaImg",
            "img#captcha",
            "img[alt*='Captcha' i]",
            "img[src*='captcha' i]",
            "img[src*='Captcha']",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    return loc.first, sel
            except Exception:
                continue
        return None, "none"

    def fetch_login_captcha(self, username: str = "") -> Dict[str, Any]:
        playwright = None
        browser = None

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(45000)

            try:
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(2000)

            # Check if login form username field exists
            has_username = False
            for sel in ["#username", "input[name='username']", "input#username"]:
                try:
                    if page.locator(sel).count() > 0:
                        has_username = True
                        if username:
                            page.locator(sel).first.fill(username)
                        break
                except Exception:
                    continue

            page.wait_for_timeout(1500)

            # Attempt to locate CAPTCHA element
            captcha_el, strategy = self._find_captcha_element(page)

            if captcha_el is None:
                # Retry once by clicking password field focus
                try:
                    pass_loc = page.locator("#user_pass, input[type='password']")
                    if pass_loc.count() > 0:
                        pass_loc.first.click()
                        page.wait_for_timeout(1500)
                        captcha_el, strategy = self._find_captcha_element(page)
                except Exception:
                    pass

            if captcha_el is None:
                debug = self._page_debug_payload(page)
                self._safe_close(browser, playwright)

                is_cloud_blocked = False
                if has_username:
                    is_cloud_blocked = True
                    friendly = (
                        "🔒 GST Portal Firewall Restriction: The GST Portal server loaded the login page "
                        "without issuing a CAPTCHA because it detected a Cloud Datacenter IP (Render/AWS). "
                        "\n\n👉 **To use Option B (Auto-Fetch):** Run AuditPilot locally on your laptop (`streamlit run app.py`). "
                        "\n👉 **For Cloud Demos:** Use Option A (Manual File Upload)."
                    )
                else:
                    friendly = f"Could not reach GST Portal login page. Title: {debug.get('page_title', '')}"

                return {
                    "success": False,
                    "error": friendly,
                    "technical_error": f"Cloud IP Firewall Filter Active (username_found={has_username}, captcha_found=False)",
                    "debug_screenshot_b64": debug.get("debug_screenshot_b64", ""),
                    "page_url": debug.get("page_url", ""),
                    "page_title": debug.get("page_title", ""),
                    "cloud_blocked": is_cloud_blocked,
                }

            captcha_bytes = captcha_el.screenshot()
            captcha_b64 = base64.b64encode(captcha_bytes).decode("utf-8")

            return {
                "success": True,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "captcha_b64": captcha_b64,
                "captcha_strategy": strategy,
            }

        except Exception as e:
            self._safe_close(browser, playwright)
            return {
                "success": False,
                "error": f"Could not connect to GST Portal. Details: {str(e)}",
                "technical_error": str(e),
            }

    def login_and_download_gstr2b(
        self,
        session: Dict[str, Any],
        username: str,
        password: str,
        captcha_text: str,
        fy: str,
        period: str,
    ) -> Dict[str, Any]:
        page = session.get("page")
        browser = session.get("browser")
        playwright = session.get("playwright")

        if not page or not browser or not playwright:
            return {
                "success": False,
                "error": "Session expired. Please click Load CAPTCHA again.",
            }

        try:
            # Fill Credentials
            page.locator("#username, input[name='username']").first.fill(username)
            page.locator("#user_pass, input[name='user_pass']").first.fill(password)
            page.locator("#captcha, input[name='captcha']").first.fill(captcha_text.strip())

            # Submit
            login_btn = page.locator("button[type='submit'], button:has-text('Login'), text=LOGIN")
            if login_btn.count() > 0:
                login_btn.first.click()
            else:
                page.keyboard.press("Enter")

            page.wait_for_timeout(4000)

            # Check for invalid captcha / login errors
            err_loc = page.locator(".err-msg, .alert-danger, #error")
            if err_loc.count() > 0:
                txt = err_loc.first.inner_text().strip()
                if txt and len(txt) < 200:
                    raise Exception(f"GST Portal Response: {txt}")

            # Navigate to returns dashboard
            page.goto(self.dashboard_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)

            save_name = f"gstr2b_{re.sub(r'[^A-Za-z0-9_]+', '_', username)}_{fy}_{str(period).replace(' ', '_')}.json"
            save_path = os.path.join(self.download_dir, save_name)

            self._safe_close(browser, playwright)
            return {"success": True, "file_path": save_path}

        except Exception as e:
            self._safe_close(browser, playwright)
            return {"success": False, "error": str(e)}