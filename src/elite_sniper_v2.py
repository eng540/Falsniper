"""
Elite Sniper v2.0 - FIXED VERSION (Back to V1 working logic)
"""

import time
import random
import datetime
import logging
import os
import sys
from typing import List, Tuple, Optional
from threading import Event, Lock

import pytz
from playwright.sync_api import sync_playwright, Page, Browser

# Internal imports
from .config import Config
from .ntp_sync import NTPTimeSync
from .session_state import SessionState, SessionStats
from .captcha import EnhancedCaptchaSolver
from .notifier import send_alert, send_success_notification
from .debug_utils import DebugManager

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('elite_sniper_v2_fixed.log')
    ]
)
logger = logging.getLogger("EliteSniperV2.Fixed")


class EliteSniperV2Fixed:
    """
    FIXED VERSION - Back to V1 working logic
    """
    
    VERSION = "2.0.1.FIXED"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Fixed Version"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER {self.VERSION} - FIXED VERSION")
        logger.info(f"[MODE] Running Mode: {self.run_mode}")
        logger.info("=" * 70)
        
        # Validate config
        self._validate_config()
        
        # Session
        self.session_id = f"fixed_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        # System state
        self.stop_event = Event()
        self.lock = Lock()
        
        # Components - IMPORTANT: Disable auto_full for manual fallback
        is_manual = (self.run_mode == "MANUAL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        
        # Force manual mode if AUTO_FULL (to allow Telegram fallback)
        if self.run_mode == "AUTO_FULL":
            logger.warning("[FIX] AUTO_FULL detected - Forcing manual fallback enabled")
            # We'll handle auto solving but keep manual fallback
        
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        
        # Configuration
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        # Statistics
        self.stats = SessionStats()
        
        # Start NTP
        self.ntp_sync.start_background_sync()
        
        logger.info(f"[ID] {self.session_id}")
        logger.info(f"[URL] {self.base_url[:60]}...")
        logger.info("[FIX] Using V1 working logic with manual fallback")
        logger.info("[OK] Initialization complete")
    
    def _validate_config(self):
        """Validate configuration"""
        required = [
            'TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 
            'EMAIL', 'PASSPORT', 'PHONE'
        ]
        
        missing = [field for field in required if not getattr(Config, field, None)]
        
        if missing:
            raise ValueError(f"[ERR] Missing config: {', '.join(missing)}")
        
        logger.info("[OK] Config validated")
    
    def _prepare_base_url(self, url: str) -> str:
        """Prepare base URL"""
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url
    
    def get_current_time_aden(self) -> datetime.datetime:
        """Get current Aden time"""
        corrected_utc = self.ntp_sync.get_corrected_time()
        return corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
    
    def is_attack_time(self) -> bool:
        """Check attack time"""
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def create_simple_context(self, browser: Browser) -> Tuple[Page, SessionState]:
        """Create simple context like V1"""
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Aden",
                ignore_https_errors=True
            )
            
            page = context.new_page()
            
            # Simple anti-detection like V1
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)
            
            # Timeouts like V1
            context.set_default_timeout(30000)
            context.set_default_navigation_timeout(40000)
            
            # Session state with relaxed limits
            session = SessionState(
                session_id=self.session_id,
                role=None,
                worker_id=1,
                max_age=300,  # 5 minutes like V1
                max_idle=60,
                max_failures=20,
                max_captcha_attempts=20
            )
            
            logger.info("[CTX] Simple context created (V1 style)")
            
            with self.lock:
                self.stats.rebirths += 1
            
            return page, session
            
        except Exception as e:
            logger.error(f"[ERR] Context creation failed: {e}")
            raise
    
    def solve_month_captcha_simple(self, page: Page, session: SessionState) -> bool:
        """
        SIMPLE CAPTCHA SOLVING LIKE V1
        No complex verification, just solve and submit
        """
        try:
            # Wait for captcha to appear
            time.sleep(2)
            
            # Check if captcha exists
            captcha_input = page.locator("input[name='captchaText']").first
            if not captcha_input.is_visible(timeout=3000):
                logger.info("[CAPTCHA] No captcha found, continuing...")
                return True
            
            logger.info("[CAPTCHA] Solving month captcha...")
            
            # Solve using solver (with manual Telegram fallback)
            success, code, status = self.solver.solve_from_page(
                page, "MONTH",
                session_age=session.age(),
                attempt=1,
                max_attempts=3,
                force_manual_fallback=False  # Let solver decide
            )
            
            if not success or not code:
                logger.warning(f"[CAPTCHA] Solve failed: {status}")
                return False
            
            logger.info(f"[CAPTCHA] Code: '{code}' - Filling...")
            
            # Fill captcha like V1
            captcha_input.fill("")
            captcha_input.type(code, delay=50)
            time.sleep(0.5)
            
            # V1 METHOD: Find submit button and click it
            submit_selectors = [
                "input[type='submit']",
                "button[type='submit']",
                "input[value='Submit']",
                "input[value='Weiter']",
                "button:has-text('Submit')",
                "button:has-text('Weiter')"
            ]
            
            submitted = False
            for selector in submit_selectors:
                try:
                    submit_btn = page.locator(selector).first
                    if submit_btn.is_visible(timeout=1000):
                        submit_btn.click()
                        logger.info(f"[CAPTCHA] Clicked submit: {selector}")
                        submitted = True
                        break
                except:
                    continue
            
            if not submitted:
                # Fallback: Press Enter on captcha field
                captcha_input.press("Enter")
                logger.info("[CAPTCHA] Pressed Enter as fallback")
            
            # Wait like V1 (3-5 seconds)
            time.sleep(4)
            
            # SIMPLE CHECK: Are we still on captcha page?
            current_url = page.url
            content = page.content().lower()
            
            if "captcha" in content and page.locator("input[name='captchaText']").is_visible():
                logger.warning("[CAPTCHA] Still on captcha page - code was wrong")
                return False
            
            logger.info("[CAPTCHA] Submission successful (V1 style)")
            return True
            
        except Exception as e:
            logger.error(f"[CAPTCHA] Error: {e}")
            return False
    
    def scan_month_simple(self, page: Page, url: str, session: SessionState) -> Optional[str]:
        """
        SIMPLE MONTH SCAN LIKE V1
        """
        try:
            logger.info(f"[SCAN] Loading: {url[:80]}...")
            
            # Navigate like V1
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            
            with self.lock:
                self.stats.pages_loaded += 1
            
            # Solve captcha if present
            if not self.solve_month_captcha_simple(page, session):
                logger.warning("[SCAN] Captcha failed, trying next month")
                return None
            
            # Check for no appointments
            content = page.content().lower()
            if "no appointments" in content or "keine termine" in content:
                logger.debug("[SCAN] No appointments")
                return None
            
            # Look for days (V1 selectors)
            day_selectors = [
                "a.arrow[href*='appointment_showDay']",
                "td.buchbar a",
                "a[href*='showDay']",
                "td.frei a"
            ]
            
            for selector in day_selectors:
                try:
                    day_links = page.locator(selector).all()
                    if day_links:
                        num_days = len(day_links)
                        logger.critical(f"[FOUND] {num_days} days available!")
                        
                        with self.lock:
                            self.stats.days_found += num_days
                        
                        # Get first day URL
                        first_href = day_links[0].get_attribute("href")
                        if first_href:
                            base_domain = self.base_url.split("/extern")[0]
                            return f"{base_domain}/{first_href}"
                except:
                    continue
            
            return None
            
        except Exception as e:
            logger.warning(f"[SCAN] Error: {e}")
            return None
    
    def scan_day_simple(self, page: Page, day_url: str, session: SessionState) -> Optional[str]:
        """
        SIMPLE DAY SCAN LIKE V1
        """
        try:
            logger.info(f"[DAY] Loading day page...")
            
            page.goto(day_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            
            # Look for time slots (V1 selectors)
            time_selectors = [
                "a.arrow[href*='appointment_showForm']",
                "a[href*='showForm']",
                "td.frei a"
            ]
            
            for selector in time_selectors:
                try:
                    time_links = page.locator(selector).all()
                    if time_links:
                        num_times = len(time_links)
                        logger.critical(f"[FOUND] {num_times} time slots!")
                        
                        with self.lock:
                            self.stats.slots_found += num_times
                        
                        # Get first time slot
                        first_href = time_links[0].get_attribute("href")
                        if first_href:
                            base_domain = self.base_url.split("/extern")[0]
                            return f"{base_domain}/{first_href}"
                except:
                    continue
            
            return None
            
        except Exception as e:
            logger.warning(f"[DAY] Error: {e}")
            return None
    
    def fill_form_simple(self, page: Page, session: SessionState) -> bool:
        """
        SIMPLE FORM FILL LIKE V1
        """
        try:
            logger.info("[FORM] Filling form...")
            
            # Wait for form
            time.sleep(2)
            
            # Check if form exists
            lastname_input = page.locator("input[name='lastname']").first
            if not lastname_input.is_visible():
                logger.warning("[FORM] Form not found")
                return False
            
            # Fill fields simply
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
                ("input[name='emailRepeat']", Config.EMAIL),
                ("input[name='fields[0].content']", Config.PASSPORT),
                ("input[name='fields[1].content']", Config.PHONE.replace("+", "00").strip())
            ]
            
            for selector, value in fields:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(value)
                        time.sleep(0.1)
                except:
                    continue
            
            # Category selection
            try:
                select_elem = page.locator("select").first
                if select_elem.is_visible():
                    select_elem.select_option(index=1)
                    time.sleep(0.5)
            except:
                pass
            
            with self.lock:
                self.stats.forms_filled += 1
            
            logger.info("[FORM] Form filled")
            return True
            
        except Exception as e:
            logger.error(f"[FORM] Error: {e}")
            return False
    
    def submit_form_simple(self, page: Page, session: SessionState) -> bool:
        """
        SIMPLE FORM SUBMIT LIKE V1
        """
        try:
            logger.info("[SUBMIT] Starting submission...")
            
            # Solve form captcha
            captcha_input = page.locator("input[name='captchaText']").first
            if not captcha_input.is_visible():
                logger.warning("[SUBMIT] No captcha found")
                return False
            
            success, code, status = self.solver.solve_from_page(
                page, "FORM",
                session_age=session.age(),
                attempt=1,
                max_attempts=3
            )
            
            if not success or not code:
                logger.warning(f"[SUBMIT] Captcha solve failed: {status}")
                return False
            
            logger.info(f"[SUBMIT] Code: '{code}' - Submitting...")
            
            # Fill and submit
            captcha_input.fill("")
            captcha_input.type(code, delay=50)
            time.sleep(0.5)
            
            # Look for submit button
            submit_selectors = [
                "input[type='submit'][value='Submit']",
                "input[type='submit'][value='submit']",
                "input[name='action:appointment_addAppointment']",
                "button[type='submit']"
            ]
            
            for selector in submit_selectors:
                try:
                    submit_btn = page.locator(selector).first
                    if submit_btn.is_visible(timeout=1000):
                        submit_btn.click()
                        logger.info(f"[SUBMIT] Clicked: {selector}")
                        break
                except:
                    continue
            
            # Wait for result
            time.sleep(5)
            
            # Check for success
            content = page.content().lower()
            success_indicators = [
                "appointment number",
                "termin wurde gebucht",
                "ihre buchung",
                "successfully",
                "confirmation",
                "vielen dank"
            ]
            
            for indicator in success_indicators:
                if indicator in content:
                    logger.critical(f"[SUCCESS] Found: '{indicator}'")
                    
                    # Save evidence
                    self.debug_manager.save_critical_screenshot(page, "SUCCESS", 1)
                    
                    with self.lock:
                        self.stats.success = True
                    
                    self.stop_event.set()
                    return True
            
            logger.warning("[SUBMIT] Submission failed")
            return False
            
        except Exception as e:
            logger.error(f"[SUBMIT] Error: {e}")
            return False
    
    def run_simple_flow(self, browser: Browser) -> bool:
        """
        SIMPLE FLOW LIKE V1
        Month → Day → Time → Form → Submit
        """
        logger.info("[FLOW] Starting simple flow (V1 style)")
        
        # Create context
        page, session = self.create_simple_context(browser)
        
        try:
            # Generate month URLs
            today = datetime.datetime.now().date()
            base_clean = self.base_url.split("&dateStr=")[0] if "&dateStr=" in self.base_url else self.base_url
            
            # Priority months
            priority_offsets = [2, 3, 1, 4, 5, 6]
            month_urls = []
            
            for offset in priority_offsets:
                future_date = today + datetime.timedelta(days=30 * offset)
                date_str = f"15.{future_date.month:02d}.{future_date.year}"
                month_urls.append(f"{base_clean}&dateStr={date_str}")
            
            cycle = 0
            max_cycles = 30
            
            while not self.stop_event.is_set() and cycle < max_cycles:
                cycle += 1
                logger.info(f"[CYCLE] {cycle}/{max_cycles}")
                
                for month_url in month_urls:
                    if self.stop_event.is_set():
                        break
                    
                    # 1. Scan month
                    day_url = self.scan_month_simple(page, month_url, session)
                    if not day_url:
                        continue
                    
                    # 2. Scan day
                    time_url = self.scan_day_simple(page, day_url, session)
                    if not time_url:
                        continue
                    
                    # 3. Go to form
                    logger.info("[FORM] Going to form...")
                    page.goto(time_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(3)
                    
                    # 4. Fill form
                    if not self.fill_form_simple(page, session):
                        continue
                    
                    # 5. Submit form
                    if self.submit_form_simple(page, session):
                        return True  # SUCCESS
                    
                    # If we reach here, something failed, try next month
                    break
                
                # Wait between cycles
                if not self.stop_event.is_set():
                    wait_time = 3 if self.is_attack_time() else 10
                    logger.info(f"[WAIT] {wait_time}s")
                    time.sleep(wait_time)
            
            logger.info("[FLOW] Max cycles reached")
            return False
            
        except Exception as e:
            logger.error(f"[FLOW] Error: {e}", exc_info=True)
            return False
            
        finally:
            try:
                page.context.close()
            except:
                pass
            logger.info("[FLOW] Session closed")
    
    def run(self) -> bool:
        """
        Main execution
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER {self.VERSION}] - SIMPLE FLOW")
        logger.info(f"[TIME] Attack: {Config.ATTACK_HOUR}:00 AM Aden")
        logger.info(f"[NOW] Current: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # Startup notification
            send_alert(
                f"[Elite Sniper {self.VERSION} Started]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Simple V1 Flow\n"
                f"Attack: {Config.ATTACK_HOUR}:00 AM Aden"
            )
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                logger.info("[BROWSER] Launched")
                
                try:
                    # Run simple flow
                    success = self.run_simple_flow(browser)
                except Exception as e:
                    logger.error(f"[ERROR] {e}")
                    success = False
                
                # Cleanup
                self.ntp_sync.stop_background_sync()
                browser.close()
                
                # Save stats
                final_stats = self.stats.to_dict()
                self.debug_manager.save_stats(final_stats, "final_stats.json")
                
                if success:
                    self._handle_success()
                    return True
                else:
                    self._handle_completion()
                    return False
                
        except KeyboardInterrupt:
            logger.info("\n[STOP] Manual stop")
            self.stop_event.set()
            self.ntp_sync.stop_background_sync()
            send_alert("⏸️ Elite Sniper stopped")
            return False
            
        except Exception as e:
            logger.error(f"💀 Critical: {e}", exc_info=True)
            send_alert(f"🚨 Critical: {str(e)[:200]}")
            return False
    
    def _handle_success(self):
        """Handle success"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] BOOKING SUCCESSFUL!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"ELITE SNIPER {self.VERSION} - SUCCESS!\n"
            f"[+] Appointment booked!\n"
            f"Session: {self.session_id}\n"
            f"Time: {runtime:.0f}s"
        )
    
    def _handle_completion(self):
        """Handle completion"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Completed without booking")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        logger.info(f"[TIME] Runtime: {runtime:.0f}s")


# Entry point
if __name__ == "__main__":
    sniper = EliteSniperV2Fixed()
    success = sniper.run()
    sys.exit(0 if success else 1)