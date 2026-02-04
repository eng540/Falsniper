"""
Elite Sniper v2.2 - Anti-Detection & Timeout Fix
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
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, expect

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('elite_sniper_v2_fixed.log')
    ]
)
logger = logging.getLogger("EliteSniperV2_Fixed")


class EliteSniperV2:
    VERSION = "2.2.0-ANTIBAN"
    
    # [NEW] Enhanced browser args to bypass detection
    STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-site-isolation-trials",
        "--disable-web-security",
        "--disable-features=BlockInsecurePrivateNetworkRequests",
        "--disable-features=InterestCohort",
        "--disable-features=PrivacySandboxAdsAPIs",
        "--disable-features=PrivacySandboxSettings",
        "--disable-features=ThirdPartyStoragePartitioning",
        "--disable-features=UserAgentClientHint",
        "--disable-features=WebRtcHideLocalIpsWithMdns",
        "--disable-features=AllowPopupsDuringPageUnload",
        "--disable-features=BackForwardCache",
        "--disable-features=AvoidUnnecessaryBeforeUnloadCheckSync",
        "--disable-features=IntensiveWakeUpThrottling",
        "--disable-features=ThrottleDisplayNoneAndVisibilityHiddenCrossOriginIframes",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-features=TranslateUI",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--force-color-profile=srgb",
        "--metrics-recording-only",
        "--no-first-run",
        "--password-store=basic",
        "--use-mock-keychain",
        "--enable-features=NetworkService,NetworkServiceInProcess",
        "--lang=en-US",
    ]
    
    def __init__(self, run_mode: str = "AUTO"):
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
            logger.info("[MODE] AUTO FULL ENABLED")
            self.solver.auto_full = True
            
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.incident_manager = IncidentManager()
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        # [NEW] More realistic user agents with proper chrome versions
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        ]
        
        self.proxies = self._load_proxies()
        self.global_stats = SessionStats()
        self.ntp_sync.start_background_sync()
        
        logger.info(f"[ID] Session ID: {self.session_id}")
        logger.info(f"[OK] Initialization complete")

    def _validate_config(self):
        required = ['TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 'EMAIL', 'PASSPORT', 'PHONE']
        missing = [field for field in required if not getattr(Config, field, None)]
        if missing:
            raise ValueError(f"[ERR] Missing configuration: {', '.join(missing)}")
        logger.info("[OK] Configuration validated")

    def _prepare_base_url(self, url: str) -> str:
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url

    def _load_proxies(self) -> List[Optional[str]]:
        proxies = []
        if hasattr(Config, 'PROXIES') and Config.PROXIES:
            proxies.extend([p for p in Config.PROXIES if p])
        try:
            if os.path.exists("proxies.txt"):
                with open("proxies.txt") as f:
                    file_proxies = [line.strip() for line in f if line.strip()]
                    proxies.extend(file_proxies)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load proxies.txt: {e}")
        while len(proxies) < 3:
            proxies.append(None)
        return proxies[:3]

    def get_current_time_aden(self) -> datetime.datetime:
        corrected_utc = self.ntp_sync.get_corrected_time()
        aden_time = corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        return aden_time

    def is_pre_attack(self) -> bool:
        now = self.get_current_time_aden()
        return (now.hour == 1 and now.minute == Config.PRE_ATTACK_MINUTE and 
                now.second >= Config.PRE_ATTACK_SECOND)

    def is_attack_time(self) -> bool:
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES

    def get_sleep_interval(self) -> float:
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
        if self.is_attack_time():
            return "ATTACK"
        elif self.is_pre_attack():
            return "PRE_ATTACK"
        else:
            now = self.get_current_time_aden()
            if now.hour == 1 and now.minute >= 45:
                return "WARMUP"
            return "PATROL"

    def create_context(self, browser: Browser, worker_id: int, proxy: Optional[str] = None):
        try:
            role = SessionRole.SCOUT if worker_id == 1 else SessionRole.ATTACKER
            user_agent = random.choice(self.user_agents)
            viewport_width = 1920 + random.randint(-100, 100)
            viewport_height = 1080 + random.randint(-50, 50)
            
            context_args = {
                "user_agent": user_agent,
                "viewport": {"width": viewport_width, "height": viewport_height},
                "locale": "en-US",
                "timezone_id": "Asia/Aden",
                "ignore_https_errors": True,
                # [NEW] Additional context options for stealth
                "java_script_enabled": True,
                "bypass_csp": True,
                "permissions": ["notifications"],
            }
            
            if proxy:
                context_args["proxy"] = {"server": proxy}
                logger.info(f"[PROXY] [W{worker_id}] Using proxy: {proxy[:30]}...")
            
            context = browser.new_context(**context_args)
            page = context.new_page()
            
            # [NEW] Comprehensive stealth script
            page.add_init_script("""
                // Override navigator properties
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
                
                // Override chrome
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
                
                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                
                // WebGL fingerprint randomization
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris Xe Graphics';
                    return getParameter(parameter);
                };
                
                // Canvas fingerprint protection
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
                
                // Keep-alive heartbeat
                setInterval(() => {
                    fetch(location.href, { method: 'HEAD', cache: 'no-store' })
                        .catch(() => {});
                }, 30000);
            """)
            
            # [MODIFIED] Longer timeouts for slow connections
            context.set_default_timeout(60000)  # Increased from 25s
            context.set_default_navigation_timeout(90000)  # Increased from 30s
            
            # [MODIFIED] Less aggressive resource blocking
            def route_handler(route):
                resource_type = route.request.resource_type
                # Only block heavy resources, allow scripts and xhr
                if resource_type in ["image", "media", "font"]:
                    route.abort()
                else:
                    route.continue_()
            
            page.route("**/*", route_handler)
            
            # [NEW] Set extra headers to appear more legitimate
            page.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            })
            
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

    def validate_session_health(self, page: Page, session: SessionState, location: str = "UNKNOWN") -> bool:
        worker_id = session.worker_id
        
        if session.is_expired():
            logger.critical(f"[EXP] [W{worker_id}][{location}] Session EXPIRED")
            return False
        
        if session.should_terminate():
            logger.critical(f"💀 [W{worker_id}][{location}] Session POISONED")
            return False
        
        if session.captcha_solved:
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if has_captcha:
                logger.critical(f"💀 [W{worker_id}][{location}] DOUBLE CAPTCHA")
                session.health = SessionHealth.POISONED
                return False
        
        session.touch()
        return True

    def soft_recovery(self, session: SessionState, reason: str):
        logger.info(f"🔄 [W{session.worker_id}] Soft recovery: {reason}")
        session.consecutive_errors = 0
        session.failures = max(0, session.failures - 1)
        
        if session.health == SessionHealth.DEGRADED:
            session.health = SessionHealth.WARNING
        elif session.health == SessionHealth.WARNING:
            session.health = SessionHealth.CLEAN
        
        session.touch()
        logger.info(f"✅ [W{session.worker_id}] Soft recovery completed")

    def generate_month_urls(self) -> List[str]:
        try:
            today = datetime.datetime.now().date()
            base_clean = self.base_url.split("&dateStr=")[0] if "&dateStr=" in self.base_url else self.base_url
            
            urls = []
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

    def _human_type(self, page: Page, selector: str, value: str, worker_logger) -> bool:
        try:
            locator = page.locator(selector).first
            if not locator.is_visible():
                return False
            
            locator.click()
            locator.fill("")
            time.sleep(0.1)
            
            for char in value:
                locator.type(char, delay=random.randint(5, 15))
            
            page.evaluate(f"""
                const el = document.querySelector("{selector}");
                if(el) {{
                    el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            """)
            
            return True
        except Exception as e:
            worker_logger.debug(f"Human type error ({selector}): {e}")
            return False

    def _fill_booking_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        try:
            worker_logger.info("📝 Filling form...")
            
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
            ]
            
            for selector, value in fields:
                if not self._human_type(page, selector, value, worker_logger):
                    self._fast_inject(page, selector, value)
            
            if not self._human_type(page, "input[name='emailrepeat']", Config.EMAIL, worker_logger):
                self._human_type(page, "input[name='emailRepeat']", Config.EMAIL, worker_logger)
            
            phone_value = Config.PHONE.replace("+", "00").strip()
            
            passport_id = self._find_input_id_by_label(page, "Passport")
            if passport_id:
                self._human_type(page, f"#{passport_id}", Config.PASSPORT, worker_logger)
            else:
                self._human_type(page, "input[name='fields[0].content']", Config.PASSPORT, worker_logger)
            
            phone_id = self._find_input_id_by_label(page, "Telephone")
            if phone_id:
                self._human_type(page, f"#{phone_id}", phone_value, worker_logger)
            else:
                self._human_type(page, "input[name='fields[1].content']", phone_value, worker_logger)
            
            self._select_category(page, worker_logger)
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            self.debug_manager.save_debug_html(page, "form_filled", session.worker_id)
            worker_logger.info("✅ Form filled")
            return True
            
        except Exception as e:
            worker_logger.error(f"❌ Form fill error: {e}")
            return False

    def _find_input_id_by_label(self, page: Page, label_text: str) -> Optional[str]:
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

    def _select_category(self, page: Page, worker_logger):
        try:
            purpose = Config.PURPOSE.lower() if hasattr(Config, 'PURPOSE') and Config.PURPOSE else "aupair"
            purpose_value = Config.PURPOSE_VALUES.get(purpose, Config.DEFAULT_PURPOSE) if hasattr(Config, 'PURPOSE_VALUES') else "1"
            
            select_elem = page.locator("select[name='fields[2].content']").first
            if not select_elem.is_visible():
                select_elem = page.locator("select").first
            
            if select_elem.is_visible():
                select_elem.select_option(value=purpose_value)
                page.evaluate("""
                    const s = document.querySelector('select');
                    if(s) { s.dispatchEvent(new Event('change', { bubbles: true })); }
                """)
        except Exception as e:
            worker_logger.warning(f"Category selection warning: {e}")

    def _fast_inject(self, page: Page, selector: str, value: str) -> bool:
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
            return True
        except:
            return False

    def _submit_form(self, page: Page, session: SessionState, worker_logger) -> bool:
        worker_id = session.worker_id
        max_attempts = 15
        
        worker_logger.info(f"🚀 Starting submission...")

        for attempt in range(1, max_attempts + 1):
            try:
                content = page.content().lower()
                if any(term in content for term in ["appointment number", "termin nummer", "successfully booked"]):
                    worker_logger.critical("🏆 ALREADY SUCCESS!")
                    return self._handle_success_state(page, worker_id)

                if "beginnen sie den buchungsvorgang neu" in content:
                    worker_logger.error("❌ Session expired")
                    session.health = SessionHealth.CRITICAL
                    return False

                captcha_input = page.locator("input[name='captchaText']").first
                if not captcha_input.is_visible():
                    time.sleep(1)
                    continue

                current_val = captcha_input.input_value()
                if not current_val or len(current_val) < 4:
                    success, code, _ = self.solver.solve_from_page(page, f"SUBMIT_{attempt}")
                    if not success or not code:
                        worker_logger.warning("🔄 Captcha failed, refreshing...")
                        self._refresh_captcha(page)
                        time.sleep(1.5)
                        continue
                    
                    captcha_input.fill(code)
                    time.sleep(0.3)

                # Try submission methods
                submit_methods = [
                    ("Enter Key", lambda: self._submit_by_enter(page, captcha_input)),
                    ("Button Click", lambda: self._submit_by_button(page)),
                    ("JS Submit", lambda: self._submit_by_js(page)),
                ]
                
                for method_name, method_func in submit_methods:
                    worker_logger.info(f"⌨️ Attempt {attempt} using {method_name}...")
                    
                    try:
                        with page.expect_navigation(timeout=10000, wait_until="domcontentloaded"):
                            method_func()
                        
                        time.sleep(0.5)
                        if self._check_success(page, worker_logger):
                            return True
                            
                    except Exception as nav_err:
                        worker_logger.debug(f"{method_name} navigation: {nav_err}")
                        if self._check_success(page, worker_logger):
                            return True
                
                if page.locator("input[name='lastname']").is_visible():
                    worker_logger.warning(f"↩️ Bounced back (Attempt {attempt})")
                    
                    lastname_val = page.locator("input[name='lastname']").input_value()
                    if not lastname_val:
                        worker_logger.info("📝 Re-filling form...")
                        self._fill_booking_form(page, session, worker_logger)
                    
                    self._refresh_captcha(page)
                    time.sleep(1)
                    continue

            except Exception as e:
                worker_logger.error(f"⚠️ Submit error: {e}")
                time.sleep(1)
        
        return False

    def _submit_by_enter(self, page: Page, captcha_input):
        captcha_input.focus()
        captcha_input.press("Enter")

    def _submit_by_button(self, page: Page):
        submit_btn = page.locator("""
            #appointment_newAppointmentForm_appointment_addAppointment,
            input[name='action:appointment_addAppointment'],
            input[type='submit'][value='Submit']
        """).first
        submit_btn.click(timeout=5000)

    def _submit_by_js(self, page: Page):
        page.evaluate("""
            const form = document.getElementById('appointment_newAppointmentForm');
            if(form) {
                form.action = "extern/appointment_addAppointment.do";
                form.submit();
            } else {
                document.getElementsByName('appointment_newAppointmentForm')[0]?.submit();
            }
        """)

    def _refresh_captcha(self, page: Page):
        try:
            refresh_btn = page.locator("#appointment_newAppointmentForm_form_newappointment_refreshcaptcha").first
            if refresh_btn.is_visible():
                refresh_btn.click()
            else:
                self.solver.reload_captcha(page)
        except:
            pass

    def _check_success(self, page: Page, worker_logger) -> bool:
        try:
            content = page.content().lower()
            
            success_terms = ["appointment number", "termin nummer", "successfully booked", "ihre buchung"]
            for term in success_terms:
                if term in content:
                    worker_logger.critical(f"🏆 SUCCESS! Found: '{term}'")
                    return True
            
            return False
        except:
            return False

    def _handle_success_state(self, page: Page, worker_id: int) -> bool:
        self.global_stats.success = True
        self.debug_manager.save_critical_screenshot(page, "VICTORY", worker_id)
        self.debug_manager.save_debug_html(page, "SUCCESS", worker_id)
        
        try:
            send_success_notification(self.session_id, worker_id)
        except:
            pass
        
        self.stop_event.set()
        return True

    def _run_single_session(self, browser: Browser, worker_id: int):
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode")
        
        proxy = None
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        
        try:
            max_cycles = 100
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    break
                
                mode = self.get_mode()
                worker_logger.info(f"[CYCLE {cycle+1}] Mode: {mode}")
                
                month_urls = self.generate_month_urls()
                
                for i, url in enumerate(month_urls):
                    if self.stop_event.is_set():
                        break
                    
                    # [MODIFIED] Retry logic for navigation with exponential backoff
                    nav_success = False
                    for retry in range(3):
                        try:
                            worker_logger.info(f"[NAV] Attempt {retry+1}/3: {url[:60]}...")
                            
                            # [NEW] Pre-warm DNS and connection
                            page.goto("about:blank", timeout=5000)
                            
                            # [MODIFIED] Longer timeout and wait until load instead of domcontentloaded
                            page.goto(url, timeout=90000, wait_until="load")
                            session.touch()
                            self.global_stats.pages_loaded += 1
                            nav_success = True
                            worker_logger.info("[NAV] Success")
                            break
                            
                        except Exception as e:
                            worker_logger.warning(f"[NAV ERROR] Attempt {retry+1}: {e}")
                            wait_time = (2 ** retry) + random.uniform(0, 1)  # Exponential backoff
                            worker_logger.info(f"[NAV] Waiting {wait_time:.1f}s before retry...")
                            time.sleep(wait_time)
                    
                    if not nav_success:
                        worker_logger.error("[NAV] All retries failed, skipping URL")
                        continue
                    
                    if not self.validate_session_health(page, session, "MONTH"):
                        context.close()
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        break
                    
                    # Handle month captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, "MONTH")
                    if has_captcha:
                        success, code, status = self.solver.solve_from_page(page, "MONTH")
                        if success and code:
                            self.solver.submit_captcha(page, "enter")
                            page.wait_for_timeout(2000)
                            self.global_stats.captchas_solved += 1
                            session.mark_captcha_solved()
                        else:
                            self.global_stats.captchas_failed += 1
                            continue
                    
                    # Check for days
                    content = page.content().lower()
                    if "no appointments" in content:
                        continue
                    
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    if not day_links:
                        continue
                    
                    worker_logger.critical(f"[FOUND] {len(day_links)} days!")
                    self.global_stats.days_found += len(day_links)
                    
                    # Day page
                    first_href = day_links[0].get_attribute("href")
                    if not first_href:
                        continue
                    
                    base_domain = self.base_url.split("/extern")[0]
                    day_url = f"{base_domain}/{first_href}" if not first_href.startswith("http") else first_href
                    
                    try:
                        page.goto(day_url, timeout=60000, wait_until="domcontentloaded")
                        session.touch()
                    except Exception as e:
                        worker_logger.error(f"[DAY ERROR] {e}")
                        continue
                    
                    # Look for time slots
                    slot_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    if not slot_links:
                        continue
                    
                    worker_logger.critical(f"[SLOTS] {len(slot_links)} time slots!")
                    self.global_stats.slots_found += len(slot_links)
                    
                    # Form page
                    slot_href = slot_links[0].get_attribute("href")
                    if not slot_href:
                        continue
                    
                    slot_url = f"{base_domain}/{slot_href}" if not slot_href.startswith("http") else slot_href
                    
                    try:
                        page.goto(slot_url, timeout=60000, wait_until="domcontentloaded")
                        session.touch()
                    except Exception as e:
                        worker_logger.error(f"[FORM ERROR] {e}")
                        continue
                    
                    # Fill and submit
                    worker_logger.info("[FORM] Step 1: Filling form...")
                    if not self._fill_booking_form(page, session, worker_logger):
                        continue
                    
                    worker_logger.info("[FORM] Step 2: Solving captcha...")
                    has_captcha, _ = self.solver.safe_captcha_check(page, "FORM")
                    
                    if has_captcha:
                        success, code, status = self.solver.solve_from_page(page, "FORM_SUBMIT")
                        if not success or not code:
                            worker_logger.warning("[CAPTCHA] Failed")
                            continue
                        self.global_stats.captchas_solved += 1
                        session.mark_captcha_solved()
                    
                    worker_logger.info("[FORM] Step 3: Submitting...")
                    if self._submit_form(page, session, worker_logger):
                        return  # Success!
                
                # Sleep between cycles
                sleep_time = self.get_sleep_interval()
                time.sleep(sleep_time)
                
                # Session rebirth if old
                if session.age() > Config.SESSION_MAX_AGE:
                    context.close()
                    context, page, session = self.create_context(browser, worker_id, proxy)
                    
        except Exception as e:
            worker_logger.error(f"[FATAL] {e}", exc_info=True)
        finally:
            try:
                context.close()
            except:
                pass

    def run(self) -> bool:
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - STARTING")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info("=" * 70)
        
        try:
            send_alert(f"[Elite Sniper v{self.VERSION} Started]")
            
            with sync_playwright() as p:
                # [MODIFIED] Use stealth args and persistent context
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=self.STEALTH_ARGS,  # [NEW] Anti-detection args
                    timeout=120000,  # [NEW] Longer launch timeout
                )
                
                self._run_single_session(browser, 1)
                
                self.ntp_sync.stop_background_sync()
                browser.close()
                
                if self.global_stats.success:
                    self._handle_success()
                    return True
                else:
                    self._handle_completion()
                    return False
                    
        except KeyboardInterrupt:
            logger.info("[STOP] Manual stop")
            self.stop_event.set()
            return False
        except Exception as e:
            logger.error(f"💀 Critical error: {e}")
            return False

    def _handle_success(self):
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] MISSION ACCOMPLISHED!")
        logger.info("=" * 70)
        send_alert("ELITE SNIPER - SUCCESS! Appointment booked!")

    def _handle_completion(self):
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Completed without booking")
        logger.info("=" * 70)


if __name__ == "__main__":
    sniper = EliteSniperV2()
    success = sniper.run()
    sys.exit(0 if success else 1)
