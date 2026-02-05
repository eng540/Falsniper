"""
Elite Sniper v2.0 - Production-Grade Multi-Session Appointment Booking System

Integrates best features from:
- Elite Sniper: Multi-session architecture, Scout/Attacker pattern, Scheduled activation
- KingSniperV12: State Machine, Soft Recovery, Safe Captcha Check, Debug utilities

Architecture:
- 3 Parallel Sessions (1 Scout + 2 Attackers)
- 24/7 Operation with 2:00 AM Aden time activation
- Intelligent session lifecycle management
- Production-grade error handling and recovery

Version: 2.0.0
"""

import time
import random
import datetime
import logging
import os
import sys
from typing import List, Tuple, Optional
from threading import Thread, Event, Lock

import pytz
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

# Internal imports
from .config import Config
from .ntp_sync import NTPTimeSync
from .session_state import SessionState, SessionStats, SessionHealth, SessionRole
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
        logging.FileHandler('elite_sniper_v2.log')
    ]
)
logger = logging.getLogger("EliteSniperV2")


class EliteSniperV2:
    """
    Production-Grade Multi-Session Appointment Booking System
    """
    
    VERSION = "2.0.0"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Elite Sniper v2.0"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER V{self.VERSION} - INITIALIZING")
        logger.info(f"[MODE] Running Mode: {self.run_mode}")
        logger.info("=" * 70)
        
        # Validate configuration
        self._validate_config()
        
        # Session management
        self.session_id = f"elite_v2_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        # System state
        self.stop_event = Event()      # Global kill switch
        self.slot_event = Event()      # Scout → Attacker signal
        self.target_url: Optional[str] = None  # Discovered appointment URL
        self.lock = Lock()              # Thread-safe coordination
        
        # Components
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full:
            logger.info("[MODE] AUTO FULL ENABLED (No Manual Fallback)")
            self.solver.auto_full = True
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        
        # Configuration
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        # User agents for rotation
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        
        # Proxies (optional)
        self.proxies = self._load_proxies()
        
        # Global statistics
        self.global_stats = SessionStats()
        
        # Start background NTP sync
        self.ntp_sync.start_background_sync()
        
        logger.info(f"[ID] Session ID: {self.session_id}")
        logger.info(f"[URL] Base URL: {self.base_url[:60]}...")
        logger.info(f"[TZ] Timezone: {self.timezone}")
        logger.info(f"[NTP] NTP Offset: {self.ntp_sync.offset:.4f}s")
        logger.info(f"[DIR] Evidence Dir: {self.debug_manager.session_dir}")
        logger.info(f"[PROXY] Proxies: {len([p for p in self.proxies if p])} configured")
        logger.info(f"[OK] Initialization complete")
    
    # ==================== Configuration ====================
    
    def _validate_config(self):
        """Validate required configuration"""
        required = [
            'TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 
            'EMAIL', 'PASSPORT', 'PHONE'
        ]
        
        missing = [field for field in required if not getattr(Config, field, None)]
        
        if missing:
            raise ValueError(f"[ERR] Missing configuration: {', '.join(missing)}")
        
        logger.info("[OK] Configuration validated")
    
    def _prepare_base_url(self, url: str) -> str:
        """Prepare base URL with locale"""
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url
    
    def _load_proxies(self) -> List[Optional[str]]:
        """Load proxies from config or file"""
        proxies = []
        
        # From Config.PROXIES
        if hasattr(Config, 'PROXIES') and Config.PROXIES:
            proxies.extend([p for p in Config.PROXIES if p])
        
        # From proxies.txt
        try:
            if os.path.exists("proxies.txt"):
                with open("proxies.txt") as f:
                    file_proxies = [line.strip() for line in f if line.strip()]
                    proxies.extend(file_proxies)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load proxies.txt: {e}")
        
        # Ensure we have at least 3 slots (None = direct connection)
        while len(proxies) < 3:
            proxies.append(None)
        
        return proxies[:3]  # Only use first 3
    
    # ==================== Time Management ====================
    
    def get_current_time_aden(self) -> datetime.datetime:
        """Get current time in Aden timezone with NTP correction"""
        corrected_utc = self.ntp_sync.get_corrected_time()
        aden_time = corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        return aden_time
    
    def is_attack_time(self) -> bool:
        """Check if in attack window (2:00:00 - 2:02:00 Aden time)"""
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def get_sleep_interval(self) -> float:
        """Calculate dynamic sleep interval"""
        if self.is_attack_time():
            return random.uniform(0.1, 0.3)
        return random.uniform(2.0, 5.0)
    
    # ==================== Session Management ====================
    
    def create_context(
        self, 
        browser: Browser, 
        worker_id: int,
        proxy: Optional[str] = None
    ) -> Tuple[BrowserContext, Page, SessionState]:
        """
        Create browser context with session state
        """
        try:
            # Determine role
            role = SessionRole.SCOUT if worker_id == 1 else SessionRole.ATTACKER
            
            # Select user agent
            user_agent = random.choice(self.user_agents)
            
            # Context arguments
            context_args = {
                "user_agent": user_agent,
                "viewport": {"width": 1366, "height": 768},
                "locale": "en-US",
                "timezone_id": "Asia/Aden",
                "ignore_https_errors": True
            }
            
            # Add proxy if provided
            if proxy:
                context_args["proxy"] = {"server": proxy}
                logger.info(f"[PROXY] [W{worker_id}] Using proxy: {proxy[:30]}...")
            
            # Create context
            context = browser.new_context(**context_args)
            page = context.new_page()
            
            # Anti-detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { 
                    get: () => undefined 
                });
            """)
            
            # Timeouts
            context.set_default_timeout(30000)
            context.set_default_navigation_timeout(40000)
            
            # Create session state
            session_state = SessionState(
                session_id=f"{self.session_id}_w{worker_id}",
                role=role,
                worker_id=worker_id,
                max_age=300,  # 5 minutes
                max_idle=60,
                max_failures=10,
                max_captcha_attempts=10
            )
            
            logger.info(f"[CTX] [W{worker_id}] Context created - Role: {role.value}")
            
            with self.lock:
                self.global_stats.rebirths += 1
            
            return context, page, session_state
            
        except Exception as e:
            logger.error(f"[ERR] [W{worker_id}] Context creation failed: {e}")
            raise
    
    def validate_session_health(
        self, 
        page: Page, 
        session: SessionState, 
        location: str = "UNKNOWN"
    ) -> bool:
        """
        Validate session health
        """
        worker_id = session.worker_id
        
        # Check if session expired
        if session.is_expired():
            age = session.age()
            idle = session.idle_time()
            logger.warning(
                f"[EXP] [W{worker_id}][{location}] "
                f"Session expired - Age: {age:.1f}s, Idle: {idle:.1f}s"
            )
            return False
        
        # Check if too many failures
        if session.should_terminate():
            logger.warning(
                f"⚠️ [W{worker_id}][{location}] "
                f"Too many failures: {session.failures}"
            )
            return False
        
        # Session is healthy
        session.touch()
        return True
    
    # ==================== Navigation ====================
    
    def generate_month_urls(self) -> List[str]:
        """Generate priority month URLs"""
        try:
            today = datetime.datetime.now().date()
            base_clean = self.base_url.split("&dateStr=")[0] if "&dateStr=" in self.base_url else self.base_url
            
            urls = []
            # Priority: 2, 3, 1, 4, 5, 6 months ahead
            priority_offsets = [2, 3, 1, 4, 5, 6]
            
            for offset in priority_offsets:
                future_date = today + datetime.timedelta(days=30 * offset)
                date_str = f"15.{future_date.month:02d}.{future_date.year}"
                url = f"{base_clean}&dateStr={date_str}"
                urls.append(url)
            
            return urls
            
        except Exception as e:
            logger.error(f"❌ Month URL generation failed: {e}")
            return []
    
    def fast_inject(self, page: Page, selector: str, value: str) -> bool:
        """
        Inject value into form field
        """
        try:
            locator = page.locator(selector)
            if locator.count() == 0:
                return False
            
            locator.first.fill(value)
            return True
            
        except Exception as e:
            logger.debug(f"[INJECT] Failed for {selector}: {e}")
            return False
    
    def fill_booking_form(self, page: Page, session: SessionState) -> bool:
        """
        Fill the booking form with user data
        """
        worker_id = session.worker_id
        logger.info(f"📝 [W{worker_id}] Filling booking form...")
        
        try:
            # Standard Fields
            self.fast_inject(page, "input[name='lastname']", Config.LAST_NAME)
            self.fast_inject(page, "input[name='firstname']", Config.FIRST_NAME)
            self.fast_inject(page, "input[name='email']", Config.EMAIL)
            
            # Email repeat
            if not self.fast_inject(page, "input[name='emailrepeat']", Config.EMAIL):
                self.fast_inject(page, "input[name='emailRepeat']", Config.EMAIL)
            
            # Dynamic Fields
            phone_value = Config.PHONE.replace("+", "00").strip()
            self.fast_inject(page, "input[name='fields[0].content']", Config.PASSPORT)
            self.fast_inject(page, "input[name='fields[1].content']", phone_value)
            
            # Category Selection
            try:
                select_elem = page.locator("select").first
                if select_elem.is_visible():
                    select_elem.select_option(index=1)
            except:
                pass
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            logger.info(f"✅ [W{worker_id}] Form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ [W{worker_id}] Form fill error: {e}")
            return False
    
    # ==================== Single Session Mode ====================
    
    def _run_single_session(self, browser: Browser, worker_id: int):
        """
        Single session mode: Full scan + book flow
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode started")
        
        # Create context
        context, page, session = self.create_context(browser, worker_id, None)
        
        try:
            max_cycles = 50
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    break
                
                worker_logger.info(f"[CYCLE {cycle+1}] Starting...")
                
                # Get month URLs to scan
                month_urls = self.generate_month_urls()
                
                for url in month_urls:
                    if self.stop_event.is_set():
                        break
                    
                    # Navigate to month page
                    try:
                        page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        self.global_stats.pages_loaded += 1
                        worker_logger.info(f"[MONTH] Loaded: {url.split('/')[-1][:60]}")
                    except Exception as e:
                        worker_logger.warning(f"[NAV ERROR] Month page: {e}")
                        continue
                    
                    # Wait for page
                    time.sleep(2)
                    
                    # Check for captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, "MONTH")
                    
                    if has_captcha:
                        worker_logger.info("[MONTH] Solving captcha...")
                        
                        # Solve captcha
                        success, code, captcha_status = self.solver.solve_from_page(
                            page, "MONTH",
                            session_age=session.age(),
                            attempt=1,
                            max_attempts=3
                        )
                        
                        if success and code:
                            worker_logger.info(f"[CAPTCHA] Code: '{code}'")
                            
                            # Fill captcha
                            captcha_input = page.locator("input[name='captchaText']").first
                            if captcha_input.is_visible():
                                captcha_input.fill(code)
                                
                                # Press Enter
                                captcha_input.press("Enter")
                                worker_logger.info("[CAPTCHA] Pressed Enter")
                                
                                # Wait
                                time.sleep(3)
                                
                                self.global_stats.captchas_solved += 1
                                session.mark_captcha_solved()
                        else:
                            worker_logger.warning(f"[CAPTCHA] Failed: {captcha_status}")
                            continue
                    
                    # Check for no appointments
                    content = page.content().lower()
                    if "no appointments" in content or "keine termine" in content:
                        worker_logger.info("[MONTH] No appointments")
                        continue
                    
                    # Look for available days
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    
                    if not day_links:
                        worker_logger.debug("[MONTH] No days found")
                        continue
                    
                    # FOUND DAYS!
                    num_days = len(day_links)
                    worker_logger.critical(f"[FOUND] {num_days} DAYS!")
                    self.global_stats.days_found += num_days
                    
                    # Click first day
                    first_href = day_links[0].get_attribute("href")
                    if not first_href:
                        continue
                    
                    base_domain = self.base_url.split("/extern")[0]
                    day_url = f"{base_domain}/{first_href}"
                    
                    worker_logger.info("[DAY] Going to day page...")
                    
                    try:
                        page.goto(day_url, timeout=20000, wait_until="domcontentloaded")
                    except Exception as e:
                        worker_logger.error(f"[NAV ERROR] Day page: {e}")
                        continue
                    
                    time.sleep(2)
                    
                    # Look for time slots
                    slot_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    
                    if not slot_links:
                        worker_logger.info("[DAY] No time slots")
                        continue
                    
                    # FOUND SLOTS!
                    num_slots = len(slot_links)
                    worker_logger.critical(f"[FOUND] {num_slots} TIME SLOTS!")
                    self.global_stats.slots_found += num_slots
                    
                    # Click first slot
                    slot_href = slot_links[0].get_attribute("href")
                    if not slot_href:
                        continue
                    
                    slot_url = f"{base_domain}/{slot_href}"
                    
                    worker_logger.info("[FORM] Going to booking form...")
                    
                    try:
                        page.goto(slot_url, timeout=20000, wait_until="domcontentloaded")
                    except Exception as e:
                        worker_logger.error(f"[NAV ERROR] Form page: {e}")
                        continue
                    
                    time.sleep(2)
                    
                    # Fill form
                    if not self.fill_booking_form(page, session):
                        worker_logger.warning("[FORM] Form fill failed")
                        continue
                    
                    # Solve form captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, "FORM")
                    
                    if has_captcha:
                        worker_logger.info("[FORM] Solving form captcha...")
                        
                        success, code, captcha_status = self.solver.solve_from_page(
                            page, "FORM",
                            session_age=session.age(),
                            attempt=1,
                            max_attempts=3
                        )
                        
                        if success and code:
                            worker_logger.info(f"[FORM CAPTCHA] Code: '{code}'")
                            
                            # Fill and submit
                            captcha_input = page.locator("input[name='captchaText']").first
                            if captcha_input.is_visible():
                                captcha_input.fill(code)
                                
                                # Look for submit button
                                submit_selectors = [
                                    "input[type='submit'][value='Submit']",
                                    "input[type='submit'][value='submit']",
                                    "input[name='action:appointment_addAppointment']"
                                ]
                                
                                for selector in submit_selectors:
                                    try:
                                        submit_btn = page.locator(selector).first
                                        if submit_btn.is_visible(timeout=1000):
                                            submit_btn.click()
                                            worker_logger.info(f"[SUBMIT] Clicked: {selector}")
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
                                    "confirmation"
                                ]
                                
                                for indicator in success_indicators:
                                    if indicator in content:
                                        worker_logger.critical(f"[SUCCESS] Found: '{indicator}'")
                                        
                                        # Save evidence
                                        self.debug_manager.save_critical_screenshot(page, "SUCCESS", worker_id)
                                        
                                        # Notify
                                        try:
                                            send_success_notification(self.session_id, worker_id, None)
                                        except:
                                            pass
                                        
                                        with self.lock:
                                            self.global_stats.success = True
                                        
                                        self.stop_event.set()
                                        return  # SUCCESS!
                                
                                worker_logger.warning("[SUBMIT] No success indicators found")
                            else:
                                worker_logger.warning("[FORM] Captcha input not found")
                        else:
                            worker_logger.warning(f"[FORM] Captcha failed: {captcha_status}")
                    
                    # If we reach here, try next month
                    break
                
                # Sleep between cycles
                sleep_time = self.get_sleep_interval()
                worker_logger.info(f"[SLEEP] {sleep_time:.1f}s")
                time.sleep(sleep_time)
            
            worker_logger.info("[END] Max cycles reached")
            
        except Exception as e:
            worker_logger.error(f"[FATAL] Single session error: {e}", exc_info=True)
        
        finally:
            try:
                context.close()
            except:
                pass
            worker_logger.info("[END] Session closed")
    
    # ==================== Main Entry Point ====================
    
    def run(self) -> bool:
        """
        Main execution entry point
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - STARTING")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info(f"[CURRENT TIME] Aden: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # Send startup notification
            send_alert(
                f"[Elite Sniper v{self.VERSION} Started]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Session\n"
                f"Attack: {Config.ATTACK_HOUR}:00 AM Aden"
            )
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                logger.info("[BROWSER] Launched successfully")
                
                # Run single session
                worker_id = 1
                
                try:
                    self._run_single_session(browser, worker_id)
                except Exception as e:
                    logger.error(f"[SESSION ERROR] {e}")
                
                # Stop NTP sync
                self.ntp_sync.stop_background_sync()
                
                # Cleanup
                browser.close()
                
                # Save final stats
                final_stats = self.global_stats.to_dict()
                self.debug_manager.save_stats(final_stats, "final_stats.json")
                
                if self.global_stats.success:
                    self._handle_success()
                    return True
                else:
                    self._handle_completion()
                    return False
                
        except KeyboardInterrupt:
            logger.info("\n[STOP] Manual stop requested")
            self.stop_event.set()
            self.ntp_sync.stop_background_sync()
            send_alert("⏸️ Elite Sniper stopped manually")
            return False
            
        except Exception as e:
            logger.error(f"💀 Critical error: {e}", exc_info=True)
            send_alert(f"🚨 Critical error: {str(e)[:200]}")
            return False
    
    def _handle_success(self):
        """Handle successful booking"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] MISSION ACCOMPLISHED - BOOKING SUCCESSFUL!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"ELITE SNIPER V2.0 - SUCCESS!\n"
            f"[+] Appointment booked!\n"
            f"Session: {self.session_id}\n"
            f"Runtime: {runtime:.0f}s\n"
            f"Stats: {self.global_stats.get_summary()}"
        )
    
    def _handle_completion(self):
        """Handle completion without success"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Session completed without booking")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        logger.info(f"[TIME] Runtime: {runtime:.0f}s")
        logger.info(f"[STATS] Final stats: {self.global_stats.get_summary()}")


# Entry point
if __name__ == "__main__":
    sniper = EliteSniperV2()
    success = sniper.run()
    sys.exit(0 if success else 1)