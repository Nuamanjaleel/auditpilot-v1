import os
import base64
import re
from typing import Dict, Any, List, Tuple, Optional
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
        # headless=False is not available on Render; use new headless where possible
        try:
            return playwright.chromium.launch(
                headless=True,
                args=launch_args,
                chromium_sandbox=False,
            )
        except Exception:
            return playwright.chromium.launch(headless=True, args=launch_args)

    def _new_context(self, browser):
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
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
            "iframe_count": 0,
            "img_count": 0,
            "canvas_count": 0,
            "input_count": 0,
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
            payload["html_snippet"] = html[:5000]
        except Exception:
            pass
        try:
            payload["iframe_count"] = page.locator("iframe").count()
        except Exception:
            pass
        try:
            payload["img_count"] = page.locator("img").count()
        except Exception:
            pass
        try:
            payload["canvas_count"] = page.locator("canvas").count()
        except Exception:
            pass
        try:
            payload["input_count"] = page.locator("input").count()
        except Exception:
            pass
        try:
            shot = page.screenshot(full_page=True)
            payload["debug_screenshot_b64"] = base64.b64encode(shot).decode("utf-8")
            debug_path = os.path.join(self.download_dir, "gst_login_debug.png")
            with open(debug_path, "wb") as f:
                f.write(shot)
        except Exception:
            pass
        return payload

    def _try_captcha_on_frame(self, frame) -> Tuple[Optional[Any], str]:
        selectors: List[str] = [
            "#imgCaptcha",
            "img#imgCaptcha",
            "#captchaImg",
            "img#captchaImg",
            "img#captcha",
            "#captcha_image",
            "#captchaImage",
            "img.captcha",
            "img[alt='Captcha']",
            "img[alt='CAPTCHA']",
            "img[alt*='Captcha' i]",
            "img[alt*='captcha' i]",
            "img[src*='captcha' i]",
            "img[src*='Captcha']",
            "img[src*='CAPTCHA']",
            "img[src*='captchaAuth' i]",
            "img[src*='getCaptcha' i]",
            "img[id*='captcha' i]",
            "img[id*='Captcha']",
            "xpath=//img[contains(translate(@id,'CAPTCHA','captcha'),'captcha')]",
            "xpath=//img[contains(translate(@src,'CAPTCHA','captcha'),'captcha')]",
            "xpath=//img[contains(translate(@alt,'CAPTCHA','captcha'),'captcha')]",
        ]

        for sel in selectors:
            try:
                loc = frame.locator(sel)
                if loc.count() > 0:
                    return loc.first, sel
            except Exception:
                continue

        try:
            canvases = frame.locator("canvas")
            n = canvases.count()
            for i in range(min(n, 10)):
                c = canvases.nth(i)
                try:
                    box = c.bounding_box()
                    if not box:
                        continue
                    w, h = box.get("width", 0), box.get("height", 0)
                    if 60 <= w <= 300 and 20 <= h <= 100:
                        return c, f"canvas[{i}]"
                except Exception:
                    continue
        except Exception:
            pass

        try:
            images = frame.locator("img")
            count = images.count()
            for i in range(min(count, 60)):
                img = images.nth(i)
                try:
                    alt = (img.get_attribute("alt") or "").lower()
                    src = (img.get_attribute("src") or "").lower()
                    id_attr = (img.get_attribute("id") or "").lower()
                    cls = (img.get_attribute("class") or "").lower()
                    blob = f"{alt} {src} {id_attr} {cls}"
                    if any(k in blob for k in ["captcha", "capcha", "security"]):
                        return img, f"img-scan-keyword[{i}]"
                    box = img.bounding_box()
                    if box and 30 <= box.get("height", 0) <= 90 and 80 <= box.get("width", 0) <= 280:
                        if "data:image" in src or src.endswith((".png", ".jpg", ".jpeg", ".gif")):
                            return img, f"img-size-heuristic[{i}]"
                except Exception:
                    continue
        except Exception:
            pass

        return None, "none"

    def _find_captcha_locator(self, page) -> Tuple[Optional[Any], str]:
        captcha, strategy = self._try_captcha_on_frame(page)
        if captcha is not None:
            return captcha, f"main:{strategy}"

        try:
            for idx, frame in enumerate(page.frames):
                if frame == page.main_frame:
                    continue
                captcha, strategy = self._try_captcha_on_frame(frame)
                if captcha is not None:
                    return captcha, f"iframe[{idx}]:{strategy}"
        except Exception:
            pass

        return None, "no-matching-captcha"

    def _fill_first(self, page, selectors: List[str], value: str) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=2000)
                    loc.first.fill("")
                    loc.first.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _click_captcha_refresh(self, page) -> bool:
        refresh_selectors = [
            "#captchaRefresh",
            "#refreshCaptcha",
            "img[onclick*='captcha' i]",
            "a[onclick*='captcha' i]",
            "button[onclick*='captcha' i]",
            "i.fa-refresh",
            "i.fa-sync",
            "img[title*='refresh' i]",
            "img[alt*='refresh' i]",
            "xpath=//img[contains(@onclick,'Captcha') or contains(@onclick,'captcha')]",
            "xpath=//a[contains(@onclick,'Captcha') or contains(@onclick,'captcha')]",
        ]
        for sel in refresh_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=2000)
                    return True
            except Exception:
                continue
        return False

    def _try_load_captcha_endpoints(self, page) -> Optional[bytes]:
        """
        Some GST builds expose captcha at known paths.
        Try fetching image bytes directly in-page.
        """
        candidates = [
            "https://services.gst.gov.in/services/captcha",
            "https://services.gst.gov.in/services/auth/captcha",
            "https://services.gst.gov.in/services/captcha.jpg",
            "https://services.gst.gov.in/services/getCaptcha",
            "/services/captcha",
            "/services/auth/captcha",
        ]
        for url in candidates:
            try:
                resp = page.request.get(url, timeout=15000)
                if resp.ok:
                    body = resp.body()
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if body and len(body) > 200 and (
                        "image" in ctype
                        or body[:3] == b"\xff\xd8\xff"
                        or body[:8] == b"\x89PNG\r\n\x1a\n"
                        or body[:3] == b"GIF"
                    ):
                        return body
            except Exception:
                continue
        return None

    def fetch_login_captcha(self, username: str = "") -> Dict[str, Any]:
        """
        Open GST login, optionally type username (triggers captcha on some builds),
        capture captcha via DOM or network.
        """
        playwright = None
        browser = None
        network_captcha_bytes: List[bytes] = []

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(60000)

            def on_response(response):
                try:
                    url = (response.url or "").lower()
                    ctype = (response.headers.get("content-type") or "").lower()
                    if response.status != 200:
                        return
                    looks_captcha = (
                        "captcha" in url
                        or "capcha" in url
                        or ("image" in ctype and "services.gst.gov.in" in url)
                    )
                    if not looks_captcha:
                        return
                    if "image" not in ctype and "captcha" not in url:
                        return
                    body = response.body()
                    if body and len(body) > 200:
                        network_captcha_bytes.append(body)
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(2000)

            # Ensure login form exists
            form_ready = False
            for sel in [
                "#username",
                "input[name='username']",
                "input#username",
                "input[type='password']",
                "input[name='user_pass']",
            ]:
                try:
                    page.wait_for_selector(sel, timeout=20000)
                    form_ready = True
                    break
                except Exception:
                    continue

            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            page.wait_for_timeout(1500)

            # Type username first — many GST builds lazy-load captcha after this
            if username:
                self._fill_first(
                    page,
                    ["#username", "input[name='username']", "input#username"],
                    username,
                )
                page.wait_for_timeout(1500)
                # Tab to password to mimic human
                try:
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(800)
                except Exception:
                    pass

            # Click password field
            self._fill_first(
                page,
                ["#user_pass", "input[name='user_pass']", "input[type='password']"],
                "",  # focus only; real password entered at login step
            )
            # empty fill may clear — just click focus instead if needed
            try:
                for sel in ["#user_pass", "input[name='user_pass']", "input[type='password']"]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click(timeout=2000)
                        break
            except Exception:
                pass

            page.wait_for_timeout(1000)
            self._click_captcha_refresh(page)
            page.wait_for_timeout(2000)

            # Poll DOM for captcha up to ~25s
            captcha = None
            strategy = "none"
            for _ in range(12):
                captcha, strategy = self._find_captcha_locator(page)
                if captcha is not None:
                    break
                self._click_captcha_refresh(page)
                page.wait_for_timeout(2000)

            captcha_b64 = None
            final_strategy = strategy

            if captcha is not None:
                try:
                    captcha.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(400)
                try:
                    captcha_bytes = captcha.screenshot()
                    if captcha_bytes and len(captcha_bytes) > 50:
                        captcha_b64 = base64.b64encode(captcha_bytes).decode("utf-8")
                        final_strategy = f"dom:{strategy}"
                except Exception:
                    pass

            # Network-captured captcha image
            if not captcha_b64 and network_captcha_bytes:
                captcha_b64 = base64.b64encode(network_captcha_bytes[-1]).decode("utf-8")
                final_strategy = "network-intercept"

            # Direct endpoint fetch
            if not captcha_b64:
                direct = self._try_load_captcha_endpoints(page)
                if direct:
                    captcha_b64 = base64.b64encode(direct).decode("utf-8")
                    final_strategy = "direct-endpoint"
                    # inject into page so user still sees it; login still needs captcha input in DOM
                    try:
                        page.evaluate(
                            """(b64) => {
                                let img = document.querySelector('#imgCaptcha, img[id*="aptcha" i]');
                                if (!img) {
                                    img = document.createElement('img');
                                    img.id = 'imgCaptcha';
                                    img.alt = 'Captcha';
                                    const pass = document.querySelector('#user_pass, input[type=password]');
                                    if (pass && pass.parentElement) {
                                        pass.parentElement.appendChild(img);
                                    } else {
                                        document.body.appendChild(img);
                                    }
                                }
                                img.src = 'data:image/png;base64,' + b64;
                                let inp = document.querySelector('#captcha, input[name=captcha]');
                                if (!inp) {
                                    inp = document.createElement('input');
                                    inp.id = 'captcha';
                                    inp.name = 'captcha';
                                    inp.type = 'text';
                                    inp.placeholder = 'Enter Captcha';
                                    img.insertAdjacentElement('afterend', inp);
                                }
                            }""",
                            captcha_b64,
                        )
                    except Exception:
                        pass

            if not captcha_b64:
                debug = self._page_debug_payload(page)
                # Check if captcha *input* exists without image
                has_captcha_input = False
                try:
                    for sel in ["#captcha", "input[name='captcha']", "input[id*='captcha' i]"]:
                        if page.locator(sel).count() > 0:
                            has_captcha_input = True
                            break
                except Exception:
                    pass

                self._safe_close(browser, playwright)

                html_l = (debug.get("html_snippet") or "").lower()
                if any(
                    k in html_l
                    for k in [
                        "access denied",
                        "request blocked",
                        "forbidden",
                        "cloudflare",
                        "cf-browser",
                    ]
                ):
                    reason = (
                        "GST Portal/WAF blocked this cloud server IP. "
                        "Use Option A (Manual Upload) or run Option B on your local laptop."
                    )
                elif not form_ready:
                    reason = (
                        "Did not reach GST login form. "
                        f"URL: {debug.get('page_url', '')} | Title: {debug.get('page_title', '')}"
                    )
                elif has_captcha_input:
                    reason = (
                        "CAPTCHA input exists but image did not render in headless Chrome. "
                        "Portal may be blocking captcha image requests from this server IP. "
                        "Use Option A or run locally."
                    )
                else:
                    reason = (
                        "GST login form loaded WITHOUT a CAPTCHA section "
                        "(confirmed via screenshot: username/password/LOGIN only). "
                        "This usually means the portal is not issuing captcha to this "
                        "cloud datacenter IP / headless browser. "
                        "Option B cannot complete login without captcha on this host. "
                        "Use Option A (Manual Upload) on Render, or run Option B locally on your laptop."
                    )

                return {
                    "success": False,
                    "error": reason,
                    "technical_error": (
                        f"strategy={final_strategy}; url={debug.get('page_url')}; "
                        f"title={debug.get('page_title')}; "
                        f"iframes={debug.get('iframe_count')}; imgs={debug.get('img_count')}; "
                        f"canvas={debug.get('canvas_count')}; inputs={debug.get('input_count')}; "
                        f"network_captcha_hits={len(network_captcha_bytes)}; "
                        f"has_captcha_input={has_captcha_input}"
                    ),
                    "debug_screenshot_b64": debug.get("debug_screenshot_b64", ""),
                    "html_snippet": debug.get("html_snippet", ""),
                    "page_url": debug.get("page_url", ""),
                    "page_title": debug.get("page_title", ""),
                    "captcha_missing_from_dom": True,
                }

            return {
                "success": True,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "captcha_b64": captcha_b64,
                "captcha_strategy": final_strategy,
            }

        except Exception as e:
            self._safe_close(browser, playwright)
            err = str(e)
            if (
                "Executable doesn't exist" in err
                or "chromium" in err.lower()
                or "browser" in err.lower()
            ):
                friendly = (
                    "Browser engine not available on this server. "
                    "Use Render Docker for GST Auto-Fetch, or Option A (Manual Upload)."
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
            pass_selectors = [
                "#user_pass",
                "input[name='user_pass']",
                "input[type='password']",
            ]
            captcha_selectors = [
                "#captcha",
                "input[name='captcha']",
                "input#captcha",
                "input[name='captcha_txt']",
            ]

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

            # Captcha field may be missing if portal never rendered it
            captcha_filled = fill_first(captcha_selectors, captcha_text.strip())
            if not captcha_filled:
                raise Exception(
                    "CAPTCHA input not found on page. "
                    "Portal did not render captcha for this session."
                )

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

            for sel in [
                ".err-msg",
                ".alert-danger",
                ".error",
                ".text-danger",
                "#error",
                ".alert",
            ]:
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

            page.goto(self.dashboard_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)

            cur = (page.url or "").lower()
            if "login" in cur and "auth" not in cur:
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

            for sel in [
                "#search",
                "button:has-text('Search')",
                "button:has-text('SEARCH')",
                "text=SEARCH",
            ]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=2500)
                        page.wait_for_timeout(2500)
                        break
                    except Exception:
                        continue

            save_name = (
                f"gstr2b_{re.sub(r'[^A-Za-z0-9_]+', '_', username)}_"
                f"{fy}_{str(period).replace(' ', '_')}.json"
            )
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