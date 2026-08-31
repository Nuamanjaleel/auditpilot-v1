# core/gst_portal.py
import os
import base64
import re
import sys
import uuid
import queue
import threading
import traceback
import time
from typing import Dict, Any, List, Optional, Tuple


def _ensure_windows_event_loop_policy():
    if sys.platform == "win32":
        import asyncio

        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass


def _log(msg: str):
    """Prints direct progress feedback to the PowerShell terminal."""
    sys.stdout.write(f"\n[AUDITPILOT-GST] {msg}\n")
    sys.stdout.flush()


def parse_period(period: str, fy: str = "") -> Dict[str, Any]:
    """
    Convert UI period like 'April 2024' + FY '2024-25' into portal-friendly values.
    Returns month name, year, mm, yyyy, fp (MMYYYY), fy variants, and quarter.
    """
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
        "oct": 10, "nov": 11, "dec": 12
    }
    month_names = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    p = (period or "").strip()
    parts = p.replace(",", " ").split()
    month_num = None
    year = None
    for token in parts:
        t = token.lower()
        if t in month_map:
            month_num = month_map[t]
        elif re.fullmatch(r"\d{4}", token):
            year = int(token)
        elif re.fullmatch(r"\d{1,2}", token) and month_num is None:
            n = int(token)
            if 1 <= n <= 12:
                month_num = n

    if year is None and fy:
        try:
            start = int(str(fy).split("-")[0])
            if month_num:
                year = start if month_num >= 4 else start + 1
        except Exception:
            year = None

    if month_num is None:
        month_num = 4
    if year is None:
        year = 2024

    mm = f"{month_num:02d}"
    yyyy = str(year)
    fp = f"{mm}{yyyy}"
    month_name = month_names[month_num]
    month_abbr = month_name[:3]

    if month_num in [4, 5, 6]:
        quarter_name = "Quarter 1"
        quarter_val = "1"
        quarter_abbr = "Q1"
    elif month_num in [7, 8, 9]:
        quarter_name = "Quarter 2"
        quarter_val = "2"
        quarter_abbr = "Q2"
    elif month_num in [10, 11, 12]:
        quarter_name = "Quarter 3"
        quarter_val = "3"
        quarter_abbr = "Q3"
    else:
        quarter_name = "Quarter 4"
        quarter_val = "4"
        quarter_abbr = "Q4"

    fy_variants = []
    if fy:
        fy_variants.append(str(fy).strip())
        m = re.match(r"^(\d{4})-(\d{2})$", str(fy).strip())
        if m:
            y1 = m.group(1)
            y2_full = str(int(y1) + 1)
            fy_variants.append(f"{y1}-{y2_full}")
            fy_variants.append(f"{y1}-{m.group(2)}")
            
    if month_num >= 4:
        derived = f"{year}-{str(year+1)[-2:]}"
        derived_full = f"{year}-{year+1}"
    else:
        derived = f"{year-1}-{str(year)[-2:]}"
        derived_full = f"{year-1}-{year}"
    for v in [derived, derived_full]:
        if v not in fy_variants:
            fy_variants.append(v)

    return {
        "month_num": month_num,
        "month_name": month_name,
        "month_abbr": month_abbr,
        "year": year,
        "mm": mm,
        "yyyy": yyyy,
        "fp": fp,
        "period_label": f"{month_name} {year}",
        "fy_variants": fy_variants,
        "quarter_name": quarter_name,
        "quarter_val": quarter_val,
        "quarter_abbr": quarter_abbr,
    }


