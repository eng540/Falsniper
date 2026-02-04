"""
Elite Sniper v2.0 - Production-Grade State Machine Implementation
Philosophy: Calm Flow, No Premature Kill, Persistent Submission
"""

import time
import random
import datetime
import logging
import os
import sys
from enum import Enum, auto
from threading import Thread, Event, Lock
import pytz
from playwright.sync_api import sync_playwright, Page, Browser

# Internal imports
from .config import Config
from .ntp_sync import NTPTimeSync
from .captcha import EnhancedCaptchaSolver
from .notifier import send_alert, send_photo, send_success_notification, send_status_update
from .debug_utils import DebugManager

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(), logging.FileHandler('elite_sniper_v2.log')]
)
logger = logging.getLogger("EliteSniperV2")

# =========================
# States Definition
# =========================
class State(Enum):
    INIT = auto()
    MONTH_SCAN = auto()
    DAY_SELECT = auto()
    TIME_SELECT = auto()
    FORM_FILL = auto()
    FORM_SUBMIT = auto()
    SUCCESS = auto()
    FATAL_ERROR = auto()

class SilentFailure(Exception):
    pass

class EliteSniperV2:
    VERSION = "2.0.0"
    
    def __init__(self, run_mode: str = "AUTO"):
        self.run_mode = run_mode
        self._validate_config()
        self.session_id = f"elite_v2_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        self.stop_event = Event()
        self.slot_event = Event()
        self.target_url = None
        self.lock = Lock()
        
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full: self.solver.auto_full = True
            
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        self.proxies = self._load_proxies()
        self.ntp_sync.start_background_sync()
        
        # State Tracking
        self.current_state = State.INIT

    def _validate_config(self):
        required = ['TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 'EMAIL', 'PASSPORT', 'PHONE']
        missing = [field for field in required if not getattr(Config, field, None)]
        if missing: raise ValueError(f"Missing config: {', '.join(missing)}")

    def _prepare_base_url(self, url: str) -> str:
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url

    def _load_proxies(self) -> List[Optional[str]]:
        proxies = []
        if hasattr(Config, 'PROXIES') and Config.PROXIES:
            proxies.extend([p for p in Config.PROXIES if p])
        while len(proxies) < 3: proxies.append(None)
        return proxies[:3]

    def create_context(self, browser: Browser, worker_id: int, proxy: Optional[str] = None):
        user_agent = random.choice(self.user_agents)
        context_args = {
            "user_agent": user_agent,
            "viewport": {"width": 1366 + random.randint(0, 50), "height": 768 + random.randint(0, 30)},
            "locale": "en-US",
            "timezone_id": "Asia/Aden",
            "ignore_https_errors": True
        }
        if proxy: context_args["proxy"] = {"server": proxy}
        
        context = browser.new_context(**context_args)
        page = context.new_page()
        
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            setInterval(() => { fetch(location.href, { method: 'HEAD' }).catch(()=>{}); }, 8000);
        """)
        context.set_default_timeout(30000)
        return context, page

    # ==================== Core Logic (State Machine) ====================

    def handle_captcha_if_any(self, page: Page, location: str):
        """Safe captcha handler - doesn't kill session"""
        has_captcha, _ = self.solver.safe_captcha_check(page, location)
        if has_captcha:
            logger.info(f"[{location}] Captcha detected - Solving...")
            success, code, _ = self.solver.solve_from_page(page, location)
            if success and code:
                self.solver.submit_captcha(page, "auto")
                try: page.wait_for_load_state("domcontentloaded", timeout=5000)
                except: pass
                return True
            return False
        return True

    def run_session_flow(self, page: Page, worker_id: int):
        """
        The main state machine loop for a single session
        """
        self.current_state = State.INIT
        
        while not self.stop_event.is_set():
            try:
                # --- STATE: INIT ---
                if self.current_state == State.INIT:
                    # Start by scanning months
                    self.current_state = State.MONTH_SCAN
                
                # --- STATE: MONTH SCAN ---
                elif self.current_state == State.MONTH_SCAN:
                    month_urls = self.generate_month_urls()
                    found_day = False
                    
                    for url in month_urls:
                        if self.stop_event.is_set(): return
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=20000)
                            
                            # Handle Month Captcha (Gatekeeper)
                            if not self.handle_captcha_if_any(page, "MONTH"):
                                continue # Retry same or next month
                            
                            # Check for days
                            if "no appointments" in page.content().lower(): continue
                            
                            day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                            if day_links:
                                logger.critical(f"[W{worker_id}] 🔥 FOUND {len(day_links)} DAYS!")
                                # Click first day
                                day_links[0].click()
                                self.current_state = State.DAY_SELECT
                                found_day = True
                                break
                        except Exception as e:
                            logger.warning(f"Month scan error: {e}")
                    
                    if not found_day:
                        time.sleep(random.uniform(5, 10)) # Wait before rescanning
                
                # --- STATE: DAY SELECT ---
                elif self.current_state == State.DAY_SELECT:
                    # Handle Day Captcha
                    if not self.handle_captcha_if_any(page, "DAY"):
                        # If captcha fails here, we might be kicked back to month
                        if "appointment_showMonth" in page.url:
                            self.current_state = State.MONTH_SCAN
                        continue

                    # Look for time slots
                    time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    if time_links:
                        logger.critical(f"[W{worker_id}] ⏰ FOUND {len(time_links)} SLOTS!")
                        # Click first slot
                        time_links[0].click()
                        self.current_state = State.TIME_SELECT
                    else:
                        logger.warning("No slots on day page, going back")
                        self.current_state = State.MONTH_SCAN
                
                # --- STATE: TIME SELECT (Pre-Form) ---
                elif self.current_state == State.TIME_SELECT:
                    # Handle Pre-Form Captcha
                    if not self.handle_captcha_if_any(page, "PRE_FORM"):
                         if "appointment_showDay" in page.url:
                             self.current_state = State.DAY_SELECT
                         continue
                    
                    # Check if we reached form
                    if page.locator("input[name='lastname']").count() > 0:
                        logger.info(f"[W{worker_id}] 📝 REACHED FORM - POINT OF NO RETURN")
                        self.current_state = State.FORM_FILL
                    else:
                        # Slot taken or error
                        logger.warning("Failed to reach form, retrying...")
                        self.current_state = State.MONTH_SCAN

                # --- STATE: FORM FILL ---
                elif self.current_state == State.FORM_FILL:
                    # Fill the form (Human Mode)
                    if self._fill_booking_form(page, worker_id):
                        self.current_state = State.FORM_SUBMIT
                    else:
                        # If fill fails, try again (don't leave form)
                        time.sleep(1)
                
                # --- STATE: FORM SUBMIT (The Loop) ---
                elif self.current_state == State.FORM_SUBMIT:
                    try:
                        if self._submit_form_logic(page, worker_id):
                            self.current_state = State.SUCCESS
                        else:
                            # Silent failure -> Stay in SUBMIT state (Retry)
                            logger.warning(f"[W{worker_id}] 🔄 Silent failure - Retrying submit...")
                            time.sleep(1)
                            # Check if we were kicked out
                            if "appointment_showMonth" in page.url:
                                logger.error("Kicked out of form!")
                                self.current_state = State.MONTH_SCAN
                    except SilentFailure:
                        time.sleep(1)
                
                # --- STATE: SUCCESS ---
                elif self.current_state == State.SUCCESS:
                    logger.critical("🏆 MISSION ACCOMPLISHED!")
                    self.stop_event.set()
                    return

            except Exception as e:
                logger.error(f"[W{worker_id}] State Machine Error: {e}")
                # Safe fallback
                if self.current_state in [State.FORM_FILL, State.FORM_SUBMIT]:
                    # If error in form, try to stay in form
                    pass
                else:
                    self.current_state = State.MONTH_SCAN
                time.sleep(2)

    # ==================== Actions ====================

    def _fill_booking_form(self, page: Page, worker_id: int) -> bool:
        try:
            logger.info(f"[W{worker_id}] Filling form...")
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
                ("input[name='emailRepeat']", Config.EMAIL),
                ("input[name='fields[0].content']", Config.PASSPORT),
                ("input[name='fields[1].content']", Config.PHONE.replace("+", "00").strip())
            ]
            for sel, val in fields:
                if page.locator(sel).count() > 0:
                    page.fill(sel, val)
            
            # Category
            try:
                page.evaluate("document.querySelector('select').selectedIndex = 1; document.querySelector('select').dispatchEvent(new Event('change'));")
            except: pass
            
            return True
        except: return False

    def _submit_form_logic(self, page: Page, worker_id: int) -> bool:
        """
        Robust submit logic: Solve Captcha -> Enter -> Wait -> Check
        """
        # 1. Check/Solve Captcha
        if page.locator("input[name='captchaText']").is_visible():
            success, code, _ = self.solver.solve_from_page(page, "SUBMIT")
            if not success or not code:
                # Refresh captcha
                self.solver.reload_captcha(page)
                return False # Retry loop
            
            # Fill & Submit
            page.fill("input[name='captchaText']", code)
            time.sleep(0.3)
            
            # Press Enter and WAIT for navigation
            try:
                with page.expect_navigation(timeout=5000):
                    page.keyboard.press("Enter")
            except:
                pass # Timeout is fine, we check content next
        
        # 2. Check Result
        try:
            content = page.content().lower()
            if "appointment number" in content or "successfully" in content:
                self.debug_manager.save_critical_screenshot(page, "VICTORY", worker_id)
                send_success_notification(self.session_id, worker_id)
                return True
            
            if "error" in content or "session expired" in content:
                logger.error("Hard error on submit")
                # We might need to restart session here
                return False
                
            # If form is still visible, it's a silent failure
            if page.locator("input[name='lastname']").is_visible():
                raise SilentFailure()
                
        except SilentFailure:
            return False
            
        return False

    def generate_month_urls(self) -> List[str]:
        try:
            today = datetime.datetime.now().date()
            base_clean = self.base_url.split("&dateStr=")[0]
            urls = []
            priority_offsets = [2, 3, 1, 4, 5, 6]
            for offset in priority_offsets:
                future_date = today + datetime.timedelta(days=30 * offset)
                date_str = f"15.{future_date.month:02d}.{future_date.year}"
                urls.append(f"{base_clean}&dateStr={date_str}")
            return urls
        except: return []

    # ==================== Runner ====================

    def session_worker(self, browser: Browser, worker_id: int):
        try:
            proxy = self.proxies[worker_id - 1] if len(self.proxies) >= worker_id else None
            context, page = self.create_context(browser, worker_id, proxy)
            
            # Run the state machine
            self.run_session_flow(page, worker_id)
            
        except Exception as e:
            logger.error(f"[W{worker_id}] Worker crashed: {e}")
        finally:
            try: context.close()
            except: pass

    def run(self) -> bool:
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - STATE MACHINE MODE")
        
        try:
            send_alert(f"🚀 Elite Sniper V{self.VERSION} Started")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=Config.HEADLESS, args=Config.BROWSER_ARGS)
                
                threads = []
                for i in range(1, 4):
                    t = Thread(target=self.session_worker, args=(browser, i), daemon=True)
                    threads.append(t)
                    t.start()
                    time.sleep(2)
                
                try:
                    while not self.stop_event.is_set():
                        time.sleep(1)
                except KeyboardInterrupt:
                    self.stop_event.set()
                
                browser.close()
                return True
                
        except Exception as e:
            logger.error(f"Critical error: {e}")
            return False

if __name__ == "__main__":
    sniper = EliteSniperV2()
    sniper.run()