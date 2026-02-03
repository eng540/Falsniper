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
        self.system_state = SystemState.STANDBY
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
        self.incident_manager = IncidentManager()
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        self.page_flow = PageFlowDetector()  # For accurate page type detection
        
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
    
    def is_pre_attack(self) -> bool:
        """Check if in pre-attack window (1:59:30 - 1:59:59 Aden time)"""
        now = self.get_current_time_aden()
        return (now.hour == 1 and 
                now.minute == Config.PRE_ATTACK_MINUTE and 
                now.second >= Config.PRE_ATTACK_SECOND)
    
    def is_attack_time(self) -> bool:
        """Check if in attack window (2:00:00 - 2:02:00 Aden time)"""
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def get_sleep_interval(self) -> float:
        """Calculate dynamic sleep interval based on current mode"""
        if self.is_attack_time():
            return random.uniform(Config.ATTACK_SLEEP_MIN, Config.ATTACK_SLEEP_MAX)
        elif self.is_pre_attack():
            return Config.PRE_ATTACK_SLEEP
        else:
            now = self.get_current_time_aden()
            if now.hour == 1 and now.minute >= 45:
                return Config.WARMUP_SLEEP
            return random.uniform(Config.PATROL_SLEEP_MIN, Config.PATROL_SLEEP_MAX)
    
    def get_mode(self) -> str:
        """Get current operational mode"""
        if self.is_attack_time():
            return "ATTACK"
        elif self.is_pre_attack():
            return "PRE_ATTACK"
        else:
            now = self.get_current_time_aden()
            if now.hour == 1 and now.minute >= 45:
                return "WARMUP"
            return "PATROL"
    
    # ==================== Session Management ====================
    
    def create_context(
        self, 
        browser: Browser, 
        worker_id: int,
        proxy: Optional[str] = None
    ) -> Tuple[BrowserContext, Page, SessionState]:
        """
        Create browser context with session state
        
        Args:
            browser: Playwright browser instance
            worker_id: Worker ID (1-3)
            proxy: Optional proxy server
        
        Returns:
            (context, page, session_state)
        """
        try:
            # Determine role
            role = SessionRole.SCOUT if worker_id == 1 else SessionRole.ATTACKER
            
            # Select user agent
            user_agent = random.choice(self.user_agents)
            
            # Randomize viewport slightly for fingerprint variation
            viewport_width = 1366 + random.randint(0, 50)
            viewport_height = 768 + random.randint(0, 30)
            
            # Context arguments
            context_args = {
                "user_agent": user_agent,
                "viewport": {"width": viewport_width, "height": viewport_height},
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
            
            # Anti-detection + Keep-Alive script
            page.add_init_script(f"""
                // Hide webdriver
                Object.defineProperty(navigator, 'webdriver', {{ 
                    get: () => undefined 
                }});
                
                // Override plugins
                Object.defineProperty(navigator, 'plugins', {{
                    get: () => [1, 2, 3, 4, 5]
                }});
                
                // Override languages
                Object.defineProperty(navigator, 'languages', {{
                    get: () => ['en-US', 'en']
                }});
                
                // Session keep-alive heartbeat (every {Config.HEARTBEAT_INTERVAL}s)
                setInterval(() => {{
                    fetch(location.href, {{ method: 'HEAD' }}).catch(()=>{{}});
                }}, {Config.HEARTBEAT_INTERVAL * 1000});
            """)
            
            # Timeouts
            context.set_default_timeout(25000)
            context.set_default_navigation_timeout(30000)
            
            # Resource blocking for performance
            def route_handler(route):
                resource_type = route.request.resource_type
                if resource_type in ["image", "media", "font", "stylesheet"]:
                    route.abort()
                else:
                    route.continue_()
            
            page.route("**/*", route_handler)
            
            # Create session state with config limits
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
        Validate session health with strict kill rules
        
        Returns:
            True if session is healthy, False if should be terminated
        """
        worker_id = session.worker_id
        
        # Rule 1: Session expired (age > 60s or idle > 15s)
        if session.is_expired():
            age = session.age()
            idle = session.idle_time()
            logger.critical(
                f"[EXP] [W{worker_id}][{location}] "
                f"Session EXPIRED - Age: {age:.1f}s, Idle: {idle:.1f}s"
            )
            self.incident_manager.create_incident(
                session.session_id, IncidentType.SESSION_EXPIRED,
                IncidentSeverity.CRITICAL,
                f"Session expired: age={age:.1f}s, idle={idle:.1f}s"
            )
            return False
        
        # Rule 2: Too many failures
        if session.should_terminate():
            logger.critical(
                f"💀 [W{worker_id}][{location}] "
                f"Session POISONED - Failures: {session.failures}"
            )
            self.incident_manager.create_incident(
                session.session_id, IncidentType.SESSION_POISONED,
                IncidentSeverity.CRITICAL,
                f"Session poisoned: failures={session.failures}"
            )
            return False
        
        # Rule 3: Double captcha detection (captcha appears twice in same flow)
        if session.captcha_solved:
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if has_captcha:
                logger.critical(
                    f"💀 [W{worker_id}][{location}] "
                    f"DOUBLE CAPTCHA detected - Session INVALID"
                )
                session.health = SessionHealth.POISONED
                self.incident_manager.create_incident(
                    session.session_id, IncidentType.DOUBLE_CAPTCHA,
                    IncidentSeverity.CRITICAL,
                    "Double captcha in same flow - session poisoned"
                )
                return False
        
        # Rule 4: Silent rejection (form still visible after submit)
        if location == "POST_SUBMIT":
            try:
                if page.locator("input[name='lastname']").count() > 0:
                    logger.critical(
                        f"🔁 [W{worker_id}][{location}] "
                        f"Silent rejection - Form reappeared"
                    )
                    self.incident_manager.create_incident(
                        session.session_id, IncidentType.FORM_REJECTED,
                        IncidentSeverity.ERROR,
                        "Form reappeared after submit - silent rejection"
                    )
                    return False
            except:
                pass
        
        # Rule 5: Bounce detection (month captcha in form view)
        if location == "FORM":
            try:
                if page.locator("form#appointment_captcha_month").count() > 0:
                    logger.critical(
                        f"↩️ [W{worker_id}][{location}] "
                        f"Bounced to month captcha"
                    )
                    return False
            except:
                pass
        
        # Session is healthy
        session.touch()
        return True
    
    def soft_recovery(self, session: SessionState, reason: str):
        """
        Soft recovery without full context recreation
        From KingSniperV12
        """
        logger.info(f"🔄 [W{session.worker_id}] Soft recovery: {reason}")
        
        # Reset counters
        session.consecutive_errors = 0
        session.failures = max(0, session.failures - 1)  # Forgive one failure
        
        # Update health
        if session.health == SessionHealth.DEGRADED:
            session.health = SessionHealth.WARNING
        elif session.health == SessionHealth.WARNING:
            session.health = SessionHealth.CLEAN
        
        session.touch()
        
        logger.info(f"✅ [W{session.worker_id}] Soft recovery completed")
    
    # ==================== Navigation & Form Filling ====================
    
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
        Inject value into form field using Playwright native methods first,
        then JavaScript fallback for reliability.
        """
        try:
            locator = page.locator(selector)
            if locator.count() == 0:
                logger.warning(f"[INJECT] Selector not found: {selector}")
                return False
            
            # Method 1: Use Playwright's native fill() - most reliable
            try:
                locator.first.fill(value, timeout=2000)
                logger.debug(f"[INJECT] Filled via Playwright: {selector}")
                return True
            except Exception as e1:
                logger.debug(f"[INJECT] Playwright fill failed for {selector}: {e1}")
            
            # Method 2: Click then type
            try:
                locator.first.click(timeout=1000)
                locator.first.fill(value, timeout=2000)
                return True
            except Exception as e2:
                logger.debug(f"[INJECT] Click+fill failed for {selector}: {e2}")
            
            # Method 3: JavaScript injection as fallback
            try:
                escaped_value = value.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
                page.evaluate(f"""
                    const el = document.querySelector("{selector}");
                    if(el) {{ 
                        el.value = "{escaped_value}"; 
                        el.dispatchEvent(new Event('input', {{ bubbles: true }})); 
                        el.dispatchEvent(new Event('change', {{ bubbles: true }})); 
                        el.dispatchEvent(new Event('blur', {{ bubbles: true }})); 
                    }}
                """)
                logger.debug(f"[INJECT] Filled via JS: {selector}")
                return True
            except Exception as e3:
                logger.warning(f"[INJECT] JS injection failed for {selector}: {e3}")
            
            return False
            
        except Exception as e:
            logger.warning(f"[INJECT] All methods failed for {selector}: {e}")
            return False
    
    def find_input_id_by_label(self, page: Page, label_text: str) -> Optional[str]:
        """Find input ID by label text"""
        try:
            return page.evaluate(f"""
                () => {{
                    const labels = Array.from(document.querySelectorAll('label'));
                    const target = labels.find(l => l.innerText.toLowerCase().includes("{label_text.lower()}"));
                    return target ? target.getAttribute('for') : null;
                }}
            """)
        except:
            return None
    
    def select_category_by_value(self, page: Page) -> bool:
        """
        Select category using exact Value attribute for server-side trigger
        Uses Config.CATEGORY_IDS for accurate selection
        """
        try:
            # Find all select elements
            selects = page.locator("select").all()
            
            for select in selects:
                try:
                    # Get options
                    options = select.locator("option").all()
                    
                    for option in options:
                        text = option.inner_text().lower()
                        
                        # Check for matches in our category map
                        for keyword, value_id in Config.CATEGORY_IDS.items():
                            if keyword in text:
                                value = option.get_attribute("value")
                                if value:
                                    select.select_option(value=value)
                                    logger.info(f"📋 Selected category: {text} (value={value})")
                                    
                                    # Trigger change event
                                    page.evaluate("""
                                        const selects = document.querySelectorAll('select');
                                        selects.forEach(s => {
                                            s.dispatchEvent(new Event('change', { bubbles: true }));
                                        });
                                    """)
                                    return True
                    
                    # Fallback: select first available option
                    if len(options) > 1:
                        select.select_option(index=1)
                        page.evaluate("""
                            const selects = document.querySelectorAll('select');
                            selects.forEach(s => {
                                s.dispatchEvent(new Event('change', { bubbles: true }));
                            });
                        """)
                        return True
                        
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            logger.warning(f"Category selection error: {e}")
            return False
    
    def fill_booking_form(self, page: Page, session: SessionState) -> bool:
        """
        Fill the booking form with user data
        Uses Surgeon's Injection for reliability
        """
        worker_id = session.worker_id
        logger.info(f"📝 [W{worker_id}] Filling booking form...")
        
        try:
            # 1. Standard Fields
            self.fast_inject(page, "input[name='lastname']", Config.LAST_NAME)
            self.fast_inject(page, "input[name='firstname']", Config.FIRST_NAME)
            self.fast_inject(page, "input[name='email']", Config.EMAIL)
            
            # Email repeat (try both variants)
            if not self.fast_inject(page, "input[name='emailrepeat']", Config.EMAIL):
                self.fast_inject(page, "input[name='emailRepeat']", Config.EMAIL)
            
            # 2. Dynamic Fields (Passport, Phone)
            phone_value = Config.PHONE.replace("+", "00").strip()
            
            # Try finding by label first
            passport_id = self.find_input_id_by_label(page, "Passport")
            if passport_id:
                self.fast_inject(page, f"#{passport_id}", Config.PASSPORT)
            else:
                self.fast_inject(page, "input[name='fields[0].content']", Config.PASSPORT)
            
            phone_id = self.find_input_id_by_label(page, "Telephone")
            if phone_id:
                self.fast_inject(page, f"#{phone_id}", phone_value)
            else:
                self.fast_inject(page, "input[name='fields[1].content']", phone_value)
            
            # 3. Category Selection
            self.select_category_by_value(page)
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            # Save debug evidence
            self.debug_manager.save_debug_html(page, "form_filled", worker_id)
            
            logger.info(f"✅ [W{worker_id}] Form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ [W{worker_id}] Form fill error: {e}")
            return False
    
    def submit_form(self, page: Page, session: SessionState) -> bool:
        """
        AGGRESSIVE FORM SUBMISSION - NO SESSION CHECK!
        
        CRITICAL: When we reach this point, we HAVE the slot and MUST submit.
        Session validation would kill our chance - SKIP IT!
        
        Uses hybrid approach: Enter on captcha + Click submit button
        """
        worker_id = session.worker_id
        logger.info(f"[W{worker_id}] === AGGRESSIVE SUBMIT STARTED ===")
        
        max_attempts = 15  # Increased retries
        
        for attempt in range(1, max_attempts + 1):
            try:
                # ===============================================
                # CRITICAL: DO NOT CHECK SESSION HEALTH!
                # We have the slot, we MUST try to submit anyway
                # ===============================================
                
                # Method 1: Check if captcha input exists and press Enter
                captcha_input = page.locator("input[name='captchaText']").first
                if captcha_input.is_visible(timeout=1000):
                    # Focus and press Enter on captcha field
                    captcha_input.focus()
                    page.keyboard.press("Enter")
                    logger.info(f"[W{worker_id}] [SUBMIT {attempt}] Pressed Enter on captcha field")
                    
                    # Wait briefly for response
                    try:
                        page.wait_for_load_state("networkidle", timeout=3000)
                    except:
                        pass
                    
                    # Check result immediately
                    if self._check_submission_success(page, worker_id):
                        return True
                    
                    # Check if still on form (silent reject)
                    if self._is_on_form_page(page):
                        logger.warning(f"[W{worker_id}] [SUBMIT {attempt}] Still on form - trying click...")
                
                # Method 2: Click submit button directly
                submit_selectors = [
                    "#appointment_newAppointmentForm_appointment_addAppointment",
                    "input[name='action:appointment_addAppointment']",
                    "input[value='Submit']",
                    "input[type='submit'][value='Submit']",
                ]
                
                for selector in submit_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            logger.info(f"[W{worker_id}] [SUBMIT {attempt}] Clicked: {selector}")
                            
                            try:
                                page.wait_for_load_state("networkidle", timeout=3000)
                            except:
                                pass
                            
                            if self._check_submission_success(page, worker_id):
                                return True
                            break
                    except:
                        continue
                
                # Method 3: JavaScript native submit (FACT-BASED TARGETING)
                try:
                    # Submit SPECIFIC form ID verified from RK-Termin form.html
                    logger.info(f"[W{worker_id}] [SUBMIT {attempt}] JS form.submit() targeting 'appointment_newAppointmentForm'...")
                    page.evaluate("""
                        const form = document.getElementById('appointment_newAppointmentForm');
                        if(form) {
                            // FACT: The HTML checkKey function explicitly sets this action
                            form.action = "extern/appointment_addAppointment.do"; 
                            form.submit();
                        } else {
                            // Fallback to name if ID fails
                            document.getElementsByName('appointment_newAppointmentForm')[0]?.submit();
                        }
                    """)
                    
                    try:
                        page.wait_for_load_state("networkidle", timeout=3000)
                    except:
                        pass
                    
                    if self._check_submission_success(page, worker_id):
                        return True
                except Exception as e:
                    logger.warning(f"[W{worker_id}] [SUBMIT {attempt}] JS Submit error: {e}")
                
                # Check for captcha errors (need new captcha)
                content = page.content().lower()
                if "incorrect" in content or "wrong" in content or "falsch" in content:
                    logger.warning(f"[W{worker_id}] [SUBMIT {attempt}] Captcha rejected - re-solving...")
                    
                    # Try to solve new captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, f"RESUBMIT_{attempt}")
                    if has_captcha:
                        success, code, status = self.solver.solve_from_page(page, f"RESUBMIT_{attempt}")
                        if success:
                            logger.info(f"[W{worker_id}] New captcha solved: '{code}'")
                            self.global_stats.captchas_solved += 1
                            continue
                    
                    self.global_stats.captchas_failed += 1
                    continue
                
                # If we're back on month/day page, slot was taken
                if "appointment_showMonth" in page.url or "appointment_showDay" in page.url:
                    logger.error(f"[W{worker_id}] [SUBMIT {attempt}] Slot lost - redirected to calendar")
                    return False
                
            except Exception as e:
                logger.error(f"[W{worker_id}] [SUBMIT {attempt}] Error: {e}")
                continue
        
        logger.warning(f"[W{worker_id}] Max submit attempts ({max_attempts}) reached")
        return False
    
    def _check_submission_success(self, page: Page, worker_id: int) -> bool:
        """Check if submission was successful"""
        try:
            content = page.content().lower()
            
            # Success indicators
            success_terms = [
                "appointment number",
                "confirmation",
                "successfully",
                "termin wurde gebucht",
                "ihre buchung",
                "booking confirmed",
                "appointment confirmed",
            ]
            
            for term in success_terms:
                if term in content:
                    logger.critical(f"[W{worker_id}] *** SUCCESS! Found: '{term}' ***")
                    
                    # Save evidence
                    self.debug_manager.save_critical_screenshot(page, "SUCCESS_FINAL", worker_id)
                    self.debug_manager.save_debug_html(page, "SUCCESS_FINAL", worker_id)
                    
                    # Notify
                    try:
                        send_success_notification(self.session_id, worker_id, None)
                    except:
                        pass
                    
                    with self.lock:
                        self.global_stats.success = True
                    
                    self.stop_event.set()
                    return True
                    
            # If we get here, no success terms found
            logger.warning(f"[W{worker_id}] Submission verification failed - checking for specific errors...")
            
            # Save snapshot of what we see
            try:
                self.debug_manager.save_debug_html(page, "submission_failed_snapshot", worker_id)
                self.debug_manager.save_critical_screenshot(page, "submission_failed_snapshot", worker_id)
            except:
                pass
                
            return False
        except Exception as e:
            logger.error(f"[W{worker_id}] Error in success check: {e}")
            return False
    
    def _is_on_form_page(self, page: Page) -> bool:
        """Check if still on form page (silent reject)"""
        try:
            return page.locator("input[name='lastname']").count() > 0
        except:
            return False
    
    # ==================== Scout Behavior ====================
    
    def _scout_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Scout behavior: Fast discovery, signals attackers
        Does NOT book - purely for finding slots
        """
        worker_id = session.worker_id
        
        try:
            # Get month URLs to scan
            month_urls = self.generate_month_urls()
            
            for url in month_urls:
                if self.stop_event.is_set():
                    return
                
                # Navigate to month page
                try:
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    session.current_url = url
                    session.touch()
                    
                    with self.lock:
                        self.global_stats.pages_loaded += 1
                        self.global_stats.months_scanned += 1
                        self.global_stats.scans += 1
                        
                except Exception as e:
                    worker_logger.warning(f"Navigation error: {e}")
                    with self.lock:
                        self.global_stats.navigation_errors += 1
                    continue
                
                # Check session health
                if not self.validate_session_health(page, session, "SCOUT_MONTH"):
                    return
                
                # Handle captcha if present
                has_captcha, _ = self.solver.safe_captcha_check(page, "SCOUT_MONTH")
                if has_captcha:
                    success, code, captcha_status = self.solver.solve_from_page(page, "SCOUT_MONTH")
                    if success and code:
                        self.solver.submit_captcha(page, "enter")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except:
                            pass
                        
                        with self.lock:
                            self.global_stats.captchas_solved += 1
                        session.mark_captcha_solved()
                    else:
                        with self.lock:
                            self.global_stats.captchas_failed += 1
                        continue
                
                # Check for "no appointments" message
                content = page.content().lower()
                if "no appointments" in content or "keine termine" in content:
                    continue
                
                # Look for available days
                day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                
                if day_links:
                    num_days = len(day_links)
                    worker_logger.critical(f"🔥 SCOUT FOUND {num_days} DAYS!")
                    
                    with self.lock:
                        self.global_stats.days_found += num_days
                    
                    # Get the first day URL
                    first_href = day_links[0].get_attribute("href")
                    if first_href:
                        # Build full URL for attackers
                        base_domain = self.base_url.split("/extern")[0]
                        self.target_url = f"{base_domain}/{first_href}"
                        
                        # Signal attackers!
                        worker_logger.critical(f"🟢 SIGNALING ATTACKERS! URL: {self.target_url[:50]}...")
                        send_alert(
                            f"🟢 <b>SCOUT: SLOTS DETECTED!</b>\n"
                            f"📅 Days found: {num_days}\n"
                            f"⏰ Attackers engaging..."
                        )
                        
                        self.incident_manager.create_incident(
                            session.session_id, IncidentType.SLOT_DETECTED,
                            IncidentSeverity.INFO,
                            f"Found {num_days} available days"
                        )
                        
                        # Signal the event
                        self.slot_event.set()
                        
                        # Scout doesn't proceed to booking - let attackers handle it
                        return
                
        except Exception as e:
            worker_logger.error(f"Scout behavior error: {e}")
            session.increment_failure(str(e))
    
    # ==================== Attacker Behavior ====================
    
    def _attacker_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Attacker behavior: Wait for scout signal or scan independently
        Executes booking when slots are found
        """
        worker_id = session.worker_id
        
        try:
            # In attack mode, scan independently
            mode = self.get_mode()
            
            # If not attack mode and no signal, do light scanning
            if mode not in ["ATTACK", "PRE_ATTACK"] and not self.slot_event.is_set():
                # Light patrol - don't overwhelm server
                time.sleep(random.uniform(2, 5))
                
                # Check for scout signal
                if self.slot_event.wait(timeout=1.0):
                    worker_logger.info("📡 Received scout signal!")
            
            # If signal received and we have a target URL, go directly there
            if self.slot_event.is_set() and self.target_url:
                worker_logger.info(f"🎯 Attacking target: {self.target_url[:50]}...")
                try:
                    page.goto(self.target_url, timeout=15000, wait_until="domcontentloaded")
                    session.touch()
                except Exception as e:
                    worker_logger.warning(f"Target navigation failed: {e}")
                    self.slot_event.clear()  # Clear and retry
                    return
            else:
                # Independent scanning
                month_urls = self.generate_month_urls()
                
                # Attackers scan fewer months to stay ready
                for url in month_urls[:3]:
                    if self.stop_event.is_set():
                        return
                    
                    try:
                        page.goto(url, timeout=20000, wait_until="domcontentloaded")
                        session.current_url = url
                        session.touch()
                        
                        with self.lock:
                            self.global_stats.pages_loaded += 1
                            self.global_stats.scans += 1
                            
                    except Exception as e:
                        worker_logger.warning(f"Navigation error: {e}")
                        continue
                    
                    # Handle captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, f"ATK_MONTH")
                    if has_captcha:
                        success, code, captcha_status = self.solver.solve_from_page(page, f"ATK_MONTH")
                        if success and code:
                            self.solver.submit_captcha(page, "enter")
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=4000)
                            except:
                                pass
                            
                            with self.lock:
                                self.global_stats.captchas_solved += 1
                            session.mark_captcha_solved()
                        else:
                            continue
                    
                    # Look for days
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    if day_links:
                        break
                else:
                    # No days found in any month
                    return
            
            # Check session health
            if not self.validate_session_health(page, session, "ATK_DAY"):
                return
            
            # Click on first available day (or we're already there from target_url)
            day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
            if day_links:
                target_day = random.choice(day_links)
                href = target_day.get_attribute("href")
                
                worker_logger.info(f"📅 Clicking day: {href[:40] if href else 'N/A'}...")
                
                try:
                    target_day.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as e:
                    # Fallback: direct navigation
                    if href:
                        base_domain = self.base_url.split("/extern")[0]
                        page.goto(f"{base_domain}/{href}", timeout=15000)
                
                session.reset_for_new_flow()
            
            # Handle day captcha
            has_captcha, _ = self.solver.safe_captcha_check(page, "ATK_DAY")
            if has_captcha:
                success, code, captcha_status = self.solver.solve_from_page(page, "ATK_DAY")
                if success and code:
                    self.solver.submit_captcha(page, "enter")
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=4000)
                    except:
                        pass
                    session.mark_captcha_solved()
                else:
                    return
            
            # Look for time slots
            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
            
            if time_links:
                with self.lock:
                    self.global_stats.slots_found += len(time_links)
                
                worker_logger.critical(f"⏰ [W{worker_id}] {len(time_links)} TIME SLOTS FOUND!")
                
                # Click first time slot
                target_time = random.choice(time_links)
                href = target_time.get_attribute("href")
                
                try:
                    target_time.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as e:
                    if href:
                        base_domain = self.base_url.split("/extern")[0]
                        page.goto(f"{base_domain}/{href}", timeout=15000)
                
                session.reset_for_new_flow()
                
                # Handle form captcha
                has_captcha, _ = self.solver.safe_captcha_check(page, "ATK_FORM")
                if has_captcha:
                    success, code, captcha_status = self.solver.solve_from_page(page, "ATK_FORM")
                    if success and code:
                        self.solver.submit_captcha(page, "enter")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=4000)
                        except:
                            pass
                        session.mark_captcha_solved()
                    else:
                        return
                
                # Validate we're on the form
                if not self.validate_session_health(page, session, "FORM"):
                    return
                
                # Check if form is visible
                if page.locator("input[name='lastname']").count() == 0:
                    worker_logger.warning("Form not found after navigation")
                    return
                
                # FILL AND SUBMIT FORM!
                self.incident_manager.create_incident(
                    session.session_id, IncidentType.BOOKING_ATTEMPT,
                    IncidentSeverity.INFO,
                    "Attempting to book appointment"
                )
                
                if self.fill_booking_form(page, session):
                    if self.submit_form(page, session):
                        # SUCCESS!
                        return
                
        except Exception as e:
            worker_logger.error(f"Attacker behavior error: {e}")
            session.increment_failure(str(e))
    
    # ==================== Worker Thread ====================
    
    def session_worker(self, browser: Browser, worker_id: int):
        """
        Worker thread for one browser session
        Implements Scout or Attacker behavior based on worker_id
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.W{worker_id}")
        
        try:
            # Get proxy for this worker
            proxy = self.proxies[worker_id - 1] if len(self.proxies) >= worker_id else None
            
            # Create initial context
            context, page, session = self.create_context(browser, worker_id, proxy)
            
            role = "SCOUT" if worker_id == 1 else "ATTACKER"
            worker_logger.info(f"👤 Worker started - Role: {role}")
            
            cycle = 0
            last_status_update = 0
            
            while not self.stop_event.is_set():
                cycle += 1
                
                try:
                    current_time = time.time()
                    mode = self.get_mode()
                    
                    # Periodic status update (every 5 minutes)
                    if current_time - last_status_update > 300:
                        send_status_update(
                            self.session_id,
                            f"Cycle {cycle}",
                            self.global_stats.to_dict(),
                            mode
                        )
                        last_status_update = current_time
                    
                    # Pre-attack reset - fresh session before attack window
                    if self.is_pre_attack() and not session.pre_attack_reset_done:
                        worker_logger.warning("⚙️ PRE-ATTACK: Fresh session reset")
                        try:
                            context.close()
                        except:
                            pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        session.pre_attack_reset_done = True
                        
                        # Pre-solve captcha while waiting
                        try:
                            page.goto(self.base_url, timeout=15000, wait_until="domcontentloaded")
                            self.solver.pre_solve(page, "PRE_ATTACK")
                        except:
                            pass
                        
                        continue
                    
                    # Check session health
                    if session.should_terminate() or session.is_expired():
                        worker_logger.warning("💀 Session unhealthy - Rebirth!")
                        try:
                            context.close()
                        except:
                            pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        continue
                    
                    # Route to appropriate behavior based on role
                    if session.role == SessionRole.SCOUT:
                        self._scout_behavior(page, session, worker_logger)
                    else:
                        self._attacker_behavior(page, session, worker_logger)
                    
                    # Reset slot event after processing (attackers will re-wait)
                    if session.role == SessionRole.ATTACKER and self.slot_event.is_set():
                        # Small delay before clearing to let other attackers see it
                        time.sleep(0.5)
                        self.slot_event.clear()
                    
                    # Dynamic sleep
                    sleep_time = self.get_sleep_interval()
                    time.sleep(sleep_time)
                    
                except Exception as e:
                    worker_logger.error(f"❌ Cycle error: {e}")
                    session.increment_failure(str(e))
                    
                    with self.lock:
                        self.global_stats.errors += 1
                    
                    # Soft recovery on minor errors
                    if session.consecutive_errors < 3:
                        self.soft_recovery(session, f"Cycle error: {e}")
                    else:
                        # Hard reset
                        worker_logger.warning("♻️ Hard reset required")
                        try:
                            context.close()
                        except:
                            pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
        
        except Exception as e:
            worker_logger.error(f"[FATAL] Worker error: {e}", exc_info=True)
        
        finally:
            try:
                context.close()
            except:
                pass
            worker_logger.info("[END] Worker terminated")
    
    # ==================== Single Session Mode ====================
    
    def _run_single_session(self, browser: Browser, worker_id: int):
        """
        Single session mode: Full scan + book flow
        
        CORRECT FLOW (based on reverse engineering HTML):
        
        1. MONTH PAGE (appointment_showMonth.do)
           - MAY have CAPTCHA (session gate) → Solve if present
           - After captcha: shows available days
           - Look for "Appointments are available" links
           
        2. DAY PAGE (appointment_showDay.do)
           - NO CAPTCHA
           - Shows available time slots
           - Look for "Book this appointment" links
           
        3. FORM PAGE (appointment_showForm.do)
           - ALWAYS has CAPTCHA (confirmation)
           - Fill form fields
           - Solve captcha
           - Submit form
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode started")
        
        # Proxy configuration
        proxy = None  # Disabled for testing
        
        # Create context and page
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        
        worker_logger.info(f"[INIT] Session {session.session_id} created")
        if proxy:
            worker_logger.info(f"[PROXY] Using: {proxy[:30]}...")
        else:
            worker_logger.info("[DIRECT] Running without proxy")
        
        try:
            max_cycles = 100
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    break
                
                mode = self.get_mode()
                worker_logger.info(f"[CYCLE {cycle+1}] Mode: {mode}")
                
                # Get month URLs to scan
                month_urls = self.generate_month_urls()
                worker_logger.info(f"[DEBUG] Generated {len(month_urls)} URLs to scan")
                
                for i, url in enumerate(month_urls):
                    worker_logger.info(f"[DEBUG] Processing URL {i+1}/{len(month_urls)}")
                    if self.stop_event.is_set():
                        worker_logger.info("[DEBUG] Stop event set - breaking loop")
                        break
                    if self.stop_event.is_set():
                        break
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 1: MONTH PAGE - MAY HAVE CAPTCHA (Session Gate)
                    # ═══════════════════════════════════════════════════════════════
                    
                    try:
                        page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        session.current_url = url
                        session.touch()
                        self.global_stats.pages_loaded += 1
                        self.global_stats.months_scanned += 1
                        worker_logger.info(f"[MONTH] Loaded: {url.split('/')[-1][:60]}")
                    except Exception as e:
                        worker_logger.warning(f"[NAV ERROR] Month page: {e}")
                        self.global_stats.navigation_errors += 1
                        continue
                    
                    # Check session health
                    if not self.validate_session_health(page, session, "MONTH"):
                        worker_logger.warning("[HEALTH] Session invalid, recreating...")
                        try:
                            context.close()
                        except:
                            pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        break
                    
                    # Save debug HTML
                    self.debug_manager.save_debug_html(page, "month_scan", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # CHECK FOR CAPTCHA ON MONTH PAGE (Session Gate)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Wait for page stability
                    page.wait_for_timeout(2000)
                    
                    has_captcha, check_ok = self.solver.safe_captcha_check(page, "MONTH")
                    
                    # FALLBACK: Check for Month Captcha Form ID directly
                    if not has_captcha:
                        worker_logger.warning("[DEBUG] Standard captcha check failed. Trying strict fallback...")
                        try:
                            # Check if form exists at all
                            form_loc = page.locator("#appointment_captcha_month")
                            if form_loc.count() > 0:
                                visible = form_loc.is_visible()
                                worker_logger.warning(f"[DEBUG] Fallback: Form found. Visible={visible}")
                                if visible:
                                    has_captcha = True
                                else:
                                    # Force true if exists but hidden (weird, but safe)
                                    worker_logger.warning("[DEBUG] Form exists but reported hidden - forcing check")
                                    has_captcha = True
                            else:
                                worker_logger.warning("[DEBUG] Fallback: Form ID not found in DOM")
                        except Exception as e:
                            worker_logger.warning(f"[DEBUG] Fallback error: {e}")
                    
                    if has_captcha:
                        worker_logger.info("[MONTH] Captcha detected - solving session gate...")
                        self.debug_manager.save_critical_screenshot(page, "month_captcha_before", worker_id)
                        
                        # Calculate session age
                        session_age = int(time.time() - session.created_at)
                        
                        # Solve the captcha (try OCR first, then manual Telegram)
                        success, code, captcha_status = self.solver.solve_from_page(
                            page, 
                            "MONTH",
                            session_age=session_age,
                            attempt=1,
                            max_attempts=1  # Only 1 try for month captcha
                        )
                        
                        # Forensic logging for captcha
                        self.debug_manager.save_forensic_state(
                            page, 
                            "month_captcha_attempt", 
                            worker_id,
                            extra_data={"code": code, "status": captcha_status, "success": success}
                        )
                        
                        # Check for BLACK CAPTCHA - session is poisoned!
                        if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                            worker_logger.critical(f"[BLACK CAPTCHA] Session poisoned! Status: {captcha_status}")
                            self.debug_manager.save_critical_screenshot(page, "black_captcha", worker_id)
                            try:
                                context.close()
                            except:
                                pass
                            context, page, session = self.create_context(browser, worker_id, proxy)
                            worker_logger.info("[RECOVERY] Session recreated after black captcha")
                            break  # Exit month loop, start fresh
                        
                        # Check for AGING session warning
                        if captcha_status in ["AGING_7", "AGING_8"]:
                            worker_logger.warning(f"[SESSION AGING] {captcha_status} - Consider session refresh soon")
                        
                        if success and code:
                            worker_logger.info(f"[CAPTCHA] Submitting: '{code}' (Status: {captcha_status})")
                            
                            # Submit captcha (auto tries click then enter)
                            self.solver.submit_captcha(page, "auto")
                            
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=10000)
                            except:
                                pass
                            
                            # Wait for page to stabilize
                            time.sleep(1)
                            
                            # Verify captcha was solved
                            solved, page_type = self.solver.verify_captcha_solved(page, "MONTH_VERIFY")
                            
                            self.debug_manager.save_critical_screenshot(page, f"month_captcha_after_{page_type}", worker_id)
                            
                            if not solved:
                                # Captcha failed - still on captcha page
                                self.global_stats.captchas_failed += 1
                                worker_logger.warning(f"[CAPTCHA] WRONG! '{code}' - Page: {page_type}")
                                continue  # Try next month
                            else:
                                # SUCCESS! Session gate passed
                                self.global_stats.captchas_solved += 1
                                session.mark_captcha_solved()
                                worker_logger.info(f"[CAPTCHA] SUCCESS! '{code}' - Now on: {page_type}")
                        else:
                            # Captcha solve failed
                            self.global_stats.captchas_failed += 1
                            worker_logger.warning(f"[CAPTCHA] Solve failed: {captcha_status}")
                            self.debug_manager.save_critical_screenshot(page, f"captcha_failed_{captcha_status}", worker_id)
                            continue  # Try next month
                    
                    # ═══════════════════════════════════════════════════════════════
                    # NOW WE'RE ON MONTH PAGE WITH AVAILABLE DAYS (No captcha)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Save debug HTML after captcha
                    self.debug_manager.save_debug_html(page, "after_captcha", worker_id)
                    
                    # Check for "no appointments" message
                    content = page.content().lower()
                    if "no appointments" in content or "keine termine" in content:
                        worker_logger.info("[MONTH] No appointments in this month")
                        continue
                    
                    # Look for available days
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    
                    if not day_links:
                        worker_logger.debug("[MONTH] No available days found")
                        continue
                    
                    # FOUND AVAILABLE DAYS!
                    num_days = len(day_links)
                    worker_logger.critical(f"[FOUND] {num_days} DAYS AVAILABLE!")
                    self.global_stats.days_found += num_days
                    
                    # Save evidence
                    self.debug_manager.save_debug_html(page, "days_found", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "days_found", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 2: DAY PAGE - NO CAPTCHA
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Click first available day
                    first_href = day_links[0].get_attribute("href")
                    if not first_href:
                        continue
                    
                    base_domain = self.base_url.split("/extern")[0]
                    day_url = f"{base_domain}/{first_href}" if not first_href.startswith("http") else first_href
                    
                    worker_logger.info(f"[DAY] Navigating to day page...")
                    
                    try:
                        page.goto(day_url, timeout=20000, wait_until="domcontentloaded")
                        session.touch()
                    except Exception as e:
                        worker_logger.error(f"[NAV ERROR] Day page: {e}")
                        continue
                    
                    # Save debug HTML
                    self.debug_manager.save_debug_html(page, "day_page", worker_id)
                    
                    # Look for time slots
                    slot_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    
                    if not slot_links:
                        worker_logger.info("[DAY] No available time slots")
                        continue
                    
                    # FOUND AVAILABLE SLOTS!
                    num_slots = len(slot_links)
                    worker_logger.critical(f"[SLOTS] {num_slots} TIME SLOTS FOUND!")
                    self.global_stats.slots_found += num_slots
                    
                    # Save evidence
                    self.debug_manager.save_debug_html(page, "slots_found", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "slots_found", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 3: FORM PAGE - ALWAYS HAS CAPTCHA
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Click first available slot
                    slot_href = slot_links[0].get_attribute("href")
                    if not slot_href:
                        continue
                    
                    slot_url = f"{base_domain}/{slot_href}" if not slot_href.startswith("http") else slot_href
                    
                    worker_logger.info(f"[FORM] Navigating to booking form...")
                    
                    try:
                        page.goto(slot_url, timeout=20000, wait_until="domcontentloaded")
                        session.touch()
                    except Exception as e:
                        worker_logger.error(f"[NAV ERROR] Form page: {e}")
                        continue
                    
                    # Save form page evidence
                    self.debug_manager.save_debug_html(page, "form_page", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "form_page", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # CRITICAL FIX: FILL FORM FIRST (FAST), THEN CAPTCHA + SUBMIT
                    # This prevents DOUBLE_CAPTCHA by minimizing time between captcha & submit
                    # ═══════════════════════════════════════════════════════════════
                    
                    # STEP 1: Fill form fields FIRST (fast - uses JavaScript injection)
                    worker_logger.info("[FORM] Step 1: Filling form fields FIRST...")
                    if not self.fill_booking_form(page, session):
                        worker_logger.warning("[FORM] Form fill failed")
                        self.debug_manager.save_debug_html(page, "fill_failed", worker_id)
                        continue
                    
                    worker_logger.info("[FORM] Step 1 DONE - Form filled (fast)")
                    
                    # Forensic logging for filled form
                    self.debug_manager.save_forensic_state(page, "form_filled", worker_id)
                    
                    # STEP 2: Now solve captcha (if present) 
                    has_captcha, _ = self.solver.safe_captcha_check(page, "FORM")
                    
                    if has_captcha:
                        worker_logger.info("[FORM] Step 2: Solving captcha...")
                        
                        # Calculate session age
                        session_age = int(time.time() - session.created_at)
                        
                        # Solve with retry logic - reload button if needed
                        success, code, captcha_status = self.solver.solve_form_captcha_with_retry(
                            page, 
                            "FORM_SUBMIT",
                            max_attempts=5,
                            session_age=session_age
                        )
                        
                        if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                            worker_logger.critical("[BLACK CAPTCHA] Session poisoned!")
                            try:
                                context.close()
                            except:
                                pass
                            context, page, session = self.create_context(browser, worker_id, proxy)
                            break
                        
                        if not success or not code:
                            worker_logger.warning(f"[CAPTCHA] Form captcha failed: {captcha_status}")
                            self.global_stats.captchas_failed += 1
                            continue
                        
                        worker_logger.info(f"[FORM] Step 2 DONE - Captcha solved: '{code}'")
                        self.global_stats.captchas_solved += 1
                        session.mark_captcha_solved()
                    
                    # STEP 3: Submit IMMEDIATELY (no delay!)
                    worker_logger.info("[FORM] Step 3: SUBMITTING NOW!")
                    
                    # Save evidence before submit
                    self.debug_manager.save_debug_html(page, "form_ready", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "form_ready", worker_id)
                    
                    # Submit form immediately
                    if self._submit_form(page, session, worker_logger):
                        worker_logger.critical("=" * 60)
                        worker_logger.critical("[SUCCESS] APPOINTMENT BOOKED!")
                        worker_logger.critical("=" * 60)
                        
                        # Save success evidence
                        self.debug_manager.save_debug_html(page, "success", worker_id)
                        self.debug_manager.save_critical_screenshot(page, "success", worker_id)
                        
                        # Notification handled in _submit_form and _handle_success
                        # try:
                        #     send_success_notification(f"APPOINTMENT BOOKED!")
                        # except Exception as e:
                        #     worker_logger.error(f"[NOTIFY] Failed: {e}")
                        
                        # Mark success
                        with self.lock:
                            self.global_stats.success = True
                        self.stop_event.set()
                        
                        return  # EXIT: Success!
                    else:
                        worker_logger.warning("[SUBMIT] Form submission failed")
                        self.debug_manager.save_debug_html(page, "submit_failed", worker_id)
                
                # Sleep based on mode
                sleep_time = self.get_sleep_interval()
                worker_logger.info(f"[SLEEP] {sleep_time:.1f}s")
                time.sleep(sleep_time)
                
                # Recreate session if too old
                if session.age() > Config.SESSION_MAX_AGE:
                    worker_logger.info("[REBIRTH] Session too old, recreating...")
                    try:
                        context.close()
                    except:
                        pass
                    context, page, session = self.create_context(browser, worker_id, proxy)
                    self.global_stats.rebirths += 1
            
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
        
        Returns:
            True if booking successful, False otherwise
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - STARTING EXECUTION")
        # Single session mode - multi-session architecture preserved for future
        logger.info("[MODE] Single Session (Multi-session ready for expansion)")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info(f"[CURRENT TIME] Aden: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # Send startup notification
            send_alert(
                f"[Elite Sniper v{self.VERSION} Started]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Session\n"
                f"Attack: {Config.ATTACK_HOUR}:00 AM Aden\n"
                f"NTP Offset: {self.ntp_sync.offset:.4f}s"
            )
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                logger.info("[BROWSER] Launched successfully")
                
                # ========================================
                # SINGLE SESSION MODE (Direct execution)
                # Architecture preserved for 3 sessions later
                # ========================================
                worker_id = 1  # Scout role for single session
                
                try:
                    # Run single session directly (no threads)
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
                self.debug_manager.create_session_report(final_stats)
                
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
    
    def _scout_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Scout behavior: Fast discovery without booking
        Scans months for available days and signals Attackers
        """
        worker_logger.info("🔍 Scout scanning...")
        
        try:
            month_urls = self.generate_month_urls()
            
            for url in month_urls[:4]:  # First 4 priority months
                if self.stop_event.is_set():
                    return
                
                try:
                    # Navigate to month page
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    session.pages_loaded += 1
                    self.global_stats.pages_loaded += 1
                    
                    # Save debug HTML
                    self.debug_manager.save_debug_html(page, "scout_month", session.worker_id)
                    
                    # Handle captcha if present
                    success, code, captcha_status = self.solver.solve_from_page(page, "SCOUT_MONTH")
                    if success and code:
                        session.mark_captcha_solved()
                        self.global_stats.captchas_solved += 1
                        self.solver.submit_captcha(page)
                        time.sleep(1)
                    
                    # Check for available days
                    day_selectors = [
                        "a.arrow[href*='appointment_showDay']",
                        "td.buchbar a",
                        "a[href*='showDay']"
                    ]
                    
                    for selector in day_selectors:
                        try:
                            days = page.locator(selector).all()
                            if days:
                                worker_logger.critical(f"🟢 SCOUT FOUND {len(days)} DAYS!")
                                self.global_stats.days_found += len(days)
                                
                                # Signal attackers
                                with self.lock:
                                    self.target_url = url
                                
                                self.slot_event.set()
                                send_alert(f"🎯 Days found! Signaling attackers. URL: {url[:60]}...")
                                
                                time.sleep(2)  # Give attackers time to react
                                break
                        except:
                            continue
                    
                except Exception as e:
                    worker_logger.warning(f"⚠️ Month scan error: {e}")
                    session.increment_failure(str(e))
                    continue
            
            self.global_stats.scans += 1
            
        except Exception as e:
            worker_logger.error(f"❌ Scout behavior error: {e}")
            session.increment_failure(str(e))
    
    def _attacker_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Attacker behavior: Wait for Scout signal, then execute booking
        Pre-positioned with solved captcha for instant action
        """
        # If no signal yet, stay ready on first month page
        if not self.slot_event.is_set():
            try:
                if session.pages_loaded == 0:
                    # Get positioned on first month
                    month_urls = self.generate_month_urls()
                    if month_urls:
                        page.goto(month_urls[0], wait_until="domcontentloaded", timeout=20000)
                        session.pages_loaded += 1
                        
                        # Pre-solve captcha
                        success, code, captcha_status = self.solver.solve_from_page(page, "ATTACKER_READY")
                        if success and code:
                            session.mark_captcha_solved()
                            self.global_stats.captchas_solved += 1
                            self.solver.submit_captcha(page)
                            worker_logger.info("✅ Attacker ready with pre-solved captcha")
                
                # Wait for signal with timeout
                self.slot_event.wait(timeout=5)
                return
                
            except Exception as e:
                worker_logger.warning(f"⚠️ Attacker standby error: {e}")
                return
        
        # Got signal - ATTACK!
        worker_logger.warning("🔥 ATTACKER ENGAGING!")
        
        try:
            target = self.target_url
            if not target:
                return
            
            # Navigate to target month
            page.goto(target, wait_until="domcontentloaded", timeout=15000)
            
            # Handle captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_MONTH")
            if success:
                self.solver.submit_captcha(page)
                time.sleep(0.5)
            
            # Find and click day
            day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
            if not day_links:
                day_links = page.locator("a[href*='showDay']").all()
            
            if not day_links:
                worker_logger.warning("⚠️ No days found at target")
                return
            
            # Click first available day
            target_day = day_links[0]
            day_href = target_day.get_attribute("href")
            worker_logger.info(f"📅 Clicking day: {day_href}")
            target_day.click()
            
            time.sleep(1)
            
            # Handle day page captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_DAY")
            if success:
                self.solver.submit_captcha(page)
                time.sleep(0.5)
            
            # Find and click time slot
            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
            if not time_links:
                time_links = page.locator("a[href*='showForm']").all()
            
            if not time_links:
                worker_logger.warning("⚠️ No time slots found")
                self.global_stats.slots_found = 0
                return
            
            self.global_stats.slots_found += len(time_links)
            
            # Click first available time
            target_time = time_links[0]
            time_href = target_time.get_attribute("href")
            worker_logger.info(f"⏰ Clicking time: {time_href}")
            target_time.click()
            
            time.sleep(1)
            
            # Handle form page captcha
            success, _ = self.solver.solve_from_page(page, "ATTACK_FORM")
            if success:
                self.solver.submit_captcha(page)
                time.sleep(0.5)
            
            # Save form page for debugging
            self.debug_manager.save_debug_html(page, "form_page", session.worker_id)
            
            # Fill form
            if self._fill_booking_form(page, session, worker_logger):
                # Submit form
                if self._submit_form(page, session, worker_logger):
                    # SUCCESS!
                    self.global_stats.success = True
                    self.stop_event.set()
                    return
            
        except Exception as e:
            worker_logger.error(f"❌ Attacker error: {e}")
            session.increment_failure(str(e))
    
    def _fill_booking_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        """
        [PATCHED] Fill booking form using HUMAN TYPING to trigger validation scripts.
        Avoids JS injection unless absolutely necessary.
        """
        try:
            worker_logger.info("📝 Filling form (Human Mode)...")
            
            # تعريف الحقول والقيم
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
                ("input[name='emailRepeat']", Config.EMAIL), # Case sensitive check
                # الحقول الديناميكية (جواز السفر والهاتف)
                ("input[name='fields[0].content']", Config.PASSPORT),
                ("input[name='fields[1].content']", Config.PHONE.replace("+", "00").strip())
            ]
            
            for selector, value in fields:
                try:
                    # التحقق من وجود الحقل
                    if page.locator(selector).count() > 0:
                        # 1. التركيز (Focus) - مهم جداً لتفعيل السكربتات
                        page.focus(selector)
                        # 2. مسح المحتوى القديم (إن وجد)
                        page.fill(selector, "")
                        # 3. الكتابة البشرية (Typing)
                        page.type(selector, value, delay=10) # تأخير بسيط جداً (10ms) للمحاكاة
                        # 4. الخروج من الحقل (Blur) لتثبيت القيمة
                        page.evaluate(f"document.querySelector(\"{selector}\").blur()")
                except Exception as e:
                    worker_logger.debug(f"Field fill error ({selector}): {e}")
                    continue

            # اختيار الفئة (Category)
            try:
                # نستخدم Select Option الأصلي لأنه الأضمن
                purpose = Config.PURPOSE.lower() if Config.PURPOSE else "aupair"
                purpose_value = Config.PURPOSE_VALUES.get(purpose, Config.DEFAULT_PURPOSE)
                
                select_elem = page.locator("select[name='fields[2].content']").first
                if not select_elem.is_visible():
                    select_elem = page.locator("select").first
                
                if select_elem.is_visible():
                    # محاولة الاختيار بالقيمة
                    select_elem.select_option(value=purpose_value)
                else:
                    # Fallback: JS Injection for Select only (Selects are tricky)
                    page.evaluate(f"""
                        const s = document.querySelector('select');
                        if(s) {{ s.selectedIndex = 1; s.dispatchEvent(new Event('change')); }}
                    """)
            except Exception as e:
                worker_logger.warning(f"Category selection warning: {e}")

            self.global_stats.forms_filled += 1
            worker_logger.info("✅ Form filled (Humanized)")
            return True
            
        except Exception as e:
            worker_logger.error(f"❌ Form fill error: {e}")
            return False
    
    def _fast_inject(self, page: Page, selector: str, value: str) -> bool:
        """Fast DOM injection bypassing events"""
        try:
            page.evaluate(f"""
                const el = document.querySelector("{selector}");
                if(el) {{
                    el.value = "{value}";
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            return True
        except:
            return False
    
    def _submit_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        """
        [PATCHED] Submit form using ENTER KEY on Captcha field.
        This is the most reliable method as it triggers the form's native submit handler.
        """
        worker_id = session.worker_id
        max_attempts = 10
        
        worker_logger.info(f"🚀 STARTING SUBMISSION SEQUENCE...")

        for attempt in range(1, max_attempts + 1):
            try:
                # 1. التحقق من وجود حقل الكابتشا
                captcha_input = page.locator("input[name='captchaText']").first
                if not captcha_input.is_visible():
                    worker_logger.warning("⚠️ Captcha input not found!")
                    return False

                # 2. حل الكابتشا
                # نستخدم الحل البسيط هنا لأننا داخل حلقة الموت
                success, code, _ = self.solver.solve_from_page(page, f"SUBMIT_{attempt}")
                
                if not success or not code:
                    # إذا فشل الحل، نضغط زر تحديث الصورة ونحاول مرة أخرى
                    worker_logger.warning("🔄 Captcha solve failed, refreshing image...")
                    self.solver.reload_captcha(page)
                    time.sleep(1)
                    continue

                # 3. كتابة الكود والضغط على ENTER (الحركة السحرية)
                worker_logger.info(f"⌨️ Typing captcha '{code}' and pressing ENTER...")
                
                captcha_input.click()
                captcha_input.fill(code)
                time.sleep(0.2)
                page.keyboard.press("Enter") # 🔥 الضربة القاضية
                
                # 4. انتظار النتيجة (حاسم جداً)
                # ننتظر إما ظهور رقم الموعد أو عودة النموذج (فشل)
                try:
                    # ننتظر أي تغيير في الصفحة
                    page.wait_for_load_state("networkidle", timeout=5000)
                except: pass

                content = page.content().lower()

                # 5. تحليل النتيجة
                if "appointment number" in content or "termin nummer" in content:
                    worker_logger.critical("🏆 VICTORY! APPOINTMENT SECURED!")
                    self.global_stats.success = True
                    
                    # حفظ التوثيق
                    self.debug_manager.save_critical_screenshot(page, "VICTORY", worker_id)
                    try:
                        # استدعاء دالة الإشعار الموجودة في الملف الأصلي
                        from .notifier import send_success_notification
                        send_success_notification(self.session_id, worker_id)
                    except: pass
                    
                    self.stop_event.set()
                    return True
                
                # هل عدنا لنفس الصفحة؟ (كابتشا خطأ أو رفض صامت)
                if page.locator("input[name='lastname']").is_visible():
                    worker_logger.warning(f"↩️ Bounced back to form (Attempt {attempt}). Retrying...")
                    # مهم: نعيد تعبئة الحقول لأن بعض المواقع تمسحها عند الخطأ
                    self._fill_booking_form(page, session, worker_logger)
                    # نحدث الكابتشا لضمان صورة جديدة
                    self.solver.reload_captcha(page)
                    time.sleep(1)
                    continue
                
                # صفحة خطأ صريحة
                if "error" in content:
                    worker_logger.error("❌ Server Error Page.")
                    return False

            except Exception as e:
                worker_logger.error(f"⚠️ Submit loop error: {e}")
                time.sleep(1)
        
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
    from src.main import run_elite_sniper_v2
    run_elite_sniper_v2()


# Entry point
if __name__ == "__main__":
    sniper = EliteSniperV2()
    success = sniper.run()
    sys.exit(0 if success else 1)