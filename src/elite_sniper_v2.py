"""
Elite Sniper v2.0 - Production-Grade Multi-Session Appointment Booking System
[FINAL GOLDEN VERSION] - Includes Human Typing & Navigation Safety
"""

import time
import random
import datetime
import logging
import os
import sys
import re
from typing import List, Tuple, Optional, Dict, Any
from threading import Thread, Event, Lock
from dataclasses import asdict

import pytz
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

# Internal imports
from .config import Config
from .ntp_sync import NTPTimeSync
from .session_state import (
    SessionState, SessionStats, SystemState, SessionHealth, 
    SessionRole, Incident, IncidentManager, IncidentType, IncidentSeverity
)
from .captcha import EnhancedCaptchaSolver
from .notifier import send_alert, send_photo, send_success_notification, send_status_update
from .debug_utils import DebugManager
from .page_flow import PageFlowDetector

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
    VERSION = "2.0.0"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Elite Sniper v2.0"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER V{self.VERSION} - INITIALIZING")
        logger.info(f"[MODE] Running Mode: {self.run_mode}")
        logger.info("=" * 70)
        
        self._validate_config()
        
        self.session_id = f"elite_v2_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        self.system_state = SystemState.STANDBY
        self.stop_event = Event()
        self.slot_event = Event()
        self.target_url: Optional[str] = None
        self.lock = Lock()
        
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full:
            self.solver.auto_full = True
            
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.incident_manager = IncidentManager()
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        self.page_flow = PageFlowDetector()
        
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        
        self.proxies = self._load_proxies()
        self.global_stats = SessionStats()
        self.ntp_sync.start_background_sync()
    
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

    # ==================== Time & Session Management ====================
    
    def get_current_time_aden(self) -> datetime.datetime:
        corrected_utc = self.ntp_sync.get_corrected_time()
        return corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
    
    def is_pre_attack(self) -> bool:
        now = self.get_current_time_aden()
        return (now.hour == 1 and now.minute == Config.PRE_ATTACK_MINUTE and now.second >= Config.PRE_ATTACK_SECOND)
    
    def is_attack_time(self) -> bool:
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def get_sleep_interval(self) -> float:
        if self.is_attack_time(): return random.uniform(Config.ATTACK_SLEEP_MIN, Config.ATTACK_SLEEP_MAX)
        elif self.is_pre_attack(): return Config.PRE_ATTACK_SLEEP
        else: return random.uniform(Config.PATROL_SLEEP_MIN, Config.PATROL_SLEEP_MAX)
    
    def get_mode(self) -> str:
        if self.is_attack_time(): return "ATTACK"
        elif self.is_pre_attack(): return "PRE_ATTACK"
        else: return "PATROL"

    def create_context(self, browser: Browser, worker_id: int, proxy: Optional[str] = None):
        role = SessionRole.SCOUT if worker_id == 1 else SessionRole.ATTACKER
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
        
        context.set_default_timeout(25000)
        
        session_state = SessionState(
            session_id=f"{self.session_id}_w{worker_id}",
            role=role,
            worker_id=worker_id,
            max_age=Config.SESSION_MAX_AGE,
            max_idle=Config.SESSION_MAX_IDLE,
            max_failures=Config.MAX_CONSECUTIVE_ERRORS,
            max_captcha_attempts=Config.MAX_CAPTCHA_ATTEMPTS
        )
        
        logger.info(f"[CTX] [W{worker_id}] Context created - Role: {role.value}")
        return context, page, session_state

    def validate_session_health(self, page: Page, session: SessionState, location: str = "UNKNOWN") -> bool:
        if session.is_expired():
            logger.critical(f"[EXP] [W{session.worker_id}] Session EXPIRED")
            return False
        if session.should_terminate():
            logger.critical(f"💀 [W{session.worker_id}] Session POISONED")
            return False
        
        # Double captcha check
        if session.captcha_solved:
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if has_captcha:
                logger.critical(f"💀 [W{session.worker_id}] DOUBLE CAPTCHA detected - Session INVALID")
                session.health = SessionHealth.POISONED
                return False
                
        session.touch()
        return True

    def soft_recovery(self, session: SessionState, reason: str):
        logger.info(f"🔄 [W{session.worker_id}] Soft recovery: {reason}")
        session.consecutive_errors = 0
        session.failures = max(0, session.failures - 1)
        session.touch()

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

    # ==================== Form Handling (PATCHED) ====================

    def _fill_booking_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        """
        [PATCHED] Fill booking form using HUMAN TYPING to trigger validation scripts.
        Avoids JS injection unless absolutely necessary.
        """
        try:
            worker_logger.info("📝 Filling form (Human Mode)...")
            
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
                        page.focus(selector)
                        page.fill(selector, "")
                        page.type(selector, value, delay=10)
                        page.evaluate(f"document.querySelector(\"{selector}\").blur()")
                except: continue

            # Category Selection
            try:
                purpose = Config.PURPOSE.lower() if Config.PURPOSE else "aupair"
                purpose_value = Config.PURPOSE_VALUES.get(purpose, Config.DEFAULT_PURPOSE)
                
                select_elem = page.locator("select[name='fields[2].content']").first
                if not select_elem.is_visible(): select_elem = page.locator("select").first
                
                if select_elem.is_visible():
                    select_elem.select_option(value=purpose_value)
                else:
                    page.evaluate(f"const s = document.querySelector('select'); if(s) {{ s.selectedIndex = 1; s.dispatchEvent(new Event('change')); }}")
            except Exception as e:
                worker_logger.warning(f"Category selection warning: {e}")

            self.global_stats.forms_filled += 1
            worker_logger.info("✅ Form filled (Humanized)")
            return True
            
        except Exception as e:
            worker_logger.error(f"❌ Form fill error: {e}")
            return False

    def _submit_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        """
        [ULTIMATE PATCH] Submit form using ENTER KEY with Navigation Safety.
        Fixes race conditions and handles soft/hard fails.
        """
        worker_id = session.worker_id
        max_attempts = 15
        
        worker_logger.info(f"🚀 STARTING SUBMISSION SEQUENCE...")

        for attempt in range(1, max_attempts + 1):
            try:
                # 1. Check if we are on the form page
                captcha_input = page.locator("input[name='captchaText']").first
                if not captcha_input.is_visible():
                    content = ""
                    try: content = page.content().lower()
                    except: pass
                    
                    if "appointment number" in content or "successfully" in content:
                        return True
                    
                    worker_logger.warning("⚠️ Captcha input not found! Checking page state...")
                    if "beginnen sie den buchungsvorgang neu" in content or "ref-id:" in content:
                        worker_logger.error("❌ CRITICAL: Session Expired (Hard Fail).")
                        session.health = SessionHealth.POISONED
                        return False
                    return False

                # 2. Solve Captcha
                success, code, _ = self.solver.solve_from_page(page, f"SUBMIT_{attempt}")
                
                if not success or not code:
                    worker_logger.warning("🔄 Captcha solve failed, refreshing...")
                    try:
                        page.click("#appointment_newAppointmentForm_form_newappointment_refreshcaptcha", timeout=1000)
                    except:
                        self.solver.reload_captcha(page)
                    time.sleep(1.5)
                    continue

                # 3. Fill and Submit with Navigation Expectation
                worker_logger.info(f"⌨️ Attempt {attempt}: Typing '{code}' and pressing ENTER...")
                captcha_input.click()
                captcha_input.fill("")
                captcha_input.fill(code)
                time.sleep(0.3)

                # Use expect_navigation to handle .do full page reloads safely
                try:
                    with page.expect_navigation(timeout=10000):
                        page.keyboard.press("Enter")
                except Exception as e:
                    worker_logger.debug(f"Navigation timeout or same-page reload: {e}")

                # 4. Wait for stability
                try: page.wait_for_load_state("domcontentloaded", timeout=5000)
                except: pass

                # 5. Analyze Result
                content = ""
                for _ in range(3):
                    try:
                        content = page.content().lower()
                        break
                    except: time.sleep(1)

                if not content:
                    worker_logger.error("❌ Failed to read page content")
                    continue

                # Case A: Success
                if "appointment number" in content or "successfully" in content or "termin nummer" in content:
                    worker_logger.critical("🏆 VICTORY! APPOINTMENT SECURED!")
                    self.global_stats.success = True
                    self.debug_manager.save_critical_screenshot(page, "VICTORY", worker_id)
                    self.stop_event.set()
                    return True
                
                # Case B: Hard Fail
                if "beginnen sie den buchungsvorgang neu" in content or "ref-id:" in content:
                    worker_logger.error("❌ CRITICAL: Session Invalidated by Server.")
                    session.health = SessionHealth.POISONED
                    return False

                # Case C: Soft Fail (Captcha Wrong) - Back to form
                if page.locator("input[name='lastname']").count() > 0:
                    worker_logger.warning(f"↩️ Bounced back to form (Attempt {attempt}).")
                    
                    # Refresh captcha
                    try:
                        page.click("#appointment_newAppointmentForm_form_newappointment_refreshcaptcha", timeout=1000)
                    except:
                        self.solver.reload_captcha(page)
                    
                    # Re-fill if cleared
                    try:
                        if page.locator("input[name='lastname']").input_value() == "":
                            worker_logger.info("📝 Re-filling cleared form fields...")
                            self._fill_booking_form(page, session, worker_logger)
                    except: pass
                    
                    time.sleep(1)
                    continue
                
                worker_logger.error("❓ Unknown page state.")

            except Exception as e:
                worker_logger.error(f"⚠️ Submit loop exception: {e}")
                time.sleep(1)
        
        return False

    # ==================== Behaviors ====================
    
    def _scout_behavior(self, page: Page, session: SessionState, worker_logger):
        worker_logger.info("🔍 Scout scanning...")
        try:
            month_urls = self.generate_month_urls()
            for url in month_urls[:4]:
                if self.stop_event.is_set(): return
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    session.touch()
                    self.global_stats.pages_loaded += 1
                    
                    has_captcha, _ = self.solver.safe_captcha_check(page, "SCOUT_MONTH")
                    if has_captcha:
                        success, code, _ = self.solver.solve_from_page(page, "SCOUT_MONTH")
                        if success and code:
                            self.solver.submit_captcha(page, "enter")
                            try: page.wait_for_load_state("domcontentloaded", timeout=5000)
                            except: pass
                            session.mark_captcha_solved()
                        else: continue
                    
                    if "no appointments" in page.content().lower(): continue
                    
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    if day_links:
                        worker_logger.critical(f"🟢 SCOUT FOUND {len(day_links)} DAYS!")
                        with self.lock: self.target_url = url
                        self.slot_event.set()
                        send_alert(f"🎯 Days found! Signaling attackers.")
                        time.sleep(2)
                        return
                except Exception as e:
                    worker_logger.warning(f"Month scan error: {e}")
                    session.increment_failure(str(e))
        except Exception as e:
            worker_logger.error(f"Scout error: {e}")

    def _attacker_behavior(self, page: Page, session: SessionState, worker_logger):
        if not self.slot_event.is_set():
            if session.pages_loaded == 0:
                month_urls = self.generate_month_urls()
                if month_urls:
                    try:
                        page.goto(month_urls[0], wait_until="domcontentloaded", timeout=20000)
                        session.pages_loaded += 1
                        success, code, _ = self.solver.solve_from_page(page, "ATTACKER_READY")
                        if success and code:
                            self.solver.submit_captcha(page, "enter")
                            session.mark_captcha_solved()
                            worker_logger.info("✅ Attacker ready")
                    except: pass
            self.slot_event.wait(timeout=5)
            return

        worker_logger.warning("🔥 ATTACKER ENGAGING!")
        try:
            if not self.target_url: return
            page.goto(self.target_url, wait_until="domcontentloaded", timeout=15000)
            
            # Month Captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_MONTH")
            if success: self.solver.submit_captcha(page)
            
            # Days
            day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
            if not day_links: return
            day_links[0].click()
            
            # Day Captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_DAY")
            if success: self.solver.submit_captcha(page)
            
            # Slots
            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
            if not time_links: return
            time_links[0].click()
            
            # Form Captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_FORM")
            if success: self.solver.submit_captcha(page)
            
            # Fill & Submit
            if self._fill_booking_form(page, session, worker_logger):
                self._submit_form(page, session, worker_logger)
                
        except Exception as e:
            worker_logger.error(f"Attacker error: {e}")
            session.increment_failure(str(e))

    def session_worker(self, browser: Browser, worker_id: int):
        worker_logger = logging.getLogger(f"EliteSniperV2.W{worker_id}")
        try:
            proxy = self.proxies[worker_id - 1] if len(self.proxies) >= worker_id else None
            context, page, session = self.create_context(browser, worker_id, proxy)
            
            while not self.stop_event.is_set():
                try:
                    if self.is_pre_attack() and not session.pre_attack_reset_done:
                        try: context.close()
                        except: pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        session.pre_attack_reset_done = True
                        continue
                        
                    if session.should_terminate():
                        try: context.close()
                        except: pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        continue
                        
                    if session.role == SessionRole.SCOUT:
                        self._scout_behavior(page, session, worker_logger)
                    else:
                        self._attacker_behavior(page, session, worker_logger)
                        
                    time.sleep(self.get_sleep_interval())
                    
                except Exception as e:
                    worker_logger.error(f"Cycle error: {e}")
                    session.increment_failure(str(e))
                    
        except Exception as e:
            worker_logger.error(f"Worker fatal error: {e}")
        finally:
            try: context.close()
            except: pass

    def run(self) -> bool:
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - MULTI-SESSION MODE")
        
        try:
            send_alert(f"🚀 Elite Sniper V{self.VERSION} Started (Multi-Session)")
            
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
                
                if self.global_stats.success:
                    self._handle_success()
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Critical error: {e}")
            return False

    def _handle_success(self):
        send_alert("🎉 VICTORY! Appointment Booked!")

    def _handle_completion(self):
        pass

if __name__ == "__main__":
    sniper = EliteSniperV2()
    sniper.run()