class _PlaywrightWorker:
    def __init__(self):
        self._cmd_q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._thread_main, name="AuditPilotPlaywright", daemon=True
        )
        self._thread.start()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _thread_main(self):
        _ensure_windows_event_loop_policy()
        import asyncio

        # Clear any active event loop on this thread to allow Playwright Sync API
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass

        while True:
            item = self._cmd_q.get()
            if item is None:
                break
            fn, args, kwargs, result_q = item
            try:
                result_q.put(("ok", fn(*args, **kwargs)))
            except Exception as e:
                result_q.put(
                    (
                        "err",
                        {
                            "error": str(e).strip() or e.__class__.__name__,
                            "technical_error": traceback.format_exc(),
                        },
                    )
                )

    def _force_cleanup_all_sessions(self):
        _log("Cleaning up active browser sessions...")
        try:
            for s_id, session in list(self._sessions.items()):
                try:
                    browser = session.get("browser")
                    if browser:
                        browser.close()
                except Exception:
                    pass
                try:
                    playwright = session.get("playwright")
                    if playwright:
                        playwright.stop()
                except Exception:
                    pass
            self._sessions.clear()
        except Exception:
            pass

    def call(self, fn, *args, timeout: float = 120.0, **kwargs) -> Dict[str, Any]:
        result_q: queue.Queue = queue.Queue()
        self._cmd_q.put((fn, args, kwargs, result_q))
        try:
            status, payload = result_q.get(timeout=timeout)
        except queue.Empty:
            self._force_cleanup_all_sessions()
            return {
                "success": False,
                "error": "The GST Portal took too long to respond. Connection aborted to prevent system lock.",
                "technical_error": "worker_timeout",
            }
        if status == "ok":
            return payload
        return {
            "success": False,
            "error": f"Could not complete GST action. Details: {payload.get('error')}",
            "technical_error": payload.get("technical_error", ""),
        }


_WORKER = _PlaywrightWorker()


