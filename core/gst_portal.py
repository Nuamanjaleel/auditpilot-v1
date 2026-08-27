import os
import time
import base64
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright


class GSTPortalAutomation:
    """
    Automates GST Portal login and GSTR-2B JSON downloading using Playwright.
    """
    
    def __init__(self, download_dir: str = "output/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.login_url = "https://services.gst.gov.in/services/login"

    def fetch_login_captcha(self) -> Dict[str, Any]:
        """
        Launches browser, opens GST portal login page, captures CAPTCHA image as Base64,
        and returns the browser context to keep the session alive.
        """
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        
        try:
            page.goto(self.login_url, wait_until="networkidle", timeout=30000)
            
            # Locate CAPTCHA image element
            captcha_img = page.locator("#imgCaptcha")
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
            browser.close()
            playwright.stop()
            return {
                "success": False,
                "error": str(e)
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
        Submits login form with user-entered CAPTCHA, navigates to Returns Dashboard,
        and downloads GSTR-2B JSON file.
        """
        page = session["page"]
        browser = session["browser"]
        playwright = session["playwright"]
        
        try:
            # Fill Credentials
            page.fill("#username", username)
            page.fill("#user_pass", password)
            page.fill("#captcha", captcha_text)
            
            # Click Login
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)
            
            # Check for invalid CAPTCHA or Login Error
            error_elem = page.locator(".err-msg, .alert-danger")
            if error_elem.count() > 0 and error_elem.is_visible():
                error_text = error_elem.inner_text()
                browser.close()
                playwright.stop()
                return {"success": False, "error": f"GST Portal Error: {error_text}"}
            
            # Successfully logged in -> Navigate to Return Dashboard
            page.goto("https://return.gst.gov.in/returns/auth/dashboard", wait_until="networkidle")
            
            # Select FY and Return Period (Dropdowns)
            # Map FY e.g., '2024-25' -> '2024-25'
            page.select_option("#fin", fy)
            page.wait_for_timeout(1000)
            
            # Map Period e.g., 'June 2024' -> 'June'
            month_name = period.split()[0]
            page.select_option("#mon", month_name)
            
            # Click Search
            page.click("#search")
            page.wait_for_timeout(2000)
            
            # Click GSTR-2B Download Tile
            # Trigger download
            with page.expect_download(timeout=30000) as download_info:
                # Selector for GSTR-2B Download JSON button
                page.click("button:has-text('DOWNLOAD GSTR-2B'), a:has-text('GSTR-2B')")
                page.wait_for_timeout(1000)
                page.click("button:has-text('GENERATE JSON'), a:has-text('JSON')")
                
            download = download_info.value
            json_filename = f"gstr2b_{username}_{fy}_{period.replace(' ', '_')}.json"
            save_path = os.path.join(self.download_dir, json_filename)
            download.save_as(save_path)
            
            browser.close()
            playwright.stop()
            
            return {
                "success": True,
                "file_path": save_path
            }
            
        except Exception as e:
            browser.close()
            playwright.stop()
            return {
                "success": False,
                "error": f"Automation Failed: {str(e)}"
            }