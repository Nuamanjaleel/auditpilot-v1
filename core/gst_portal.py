import os
import base64
from typing import Dict, Any
from playwright.sync_api import sync_playwright


class GSTPortalAutomation:
    """
    Automates GST Portal login and GSTR-2B JSON downloading using Playwright.
    Note: Works best on local machines. Streamlit Cloud free tier often blocks browser launch.
    """

    def __init__(self, download_dir: str = "output/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.login_url = "https://services.gst.gov.in/services/login"

    def _launch_browser(self, playwright):
        """
        Try launching Chromium with cloud-friendly flags.
        """
        launch_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
        ]

        # First try normal chromium
        try:
            browser = playwright.chromium.launch(
                headless=True,
                args=launch_args
            )
            return browser
        except Exception:
            # Fallback: try channel chrome if available
            browser = playwright.chromium.launch(
                headless=True,
                channel="chrome",
                args=launch_args
            )
            return browser

    def fetch_login_captcha(self) -> Dict[str, Any]:
        """
        Opens GST portal login page and returns CAPTCHA image as base64.
        """
        playwright = None
        browser = None

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)

            # CAPTCHA image selector (GST portal)
            captcha_img = page.locator("#imgCaptcha")
            if captcha_img.count() == 0:
                # fallback selector variants
                captcha_img = page.locator("img[alt*='Captcha'], img[id*='captcha'], img[src*='captcha']").first

            captcha_bytes = captcha_img.screenshot()
            captcha_b64 = base64.b64encode(captcha_bytes).decode("utf-8")

            return {
                "success": True,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "captcha_b64": captcha_b64
            }

        except Exception as e:
            # Clean up if partially started
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

            msg = str(e)
            friendly = (
                "GST Auto-Fetch is not supported on this cloud server right now "
                "(browser automation blocked). "
                "Please use Option A: Manual File Upload, or run AuditPilot locally for Option B."
            )

            # Keep technical detail short
            return {
                "success": False,
                "error": friendly,
                "technical_error": msg
            }

    def login_and_download_gstr2b(
        self,
        session: Dict[str, Any],
        username: str,
        password: str,
        captcha_text: str,
        fy: str,
        period: str
    ) -> Dict[str, Any]:
        """
        Logs in using CAPTCHA and attempts GSTR-2B JSON download.
        """
        page = session.get("page")
        browser = session.get("browser")
        playwright = session.get("playwright")

        if not page or not browser or not playwright:
            return {
                "success": False,
                "error": "Session expired. Please click 'Load CAPTCHA' again."
            }

        try:
            # Fill credentials
            page.fill("#username", username)
            page.fill("#user_pass", password)
            page.fill("#captcha", captcha_text)

            # Click login
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)

            # Login error check
            error_elem = page.locator(".err-msg, .alert-danger, .error")
            if error_elem.count() > 0:
                try:
                    if error_elem.first.is_visible():
                        error_text = error_elem.first.inner_text().strip()
                        if error_text:
                            browser.close()
                            playwright.stop()
                            return {"success": False, "error": f"GST Portal Error: {error_text}"}
                except Exception:
                    pass

            # Go to returns dashboard
            page.goto(
                "https://return.gst.gov.in/returns/auth/dashboard",
                wait_until="domcontentloaded",
                timeout=45000
            )
            page.wait_for_timeout(2000)

            # FY / month selection (best-effort; portal DOM changes often)
            try:
                page.select_option("#fin", fy)
                page.wait_for_timeout(800)
            except Exception:
                pass

            try:
                month_name = period.split()[0]
                page.select_option("#mon", month_name)
                page.wait_for_timeout(800)
            except Exception:
                pass

            try:
                page.click("#search")
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # Try download flow
            json_filename = f"gstr2b_{username}_{fy}_{period.replace(' ', '_')}.json"
            save_path = os.path.join(self.download_dir, json_filename)

            # This section is portal-DOM dependent and may need selector tuning with real account
            with page.expect_download(timeout=30000) as download_info:
                # Try common buttons/links
                candidates = [
                    "text=GSTR-2B",
                    "text=DOWNLOAD",
                    "text=Download",
                    "text=JSON",
                    "button:has-text('GSTR-2B')",
                    "a:has-text('GSTR-2B')",
                ]
                clicked = False
                for sel in candidates:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        try:
                            loc.first.click(timeout=2000)
                            clicked = True
                            page.wait_for_timeout(1000)
                        except Exception:
                            continue
                if not clicked:
                    raise Exception("Could not find GSTR-2B download button. Portal UI may have changed.")

            download = download_info.value
            download.save_as(save_path)

            browser.close()
            playwright.stop()

            return {
                "success": True,
                "file_path": save_path
            }

        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass

            return {
                "success": False,
                "error": (
                    "Auto-download failed. Use Option A (Manual Upload) for now. "
                    f"Details: {str(e)}"
                )
            }