class GSTPortalAutomation:
    def __init__(self, download_dir: str = "output/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.login_url = "https://services.gst.gov.in/services/login"

    def _launch_browser(self, playwright):
        _log("Launching headless Chromium browser...")
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

    def _safe_close_session(self, session: Optional[Dict[str, Any]]):
        if not session:
            return
        _log("Closing browser session cleanly.")
        try:
            browser = session.get("browser")
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            playwright = session.get("playwright")
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
            "clickables": [],
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
            payload["html_snippet"] = (page.content() or "")[:8000]
        except Exception:
            pass
        try:
            labels = []
            locs = page.locator("button, a, [role='button'], select, option")
            n = min(locs.count(), 100)
            for i in range(n):
                el = locs.nth(i)
                try:
                    t = " ".join((el.inner_text(timeout=100) or "").split())
                    if t and len(t) < 120:
                        low = t.lower()
                        if any(k in low for k in ["gstr", "2b", "download", "json", "pdf", "search", "return"]):
                            labels.append(t)
                except Exception:
                    continue
            payload["clickables"] = labels[:40]
        except Exception:
            pass
        try:
            shot = page.screenshot(full_page=True)
            payload["debug_screenshot_b64"] = base64.b64encode(shot).decode("utf-8")
            path = os.path.join(self.download_dir, "gst_post_login_debug.png")
            with open(path, "wb") as f:
                f.write(shot)
            _log(f"Saved debug screenshot: {path}")
        except Exception:
            pass
        return payload

    def _find_captcha_element(self, page) -> Tuple[Optional[Any], str]:
        selectors = [
            "#imgCaptcha", "img#imgCaptcha", "#captchaImg", "img#captchaImg",
            "img#captcha", "img.captcha", "img[alt*='Captcha' i]", "img[src*='captcha' i]"
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    return loc.first, sel
            except Exception:
                continue
        return None, "none"

    def _fill_first(self, page, selectors: List[str], value: str) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill("")
                    loc.first.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _click_first(self, page, selectors: List[str], wait_ms: int = 1200) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                _log(f"Clicking control: '{sel}'")
                loc.first.click(timeout=3000)
                page.wait_for_timeout(wait_ms)
                return True
            except Exception:
                continue
        return False

    def _select_by_keywords(self, select_loc, keywords: List[str]) -> bool:
        keys = [k.lower() for k in keywords if k]
        try:
            for k in keywords:
                try:
                    select_loc.select_option(value=k)
                    return True
                except Exception:
                    pass
                try:
                    select_loc.select_option(label=k)
                    return True
                except Exception:
                    pass

            opts = select_loc.locator("option")
            n = opts.count()
            for i in range(n):
                opt = opts.nth(i)
                try:
                    text = (opt.inner_text() or "").strip()
                    val = (opt.get_attribute("value") or "").strip()
                    blob = f"{text} {val}".lower()
                    if any(k in blob for k in keys):
                        try:
                            select_loc.select_option(index=i)
                            return True
                        except Exception:
                            try:
                                select_loc.select_option(value=val)
                                return True
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _apply_fy_period_on_page(self, page, meta: Dict[str, Any]) -> Dict[str, bool]:
        result = {"fy": False, "quarter": False, "period": False, "search": False}
        _log(f"Selecting FY {meta['fy_variants'][0]}, Quarter {meta['quarter_abbr']}, Month {meta['period_label']}")

        fy_keywords = meta["fy_variants"] + [meta["fy_variants"][0] if meta["fy_variants"] else ""]
        quarter_keywords = [meta["quarter_name"], meta["quarter_abbr"], meta["quarter_val"]]
        period_keywords = [
            meta["fp"], f"{meta['mm']}-{meta['yyyy']}", f"{meta['month_name']} {meta['yyyy']}",
            f"{meta['month_abbr']} {meta['yyyy']}", meta["month_name"], meta["month_abbr"], meta["mm"]
        ]

        for sel in ["#fin", "select[name='fin']", "#fy", "select[name='fy']", "select[id*='fin' i]"]:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                if self._select_by_keywords(loc.first, fy_keywords):
                    _log(f"Selected FY via '{sel}'")
                    result["fy"] = True
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue

        for sel in ["#quarter", "select[name='quarter']", "#quarterlyPeriod", "select[id*='quarter' i]"]:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                if self._select_by_keywords(loc.first, quarter_keywords):
                    _log(f"Selected Quarter via '{sel}'")
                    result["quarter"] = True
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue

        for sel in ["#mon", "select[name='mon']", "#month", "#rtnPeriod", "select[name='rtnPeriod']", "select[id*='mon' i]"]:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                if self._select_by_keywords(loc.first, period_keywords):
                    _log(f"Selected Period via '{sel}'")
                    result["period"] = True
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue

        if self._click_first(
            page,
            [
                "#search", "button:has-text('SEARCH')", "button:has-text('Search')",
                "button:has-text('GO')", "button:has-text('PROCEED')", "input[value='SEARCH']"
            ],
            wait_ms=2000,
        ):
            _log("Triggered Search.")
            result["search"] = True

        return result

    def _check_for_portal_alerts(self, page) -> Tuple[bool, str]:
        alert_selectors = [
            ".modal-content", ".modal-body", "div[role='dialog']",
            ".alert-danger", "#disclaimer", ".err-msg", "div.alert"
        ]
        negative_keywords = [
            "not generated", "no records", "not available", "no data found",
            "does not exist", "is in progress", "please try again later",
            "error in generating", "not filed", "no transactions", "not applicable"
        ]
        for sel in alert_selectors:
            try:
                loc = page.locator(sel)
                n = loc.count()
                for i in range(n):
                    el = loc.nth(i)
                    if el.is_visible():
                        txt = (el.inner_text() or "").strip()
                        low = txt.lower()
                        if any(k in low for k in negative_keywords):
                            _log(f"GST Portal Warning modal found: '{txt}'")
                            try:
                                close_btn = el.locator("button:has-text('OK'), button:has-text('Ok'), button:has-text('Close'), .close")
                                if close_btn.count() > 0:
                                    close_btn.first.click(timeout=800)
                            except Exception:
                                pass
                            return True, txt
            except Exception:
                continue
        return False, ""

    def _find_gstr2b_entry_control(self, page):
        try:
            t = page.get_by_text(re.compile(r"GSTR\s*-?\s*2B", re.I))
            if t.count() > 0:
                for i in range(min(t.count(), 5)):
                    node = t.nth(i)
                    try:
                        if node.is_visible():
                            return node
                    except Exception:
                        continue
        except Exception:
            pass
        for sel in [
            "a:has-text('GSTR-2B')", "button:has-text('GSTR-2B')", "text=GSTR-2B",
            "a[href*='gstr2b' i]", "a[href*='GSTR2B']"
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        return None

    def _is_pdfish(self, text: str) -> bool:
        t = (text or "").lower()
        return "pdf" in t and "json" not in t

    def _is_jsonish(self, text: str) -> bool:
        t = (text or "").lower()
        if "pdf" in t and "json" not in t:
            return False
        return any(k in t for k in ["json", "generate json", "download json", ".json"])

    def _open_download_menus(self, page) -> None:
        menu_selectors = [
            "button:has-text('DOWNLOAD')", "a:has-text('DOWNLOAD')",
            "button:has-text('Download')", "a:has-text('Download')",
            "[title*='Download' i]", "span:has-text('Download')"
        ]
        for sel in menu_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                for i in range(min(loc.count(), 3)):
                    el = loc.nth(i)
                    try:
                        txt = " ".join([
                            el.inner_text(timeout=100) or "",
                            el.get_attribute("title") or "",
                            el.get_attribute("aria-label") or "",
                        ]).lower()
                        if self._is_pdfish(txt):
                            continue
                        el.click(timeout=1200)
                        page.wait_for_timeout(300)
                    except Exception:
                        continue
            except Exception:
                continue

    def _collect_candidate_controls(self, page) -> List[Tuple[str, Any]]:
        candidates: List[Tuple[str, Any]] = []
        seen = set()
        for sel in ["button", "a", "[role='button']", "span"]:
            try:
                loc = page.locator(sel)
                n = min(loc.count(), 30)
                for i in range(n):
                    el = loc.nth(i)
                    try:
                        t = " ".join((el.inner_text(timeout=100) or "").split())
                        title = el.get_attribute("title") or ""
                        aria = el.get_attribute("aria-label") or ""
                        label = " ".join([t, title, aria]).strip()
                        key = label.lower()[:150]
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        if not any(k in key for k in ["download", "json", "generate", "export", "pdf"]):
                            continue
                        candidates.append((label, el))
                    except Exception:
                        continue
            except Exception:
                continue

        def score(item):
            low = item[0].lower()
            s = 0
            if "json" in low:
                s += 50
            if "download" in low and "json" in low:
                s += 40
            if "generate" in low and "json" in low:
                s += 35
            if "download" in low:
                s += 10
            if "pdf" in low and "json" not in low:
                s -= 100
            return s

        candidates.sort(key=score, reverse=True)
        return candidates

    def _save_download(self, download, save_path: str) -> bool:
        try:
            download.save_as(save_path)
            if not os.path.exists(save_path) or os.path.getsize(save_path) < 10:
                return False
            with open(save_path, "rb") as f:
                head = f.read(8)
            if head.startswith(b"%PDF"):
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                return False
            return True
        except Exception:
            return False

    def _try_download_from_click(self, page, control, save_path: str, timeout_ms: int = 3500) -> bool:
        try:
            with page.expect_download(timeout=timeout_ms) as di:
                control.click(timeout=2000)
            return self._save_download(di.value, save_path)
        except Exception:
            return False

    def _install_network_sniffer(self, page) -> Dict[str, Any]:
        bucket = {"bodies": []}

        def on_response(response):
            try:
                url = response.url or ""
                ul = url.lower()
                ctype = (response.headers.get("content-type") or "").lower()
                if response.status not in (200, 201):
                    return
                if "pdf" in ctype or ul.endswith(".pdf"):
                    return
                score = 0
                if "gstr2b" in ul or "gstr-2b" in ul:
                    score += 30
                if any(k in ul for k in ["json", "download", "generate"]):
                    score += 20
                if "application/json" in ctype:
                    score += 40
                if "zip" in ctype or "octet-stream" in ctype:
                    score += 25
                if score < 20:
                    return
                body = response.body()
                if not body or len(body) < 30 or body.startswith(b"%PDF"):
                    return
                if body[:1] in (b"{", b"[") or body[:3] == b"\xef\xbb\xbf":
                    score += 50
                if body[:2] == b"PK":
                    score += 40
                bucket["bodies"].append((score, body, url))
            except Exception:
                pass

        page.on("response", on_response)
        return bucket

    def _pick_best_body(self, bucket: Dict[str, Any]) -> Optional[bytes]:
        bodies = bucket.get("bodies") or []
        if not bodies:
            return None
        bodies.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
        return bodies[0][1]

    def _write_bytes(self, save_path: str, body: bytes) -> bool:
        if not body or body.startswith(b"%PDF"):
            return False
        with open(save_path, "wb") as f:
            f.write(body)
        return os.path.getsize(save_path) >= 30

    def _download_json_from_summary_page(self, page, save_path: str, start_time: float) -> Tuple[bool, List[str]]:
        attempts: List[str] = []
        sniffer = self._install_network_sniffer(page)
        page.wait_for_timeout(1000)

        has_alert, alert_txt = self._check_for_portal_alerts(page)
        if has_alert:
            attempts.append(f"portal_alert_detected: {alert_txt}")
            raise Exception(f"GST Portal Alert: {alert_txt}")

        attempts.append("open_download_menus")
        self._open_download_menus(page)
        page.wait_for_timeout(400)

        candidates = self._collect_candidate_controls(page)
        _log(f"Found {len(candidates)} candidate download controls.")
        attempts.append(f"candidates={len(candidates)}")

        ordered = []
        for label, el in candidates:
            if self._is_jsonish(label):
                ordered.append((label, el, "jsonish"))
        for label, el in candidates:
            low = label.lower()
            if self._is_pdfish(label):
                continue
            if "download" in low or "generate" in low or "export" in low:
                if not any(el == o_el for _, o_el, _ in ordered):
                    ordered.append((label, el, "downloadish"))

        for label, el, kind in ordered[:5]:
            if time.time() - start_time > 85.0:
                raise TimeoutError("Time budget exceeded in download loop.")

            _log(f"Clicking download element: '{label[:40]}'")
            attempts.append(f"click_{kind}:{label[:30]}")
            ok = self._try_download_from_click(page, el, save_path, timeout_ms=3000)
            if ok:
                _log("JSON downloaded successfully via download event.")
                attempts.append("download_event_success")
                return True, attempts

            body = self._pick_best_body(sniffer)
            if body and self._write_bytes(save_path, body):
                _log("JSON captured via network traffic.")
                attempts.append("network_body_after_click_success")
                return True, attempts

            has_alert, alert_txt = self._check_for_portal_alerts(page)
            if has_alert:
                attempts.append(f"alert_after_click: {alert_txt}")
                raise Exception(f"GST Portal Alert: {alert_txt}")

        for pat in [r"DOWNLOAD\s*JSON", r"Download\s*JSON", r"GENERATE\s*JSON"]:
            if time.time() - start_time > 85.0:
                raise TimeoutError("Time budget exceeded in regex download search.")

            attempts.append(f"get_by_text:{pat}")
            try:
                loc = page.get_by_text(re.compile(pat, re.I))
                if loc.count() == 0:
                    continue
                for i in range(min(loc.count(), 2)):
                    el = loc.nth(i)
                    try:
                        txt = (el.inner_text(timeout=100) or "").lower()
                    except Exception:
                        txt = ""
                    if self._is_pdfish(txt):
                        continue
                    ok = self._try_download_from_click(page, el, save_path, timeout_ms=3000)
                    if ok:
                        _log("JSON downloaded via fallback regex click.")
                        return True, attempts + ["get_by_text_download_success"]
                    body = self._pick_best_body(sniffer)
                    if body and self._write_bytes(save_path, body):
                        _log("JSON captured via fallback network body.")
                        return True, attempts + ["get_by_text_network_success"]

                    has_alert, alert_txt = self._check_for_portal_alerts(page)
                    if has_alert:
                        raise Exception(f"GST Portal Alert: {alert_txt}")
            except Exception as ex:
                if "GST Portal Alert" in str(ex):
                    raise
                attempts.append(f"get_by_text_err:{ex}")

        body = self._pick_best_body(sniffer)
        if body and self._write_bytes(save_path, body):
            return True, attempts + ["final_network_success"]

        return False, attempts

    def _worker_fetch_login_captcha(self, username: str = "") -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

        playwright = None
        browser = None
        session_id = str(uuid.uuid4())
        _log("Initiating CAPTCHA fetch cycle on dedicated worker.")

        try:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(35000)

            _log(f"Navigating to login page: {self.login_url}")
            try:
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                pass
            
            page.wait_for_timeout(2000)

            for sel in ["#username", "input[name='username']", "input#username"]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        if username:
                            loc.first.fill(username)
                        break
                except Exception:
                    continue

            page.wait_for_timeout(600)

            captcha_el, strategy = self._find_captcha_element(page)
            if captcha_el is None:
                for i in range(5):
                    page.wait_for_timeout(1000)
                    captcha_el, strategy = self._find_captcha_element(page)
                    if captcha_el is not None:
                        break

            if captcha_el is None:
                debug = self._page_debug_payload(page)
                self._safe_close_session({"browser": browser, "playwright": playwright})
                return {
                    "success": False,
                    "error": "CAPTCHA graphic not found on GST Portal.",
                    "technical_error": f"strategy={strategy}",
                    "debug_screenshot_b64": debug.get("debug_screenshot_b64", ""),
                    "page_url": debug.get("page_url", ""),
                }

            _log(f"CAPTCHA found via '{strategy}'. Capturing base64 image.")
            captcha_b64 = base64.b64encode(captcha_el.screenshot()).decode("utf-8")

            _WORKER._sessions[session_id] = {
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            _log("CAPTCHA loaded successfully.")
            return {
                "success": True,
                "session_id": session_id,
                "captcha_b64": captcha_b64,
                "captcha_strategy": strategy,
            }
        except Exception as e:
            _log(f"Error in fetch_login_captcha: {e}")
            self._safe_close_session({"browser": browser, "playwright": playwright})
            return {
                "success": False,
                "error": f"Could not connect to GST Portal: {e}",
                "technical_error": traceback.format_exc(),
            }

    def _worker_login_and_download(
        self,
        session_id: str,
        username: str,
        password: str,
        captcha_text: str,
        fy: str,
        period: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        _log("Initiating login and GSTR-2B download...")

        def check_timeout(stage_name: str):
            elapsed = time.time() - start_time
            _log(f"Stage: '{stage_name}' (Elapsed: {elapsed:.1f}s)")
            if elapsed > 90.0:
                raise TimeoutError(f"Budget exceeded (90s limit) during stage: {stage_name}")

        session = _WORKER._sessions.pop(session_id, None)
        if not session:
            return {"success": False, "error": "Session expired. Click Load CAPTCHA again."}

        page = session["page"]
        browser = session.get("browser")
        meta = parse_period(period, fy)

        try:
            check_timeout("fill_credentials")
            if not self._fill_first(page, ["#username", "input[name='username']"], username):
                raise Exception("Username field not found.")
            if not self._fill_first(page, ["#user_pass", "input[name='user_pass']", "input[type='password']"], password):
                raise Exception("Password field not found.")
            if not self._fill_first(page, ["#captcha", "input[name='captcha']", "input#captcha"], captcha_text.strip()):
                raise Exception("CAPTCHA input field not found.")

            check_timeout("submit_login")
            if not self._click_first(
                page,
                ["button[type='submit']", "button:has-text('LOGIN')", "input[type='submit']"],
                wait_ms=2000
            ):
                page.keyboard.press("Enter")

            page.wait_for_timeout(2500)
            check_timeout("check_login_error")

            for err_sel in [".err-msg", ".alert-danger", "#error", ".text-danger"]:
                try:
                    loc = page.locator(err_sel)
                    if loc.count() > 0:
                        txt = loc.first.inner_text().strip()
                        low = (txt or "").lower()
                        if txt and any(k in low for k in ["invalid", "captcha", "password", "incorrect", "not match"]):
                            _log(f"Login rejected by portal: '{txt}'")
                            raise Exception(f"GST Portal Response: {txt}")
                except Exception as ex:
                    if "GST Portal Response" in str(ex):
                        raise

            self._click_first(
                page,
                ["button:has-text('Remind Me Later')", "button:has-text('CLOSE')", "button:has-text('OK')", ".close"],
                wait_ms=400
            )

            check_timeout("nav_return_dashboard")
            clicked_ret = self._click_first(
                page,
                [
                    "button:has-text('RETURN DASHBOARD')", "a:has-text('RETURN DASHBOARD')",
                    "button:has-text('Return Dashboard')", "text=RETURN DASHBOARD"
                ],
                wait_ms=2500
            )
            if not clicked_ret or "return" not in (page.url or "").lower():
                _log("Direct click failed. Redirecting to dashboard URL...")
                try:
                    page.goto(
                        "https://return.gst.gov.in/returns/auth/dashboard",
                        wait_until="domcontentloaded",
                        timeout=25000,
                    )
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

            check_timeout("apply_filters_dashboard")
            sel1 = self._apply_fy_period_on_page(page, meta)
            page.wait_for_timeout(1000)

            has_alert, alert_txt = self._check_for_portal_alerts(page)
            if has_alert:
                raise Exception(f"GST Portal Alert: {alert_txt}")

            save_name = (
                f"gstr2b_{re.sub(r'[^A-Za-z0-9_]+', '_', username)}_"
                f"{meta['fp']}_{meta['fy_variants'][0].replace('-', '')}.json"
            )
            save_path = os.path.join(self.download_dir, save_name)
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except Exception:
                    pass

            check_timeout("open_gstr2b_tile")
            if "gstr2b.gst.gov.in" not in (page.url or "").lower():
                entry = self._find_gstr2b_entry_control(page)
                if entry is None:
                    self._apply_fy_period_on_page(page, meta)
                    page.wait_for_timeout(1000)
                    entry = self._find_gstr2b_entry_control(page)

                if entry is None:
                    has_alert, alert_txt = self._check_for_portal_alerts(page)
                    if has_alert:
                        raise Exception(f"GST Portal Alert: {alert_txt}")
                    
                    debug = self._page_debug_payload(page)
                    raise Exception(
                        f"GSTR-2B tile is not available on the portal for "
                        f"{meta['period_label']} / FY {meta['fy_variants'][0]}."
                    )
                _log("Clicking GSTR-2B entry tile...")
                try:
                    entry.click(timeout=3000)
                except Exception:
                    entry.evaluate("el => el.click()")
                page.wait_for_timeout(2000)

            for _ in range(8):
                if "gstr2b.gst.gov.in" in (page.url or "").lower():
                    break
                page.wait_for_timeout(300)

            self._click_first(
                page,
                ["button:has-text('OK')", "button:has-text('Ok')", "button:has-text('PROCEED')"],
                wait_ms=400
            )

            check_timeout("apply_filters_gstr2b_module")
            sel2 = self._apply_fy_period_on_page(page, meta)
            page.wait_for_timeout(1000)

            has_alert, alert_txt = self._check_for_portal_alerts(page)
            if has_alert:
                raise Exception(f"GST Portal Alert: {alert_txt}")

            check_timeout("download_json_file")
            ok, attempts = self._download_json_from_summary_page(page, save_path, start_time)

            if not ok:
                check_timeout("retry_download")
                self._apply_fy_period_on_page(page, meta)
                page.wait_for_timeout(1000)
                ok, attempts2 = self._download_json_from_summary_page(page, save_path, start_time)
                attempts = attempts + ["retry"] + attempts2

            if not ok:
                debug = self._page_debug_payload(page)
                raise Exception(
                    f"GSTR-2B section opened, but JSON could not be retrieved. "
                    f"Attempts: {attempts}. URL={debug.get('page_url')}"
                )

            with open(save_path, "rb") as f:
                head = f.read(8)
            if head.startswith(b"%PDF"):
                raise Exception("Portal served a PDF summary instead of GSTR-2B JSON.")

            _log("GSTR-2B JSON captured successfully!")
            self._safe_close_session(session)
            return {
                "success": True,
                "file_path": save_path,
                "period_meta": meta,
                "attempts": attempts,
            }

        except Exception as e:
            _log(f"Exception during login_and_download: {e}")
            try:
                if page:
                    self._page_debug_payload(page)
            except Exception:
                pass
            self._safe_close_session(session)
            return {
                "success": False,
                "error": str(e).strip() or e.__class__.__name__,
                "technical_error": traceback.format_exc(),
            }

    def fetch_login_captcha(self, username: str = "") -> Dict[str, Any]:
        return _WORKER.call(self._worker_fetch_login_captcha, username, timeout=60.0)

    def login_and_download_gstr2b(
        self,
        session: Dict[str, Any],
        username: str,
        password: str,
        captcha_text: str,
        fy: str,
        period: str,
    ) -> Dict[str, Any]:
        session_id = session.get("session_id") if isinstance(session, dict) else ""
        if not session_id:
            return {"success": False, "error": "Session expired. Click Load CAPTCHA again."}
        return _WORKER.call(
            self._worker_login_and_download,
            session_id,
            username,
            password,
            captcha_text,
            fy,
            period,
            timeout=110.0,
        )