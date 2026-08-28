import os
import base64
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright


class GSTPortalAutomation:
    """
    GST Portal login + GSTR-2B download automation using Playwright.
    Designed to run on Docker/Render (not Streamlit Cloud free tier).
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

        return playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )

    def fetch_login_captcha(self) -> Dict[str, Any]:
        playwright = None
        browser = None

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)

            # Try multiple captcha selectors (portal DOM changes)
            captcha = None
            for sel in ["#imgCaptcha", "img#captcha", "img[alt*='Captcha' i]", "img[src*='captcha' i]"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    captcha = loc.first
                    break

            if captcha is None:
                raise Exception("CAPTCHA image not found on GST login page.")

            captcha_bytes = captcha.screenshot()
            captcha_b64 = base64.b64encode(captcha_bytes).decode("utf-8")

            return {
                "success": True,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "captcha_b64": captcha_b64,
            }

        except Exception as e:
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

            err = str(e)
            if "Executable doesn't exist" in err or "chromium" in err.lower() or "browser" in err.lower():
                friendly = (
                    "Browser engine not available on this server. "
                    "Use the Render Docker deployment for GST Auto-Fetch, "
                    "or use Option A (Manual Upload)."
                )
            else:
                friendly = f"Could not open GST Portal login page. Details: {err}"

            return {"success": False, "error": friendly, "technical_error": err}

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
            return {"success": False, "error": "Session expired. Click Load CAPTCHA again."}

        try:
            # Fill login form
            user_selectors = ["#username", "input[name='username']", "input#user"]
            pass_selectors = ["#user_pass", "input[name='user_pass']", "input[type='password']"]
            captcha_selectors = ["#captcha", "input[name='captcha']", "input#captcha"]

            def fill_first(selectors, value):
                for sel in selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.fill(value)
                        return True
                return False

            if not fill_first(user_selectors, username):
                raise Exception("Username field not found.")
            if not fill_first(pass_selectors, password):
                raise Exception("Password field not found.")
            if not fill_first(captcha_selectors, captcha_text):
                raise Exception("CAPTCHA input not found.")

            # Submit login
            clicked_login = False
            for sel in ["button[type='submit']", "input[type='submit']", "button:has-text('Login')", "text=LOGIN"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=3000)
                        clicked_login = True
                        break
                    except Exception:
                        continue
            if not clicked_login:
                page.keyboard.press("Enter")

            page.wait_for_timeout(4000)

            # Check obvious login errors
            for sel in [".err-msg", ".alert-danger", ".error", ".text-danger"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        txt = loc.first.inner_text().strip()
                        if txt and len(txt) < 300:
                            low = txt.lower()
                            if "invalid" in low or "captcha" in low or "password" in low or "login" in low:
                                raise Exception(f"GST Portal login error: {txt}")
                    except Exception as ex:
                        if "GST Portal login error" in str(ex):
                            raise

            # Go to returns dashboard
            page.goto(self.dashboard_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)

            # Best-effort FY/month selection
            month_name = period.split()[0] if period else ""
            for sel, val in [("#fin", fy), ("select[name='fin']", fy), ("#mon", month_name), ("select[name='mon']", month_name)]:
                if not val:
                    continue
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.select_option(val)
                        page.wait_for_timeout(700)
                except Exception:
                    try:
                        loc.first.select_option(label=val)
                        page.wait_for_timeout(700)
                    except Exception:
                        pass

            for sel in ["#search", "button:has-text('Search')", "text=SEARCH"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=2500)
                        page.wait_for_timeout(2000)
                        break
                    except Exception:
                        continue

            # Attempt download
            save_name = f"gstr2b_{username}_{fy}_{str(period).replace(' ', '_')}.json"
            save_path = os.path.join(self.download_dir, save_name)

            # Portal UI changes often; try multiple click paths
            download = None
            click_targets = [
                "text=GSTR-2B",
                "a:has-text('GSTR-2B')",
                "button:has-text('GSTR-2B')",
                "text=Download",
                "text=DOWNLOAD",
                "text=JSON",
                "button:has-text('JSON')",
                "a:has-text('JSON')",
            ]

            # First navigate/open GSTR-2B section
            for sel in click_targets[:3]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=2500)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

            try:
                with page.expect_download(timeout=45000) as di:
                    clicked = False
                    for sel in click_targets:
                        loc = page.locator(sel)
                        if loc.count() == 0:
                            continue
                        try:
                            loc.first.click(timeout=2500)
                            clicked = True
                            page.wait_for_timeout(1000)
                        except Exception:
                            continue
                    if not clicked:
                        raise Exception("Could not find a GSTR-2B/JSON download button.")
                download = di.value
            except Exception as ex:
                raise Exception(
                    "Logged in, but could not auto-download GSTR-2B JSON. "
                    "GST portal buttons may have changed for this account/period. "
                    f"Details: {ex}"
                )

            download.save_as(save_path)

            # Basic sanity check
            if not os.path.exists(save_path) or os.path.getsize(save_path) < 10:
                raise Exception("Download completed but file is empty/invalid.")

            try:
                browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass

            return {"success": True, "file_path": save_path}

        except Exception as e:
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
            return {"success": False, "error": str(e)}