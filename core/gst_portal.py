import os
import base64
import re
from typing import Dict, Any, Optional, List
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class GSTPortalAutomation:
    """
    GST Portal login + GSTR-2B download automation using Playwright.
    Designed for Docker/Render (headless Chromium).
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
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        return playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )

    def _new_context(self, browser):
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        # Reduce obvious automation flags
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
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
        """Capture screenshot + HTML snippet when selectors fail."""
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
            payload["html_snippet"] = html[:2500]
        except Exception:
            pass
        try:
            shot = page.screenshot(full_page=True)
            payload["debug_screenshot_b64"] = base64.b64encode(shot).decode("utf-8")
            # Also save to disk for Render shell/log debugging
            debug_path = os.path.join(self.download_dir, "gst_login_debug.png")
            with open(debug_path, "wb") as f:
                f.write(shot)
        except Exception:
            pass
        return payload

    def _find_captcha_locator(self, page):
        """
        Try multiple known GST portal CAPTCHA patterns.
        Returns (locator, strategy_name) or (None, reason).
        """
        selectors: List[str] = [
            "#imgCaptcha",
            "img#imgCaptcha",
            "#captchaImg",
            "img#captchaImg",
            "img#captcha",
            "#captcha_image",
            "img.captcha",
            "img[alt='Captcha']",
            "img[alt='CAPTCHA']",
            "img[alt*='Captcha']",
            "img[alt*='captcha']",
            "img[src*='captcha']",
            "img[src*='Captcha']",
            "img[src*='CAPTCHA']",
            "img[src*='captchaAuth']",
            "img[src*='getCaptcha']",
            "//img[contains(@id,'aptcha')]",
            "//img[contains(@src,'aptcha')]",
            "//img[contains(@alt,'aptcha')]",
        ]

        for sel in selectors:
            try:
                if sel.startswith("//"):
                    loc = page.locator(f"xpath={sel}")
                else:
                    loc = page.locator(sel)
                if loc.count() > 0:
                    first = loc.first
                    try:
                        if first.is_visible(timeout=2000):
                            return first, sel
                    except Exception:
                        # Some captcha imgs report not visible briefly; still try
                        return first, sel
            except Exception:
                continue

        # Fallback: scan all images and pick likely captcha by src/alt/size
        try:
            images = page.locator("img")
            count = images.count()
            for i in range(min(count, 40)):
                img = images.nth(i)
                try:
                    alt = (img.get_attribute("alt") or "").lower()
                    src = (img.get_attribute("src") or "").lower()
                    id_attr = (img.get_attribute("id") or "").lower()
                    cls = (img.get_attribute("class") or "").lower()
                    blob = f"{alt} {src} {id_attr} {cls}"
                    if "captcha" in blob or "capcha" in blob:
                        return img, f"img-scan[{i}]"
                    # GST captchas are often small wide images near login form
                    box = img.bounding_box()
                    if box and 40 <= box.get("height", 0) <= 80 and 100 <= box.get("width", 0) <= 250:
                        # Near password field preference handled by scan order
                        if "data:" in src or "captcha" in src or src.endswith(".png") or "image" in src:
                            return img, f"img-size-heuristic[{i}]"
                except Exception:
                    continue
        except Exception:
            pass

        return None, "no-matching-img"

    def fetch_login_captcha(self) -> Dict[str, Any]:
        playwright = None
        browser = None

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(60000)

            # Navigate — portal is slow from cloud IPs
            try:
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeoutError:
                # Continue even on timeout; DOM may still be usable
                pass

            page.wait_for_timeout(2500)

            # Wait for login form as proof we hit the real login page
            form_ready = False
            for sel in ["#username", "input[name='username']", "input#username", "input[type='text']"]:
                try:
                    page.wait_for_selector(sel, timeout=15000)
                    form_ready = True
                    break
                except Exception:
                    continue

            # Extra settle time for captcha image JS
            page.wait_for_timeout(2000)

            # Sometimes captcha appears only after a tiny interaction
            try:
                page.mouse.move(200, 200)
                page.wait_for_timeout(500)
            except Exception:
                pass

            captcha, strategy = self._find_captcha_locator(page)

            if captcha is None:
                debug = self._page_debug_payload(page)
                self._safe_close(browser, playwright)

                # Friendly diagnosis from HTML/title
                html_l = (debug.get("html_snippet") or "").lower()
                title_l = (debug.get("page_title") or "").lower()
                url_l = (debug.get("page_url") or "").lower()

                if "access denied" in html_l or "blocked" in html_l or "forbidden" in html_l:
                    reason = (
                        "GST Portal blocked this server IP (common on cloud). "
                        "Try again later or use Option A (Manual Upload)."
                    )
                elif "maintenance" in html_l or "unavailable" in html_l:
                    reason = "GST Portal appears under maintenance or temporarily unavailable."
                elif not form_ready and "login" not in title_l and "login" not in url_l:
                    reason = (
                        "Did not reach GST login form (redirect/block). "
                        f"URL: {debug.get('page_url', '')} | Title: {debug.get('page_title', '')}"
                    )
                else:
                    reason = (
                        "CAPTCHA image not found on GST login page. "
                        "Portal DOM may have changed or captcha failed to render in headless mode."
                    )

                return {
                    "success": False,
                    "error": reason,
                    "technical_error": f"strategy={strategy}; url={debug.get('page_url')}; title={debug.get('page_title')}",
                    "debug_screenshot_b64": debug.get("debug_screenshot_b64", ""),
                    "html_snippet": debug.get("html_snippet", ""),
                    "page_url": debug.get("page_url", ""),
                    "page_title": debug.get("page_title", ""),
                }

            # Screenshot just the captcha element
            try:
                captcha.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            captcha_bytes = captcha.screenshot()
            captcha_b64 = base64.b64encode(captcha_bytes).decode("utf-8")

            if not captcha_b64 or len(captcha_bytes) < 50:
                debug = self._page_debug_payload(page)
                self._safe_close(browser, playwright)
                return {
                    "success": False,
                    "error": "CAPTCHA element found but screenshot was empty.",
                    "technical_error": f"strategy={strategy}",
                    "debug_screenshot_b64": debug.get("debug_screenshot_b64", ""),
                    "html_snippet": debug.get("html_snippet", ""),
                }

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
            try:
                if browser:
                    # best-effort debug if page exists
                    pass
            except Exception:
                pass
            self._safe_close(browser, playwright)

            err = str(e)
            if (
                "Executable doesn't exist" in err
                or "chromium" in err.lower()
                or "browser" in err.lower()
            ):
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
            return {
                "success": False,
                "error": "Session expired. Click Load CAPTCHA again.",
            }

        try:
            user_selectors = ["#username", "input[name='username']", "input#user"]
            pass_selectors = ["#user_pass", "input[name='user_pass']", "input[type='password']"]
            captcha_selectors = ["#captcha", "input[name='captcha']", "input#captcha"]

            def fill_first(selectors, value):
                for sel in selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.fill("")
                        loc.first.fill(value)
                        return True
                return False

            if not fill_first(user_selectors, username):
                raise Exception("Username field not found.")
            if not fill_first(pass_selectors, password):
                raise Exception("Password field not found.")
            if not fill_first(captcha_selectors, captcha_text.strip()):
                raise Exception("CAPTCHA input not found.")

            clicked_login = False
            for sel in [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Login')",
                "button:has-text('LOGIN')",
                "text=LOGIN",
                "text=Login",
            ]:
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

            page.wait_for_timeout(5000)

            # Detect login errors
            for sel in [".err-msg", ".alert-danger", ".error", ".text-danger", "#error", ".alert"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        txt = loc.first.inner_text().strip()
                        if txt and len(txt) < 300:
                            low = txt.lower()
                            if any(
                                k in low
                                for k in [
                                    "invalid",
                                    "captcha",
                                    "password",
                                    "login",
                                    "incorrect",
                                    "not match",
                                ]
                            ):
                                raise Exception(f"GST Portal login error: {txt}")
                    except Exception as ex:
                        if "GST Portal login error" in str(ex):
                            raise

            # Navigate returns dashboard
            page.goto(self.dashboard_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)

            # If still on login page, session failed
            cur = (page.url or "").lower()
            if "login" in cur and "auth" not in cur:
                debug = self._page_debug_payload(page)
                raise Exception(
                    "Login did not succeed (still on login page). "
                    "Wrong credentials/CAPTCHA, or portal blocked the session."
                )

            month_name = period.split()[0] if period else ""
            year_label = fy or ""

            for sel, val in [
                ("#fin", year_label),
                ("select[name='fin']", year_label),
                ("#fy", year_label),
                ("#mon", month_name),
                ("select[name='mon']", month_name),
                ("#month", month_name),
            ]:
                if not val:
                    continue
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        try:
                            loc.first.select_option(val)
                        except Exception:
                            loc.first.select_option(label=val)
                        page.wait_for_timeout(800)
                except Exception:
                    pass

            for sel in ["#search", "button:has-text('Search')", "button:has-text('SEARCH')", "text=SEARCH"]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=2500)
                        page.wait_for_timeout(2500)
                        break
                    except Exception:
                        continue

            save_name = f"gstr2b_{re.sub(r'[^A-Za-z0-9_]+', '_', username)}_{fy}_{str(period).replace(' ', '_')}.json"
            save_path = os.path.join(self.download_dir, save_name)

            click_targets = [
                "text=GSTR-2B",
                "a:has-text('GSTR-2B')",
                "button:has-text('GSTR-2B')",
                "text=Download",
                "text=DOWNLOAD",
                "text=JSON",
                "button:has-text('JSON')",
                "a:has-text('JSON')",
                "a:has-text('Download')",
            ]

            for sel in click_targets[:3]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=2500)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

            try:
                with page.expect_download(timeout=60000) as di:
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
                debug = self._page_debug_payload(page)
                raise Exception(
                    "Logged in, but could not auto-download GSTR-2B JSON. "
                    "GST portal buttons may have changed for this account/period. "
                    f"Details: {ex}"
                )

            download.save_as(save_path)

            if not os.path.exists(save_path) or os.path.getsize(save_path) < 10:
                raise Exception("Download completed but file is empty/invalid.")

            self._safe_close(browser, playwright)

            return {"success": True, "file_path": save_path}

        except Exception as e:
            self._safe_close(browser, playwright)
            return {"success": False, "error": str(e)}