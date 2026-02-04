"""
Elite Sniper v2.0 - Production-Grade Multi-Session Appointment Booking System
[PATCHED - State Machine + Silent Failure Fix]
"""

import time
import random
import datetime
import logging
import os
import sys
import re
from enum import Enum, auto
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


# =========================
# State Machine
# =========================
class BookingState(Enum):
    """حالات النظام - State Machine"""
    INIT = auto()
    MONTH_SELECTION = auto()
    CAPTCHA_MONTH = auto()      # فرعية
    DAY_SELECTION = auto()
    CAPTCHA_DAY = auto()        # فرعية
    TIME_SELECTION = auto()
    CAPTCHA_TIME = auto()       # فرعية
    FORM_READY = auto()         # نقطة اللاعودة
    FORM_FILLING = auto()
    CAPTCHA_FORM = auto()       # فرعية
    FORM_SUBMITTING = auto()
    SUCCESS = auto()
    FAILED = auto()


class SilentFailure(Exception):
    """فشل صامت - نعيد المحاولة فقط"""
    pass


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
        
        # State Machine
        self.current_state = BookingState.INIT
        self.form_submit_attempts = 0
        self.max_submit_attempts = 10
        
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
    
    # ==================== State Machine Helpers ====================
    
    def _transition_to(self, new_state: BookingState, reason: str = ""):
        """انتقال آمن بين الحالات"""
        old_state = self.current_state
        self.current_state = new_state
        logger.info(f"[STATE] {old_state.name} → {new_state.name} ({reason})")
        
        # قواعد خاصة بعد الفورم
        if old_state == BookingState.FORM_READY:
            logger.warning("🚨 وصلنا لنقطة اللاعودة - لا رجوع للكالندر!")
        
        return new_state
    
    def _is_allowed_transition(self, from_state: BookingState, to_state: BookingState) -> bool:
        """التحقق من صحة الانتقال"""
        
        # ممنوع الرجوع بعد الفورم
        if from_state in [
            BookingState.FORM_READY,
            BookingState.FORM_FILLING,
            BookingState.CAPTCHA_FORM,
            BookingState.FORM_SUBMITTING
        ]:
            if to_state in [
                BookingState.MONTH_SELECTION,
                BookingState.DAY_SELECTION,
                BookingState.TIME_SELECTION,
                BookingState.INIT
            ]:
                return False
        
        return True
    
    def _handle_captcha_safe(self, page: Page, location: str, session: SessionState) -> bool:
        """
        حل آمن للكابتشا - لا يسمم الجلسة
        """
        worker_id = session.worker_id
        logger.info(f"[CAPTCHA] معالجة آمنة في: {location}")
        
        try:
            # فحص الكابتشا بهدوء
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if not has_captcha:
                return True
            
            # حل الكابتشا
            success, code, captcha_status = self.solver.solve_from_page(page, location)
            
            # ⚠️ القاعدة: الكابتشا السوداء فقط = فشل
            if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                logger.error(f"[W{worker_id}] كابتشا سوداء - جلسة مسمومة")
                return False
            
            if success and code:
                # تقديم الكابتشا
                self.solver.submit_captcha(page, "enter")
                
                # انتظار قصير
                time.sleep(1)
                
                # ✅ لا نسمم الجلسة عند نجاح
                # ❌ لا نستدعي session.mark_captcha_solved()
                
                with self.lock:
                    self.global_stats.captchas_solved += 1
                
                logger.info(f"[W{worker_id}] كابتشا حُلّت: '{code}'")
                return True
            else:
                logger.warning(f"[W{worker_id}] فشل حل الكابتشا: {captcha_status}")
                with self.lock:
                    self.global_stats.captchas_failed += 1
                return False
                
        except Exception as e:
            logger.warning(f"[W{worker_id}] خطأ في معالجة الكابتشا: {e}")
            return False
    
    def _soft_validate_session(self, page: Page, session: SessionState, location: str) -> bool:
        """
        فحص جلسة ناعم - قبل الفورم فقط
        
        ⚠️ لا يقتل الجلسة إلا في حالات قاهرة
        """
        worker_id = session.worker_id
        
        # قاعدة 1: عمر الجلسة (فقط قبل الفورم)
        if self.current_state.value < BookingState.FORM_READY.value:
            if session.age() > Config.SESSION_MAX_AGE:
                logger.warning(f"[W{worker_id}] جلسة قديمة - إعادة إنشاء")
                return False
        
        # قاعدة 2: إخفاق متتالي (مخفف)
        if session.consecutive_errors >= 5:
            logger.warning(f"[W{worker_id}] أخطاء متتالية كثيرة")
            return False
        
        # قاعدة 3: Double Captcha - ❌ معطل قبل الفورم
        # لا نفحصها هنا
        
        session.touch()
        return True
    
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
    
    def fill_booking_form_humanized(self, page: Page, session: SessionState) -> bool:
        """
        ملء النموذج بطريقة إنسانية - تنشيط الأحداث المطلوبة
        """
        worker_id = session.worker_id
        logger.info(f"📝 [W{worker_id}] ملء النموذج (بطريقة إنسانية)...")
        
        try:
            # الحقول الأساسية
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
                ("input[name='emailRepeat']", Config.EMAIL),
            ]
            
            for selector, value in fields:
                try:
                    if page.locator(selector).count() > 0:
                        # التركيز أولاً
                        page.locator(selector).first.focus()
                        time.sleep(0.1)
                        
                        # مسح المحتوى القديم
                        page.locator(selector).first.fill("")
                        time.sleep(0.1)
                        
                        # الكتابة البشرية
                        page.locator(selector).first.type(value, delay=10)
                        time.sleep(0.1)
                        
                        # حدث blur لتثبيت القيمة
                        page.evaluate(f"""
                            document.querySelector("{selector}")?.blur();
                        """)
                        time.sleep(0.1)
                except:
                    continue
            
            # الحقول الديناميكية (جواز السفر والهاتف)
            phone_value = Config.PHONE.replace("+", "00").strip()
            
            # جواز السفر
            passport_selectors = [
                "input[name='fields[0].content']",
                "input[placeholder*='passport']",
                "input[placeholder*='Passport']",
            ]
            
            for selector in passport_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(Config.PASSPORT)
                        page.locator(selector).first.dispatch_event("change")
                        break
                except:
                    continue
            
            # الهاتف
            phone_selectors = [
                "input[name='fields[1].content']",
                "input[placeholder*='phone']",
                "input[placeholder*='Phone']",
            ]
            
            for selector in phone_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(phone_value)
                        page.locator(selector).first.dispatch_event("change")
                        break
                except:
                    continue
            
            # اختيار الفئة
            self.select_category_by_value(page)
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            # حفظ الأدلة
            self.debug_manager.save_debug_html(page, "form_filled_humanized", worker_id)
            
            logger.info(f"✅ [W{worker_id}] تم ملء النموذج بنجاح")
            return True
            
        except Exception as e:
            logger.error(f"❌ [W{worker_id}] خطأ في ملء النموذج: {e}")
            return False
    
    def submit_form_smart(self, page: Page, session: SessionState) -> bool:
        """
        تقديم ذكي للنموذج - يعالج الفشل الصامت
        """
        worker_id = session.worker_id
        
        # ننتقل لحالة الإرسال
        self._transition_to(BookingState.FORM_SUBMITTING, "بدء الإرسال")
        
        for attempt in range(1, self.max_submit_attempts + 1):
            logger.info(f"[SUBMIT] [W{worker_id}] محاولة {attempt}/{self.max_submit_attempts}")
            
            try:
                # 1. التحقق من وجود حقل الكابتشا
                captcha_input = page.locator("input[name='captchaText']").first
                if not captcha_input.is_visible():
                    # ربما نجح الإرسال السابق
                    content = page.content().lower()
                    if "appointment number" in content or "successfully" in content:
                        self._transition_to(BookingState.SUCCESS, "نجاح!")
                        return True
                    continue
                
                # 2. حل الكابتشا الحالية
                success, code, status = self.solver.solve_from_page(page, f"SUBMIT_{attempt}")
                if not success or not code:
                    logger.warning(f"[W{worker_id}] فشل حل الكابتشا، تحديث...")
                    
                    # تحديث الكابتشا
                    refresh_btn = page.locator("#appointment_newAppointmentForm_form_newappointment_refreshcaptcha")
                    if refresh_btn.is_visible():
                        refresh_btn.click()
                        time.sleep(1)
                    continue
                
                # 3. كتابة الكابتشا والضغط على Enter
                captcha_input.click()
                captcha_input.fill("")
                captcha_input.fill(code)
                time.sleep(0.5)  # استقرار
                
                # 4. الإرسال مع انتظار التنقل
                try:
                    with page.expect_navigation(timeout=10000):
                        page.keyboard.press("Enter")
                except:
                    pass  # قد لا يكون هناك تنقل
                
                # 5. انتظار الاستجابة
                time.sleep(2)
                
                # 6. تحليل النتيجة
                content = page.content().lower()
                
                # الحالة أ: النجاح
                if "appointment number" in content or "successfully" in content or "termin nummer" in content:
                    logger.critical(f"[W{worker_id}] 🏆 نجاح! تم الحجز!")
                    self._transition_to(BookingState.SUCCESS, "تأكيد النجاح")
                    
                    # حفظ الأدلة
                    self.debug_manager.save_critical_screenshot(page, "SUCCESS_FINAL", worker_id)
                    self.debug_manager.save_debug_html(page, "SUCCESS_FINAL", worker_id)
                    
                    # إرسال إشعار
                    try:
                        send_success_notification(self.session_id, worker_id, None)
                    except:
                        pass
                    
                    with self.lock:
                        self.global_stats.success = True
                    
                    self.stop_event.set()
                    return True
                
                # الحالة ب: الفشل الصارم (انتهت الجلسة)
                if "beginnen sie den buchungsvorgang neu" in content or "ref-id:" in content:
                    logger.error(f"[W{worker_id}] انتهت الجلسة")
                    self._transition_to(BookingState.FAILED, "جلسة منتهية")
                    return False
                
                # الحالة ج: الفشل الصامت (لا يزال في الفورم)
                lastname_input = page.locator("input[name='lastname']").first
                if lastname_input.is_visible():
                    logger.warning(f"[W{worker_id}] فشل صامت - إعادة المحاولة")
                    
                    # تحديث الكابتشا
                    refresh_btn = page.locator("#appointment_newAppointmentForm_form_newappointment_refreshcaptcha")
                    if refresh_btn.is_visible():
                        refresh_btn.click()
                        time.sleep(1)
                    
                    # إعادة ملء إذا تم مسح الحقول
                    if lastname_input.input_value() == "":
                        logger.info(f"[W{worker_id}] إعادة ملء الحقول...")
                        self.fill_booking_form_humanized(page, session)
                    
                    continue
                
                # حالة غير معروفة
                logger.warning(f"[W{worker_id}] حالة غير معروفة - حفظ الأدلة")
                self.debug_manager.save_debug_html(page, f"unknown_state_attempt_{attempt}", worker_id)
                
            except Exception as e:
                logger.error(f"[W{worker_id}] خطأ في المحاولة {attempt}: {e}")
                time.sleep(1)
        
        logger.error(f"[W{worker_id}] فشل جميع محاولات الإرسال")
        return False
    
    # ==================== State Machine Execution ====================
    
    def execute_state_machine(self, page: Page, session: SessionState) -> bool:
        """
        تنفيذ State Machine الرئيسية
        """
        worker_id = session.worker_id
        logger.info(f"[STATE] بدء State Machine [W{worker_id}]")
        
        while not self.stop_event.is_set() and self.current_state != BookingState.SUCCESS:
            try:
                # === STATE: INIT ===
                if self.current_state == BookingState.INIT:
                    # الانتقال للشهر الأول
                    month_urls = self.generate_month_urls()
                    if not month_urls:
                        logger.error("لا توجد روابط للشهور")
                        return False
                    
                    page.goto(month_urls[0], timeout=30000, wait_until="domcontentloaded")
                    self.global_stats.pages_loaded += 1
                    
                    self._transition_to(BookingState.MONTH_SELECTION, "تم التحميل")
                
                # === STATE: MONTH_SELECTION ===
                elif self.current_state == BookingState.MONTH_SELECTION:
                    # فحص الجلسة (ناعم)
                    if not self._soft_validate_session(page, session, "MONTH"):
                        return False
                    
                    # معالجة الكابتشا إذا وجدت
                    if not self._handle_captcha_safe(page, "MONTH", session):
                        # فشل في الكابتشا - نجرب شهر آخر
                        month_urls = self.generate_month_urls()
                        if len(month_urls) > 1:
                            page.goto(month_urls[1], timeout=30000)
                            continue
                    
                    # البحث عن أيام متاحة
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    if not day_links:
                        # لا توجد أيام - نجرب شهر آخر
                        month_urls = self.generate_month_urls()
                        current_url = page.url
                        for url in month_urls:
                            if url != current_url:
                                page.goto(url, timeout=30000)
                                break
                        continue
                    
                    # الانتقال للاختيار اليوم
                    first_href = day_links[0].get_attribute("href")
                    if first_href:
                        base_domain = self.base_url.split("/extern")[0]
                        day_url = f"{base_domain}/{first_href}"
                        page.goto(day_url, timeout=20000)
                        self.global_stats.days_found += 1
                        self._transition_to(BookingState.DAY_SELECTION, "وجدنا أياماً")
                
                # === STATE: DAY_SELECTION ===
                elif self.current_state == BookingState.DAY_SELECTION:
                    # فحص الجلسة (ناعم)
                    if not self._soft_validate_session(page, session, "DAY"):
                        return False
                    
                    # معالجة الكابتشا إذا وجدت
                    self._handle_captcha_safe(page, "DAY", session)
                    
                    # البحث عن أوقات متاحة
                    time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    if not time_links:
                        # لا توجد أوقات - نعود للشهر
                        self._transition_to(BookingState.MONTH_SELECTION, "لا توجد أوقات")
                        continue
                    
                    # الانتقال للوقت
                    first_href = time_links[0].get_attribute("href")
                    if first_href:
                        base_domain = self.base_url.split("/extern")[0]
                        time_url = f"{base_domain}/{first_href}"
                        page.goto(time_url, timeout=20000)
                        self.global_stats.slots_found += len(time_links)
                        self._transition_to(BookingState.TIME_SELECTION, "وجدنا أوقاتاً")
                
                # === STATE: TIME_SELECTION ===
                elif self.current_state == BookingState.TIME_SELECTION:
                    # فحص الجلسة (ناعم)
                    if not self._soft_validate_session(page, session, "TIME"):
                        return False
                    
                    # معالجة الكابتشا إذا وجدت
                    self._handle_captcha_safe(page, "TIME", session)
                    
                    # الانتقال للفورم
                    # نحن الآن في صفحة الفورم
                    self._transition_to(BookingState.FORM_READY, "وصلنا للفورم - نقطة اللاعودة")
                
                # === STATE: FORM_READY ===
                elif self.current_state == BookingState.FORM_READY:
                    # التحقق من وجود الفورم
                    if page.locator("input[name='lastname']").count() == 0:
                        logger.error("الفورم غير موجود")
                        return False
                    
                    # الانتقال لملء الفورم
                    self._transition_to(BookingState.FORM_FILLING, "بدء ملء الفورم")
                
                # === STATE: FORM_FILLING ===
                elif self.current_state == BookingState.FORM_FILLING:
                    # ملء النموذج
                    if not self.fill_booking_form_humanized(page, session):
                        logger.error("فشل ملء النموذج")
                        return False
                    
                    # الانتقال لكابتشا الفورم
                    self._transition_to(BookingState.CAPTCHA_FORM, "الفورم ممتلئ")
                
                # === STATE: CAPTCHA_FORM ===
                elif self.current_state == BookingState.CAPTCHA_FORM:
                    # حل كابتشا الفورم
                    success, code, status = self.solver.solve_from_page(page, "FORM_CAPTCHA")
                    if success and code:
                        # كتابة الكابتشا
                        captcha_input = page.locator("input[name='captchaText']").first
                        captcha_input.fill(code)
                        
                        # الانتقال للإرسال
                        self._transition_to(BookingState.FORM_SUBMITTING, "كابتشا الفورم جاهزة")
                    else:
                        logger.warning("فشل حل كابتشا الفورم")
                        continue
                
                # === STATE: FORM_SUBMITTING ===
                elif self.current_state == BookingState.FORM_SUBMITTING:
                    # تنفيذ الإرسال الذكي
                    if self.submit_form_smart(page, session):
                        return True  # نجاح!
                    else:
                        # فشل في الإرسال - نعيد المحاولة
                        self.form_submit_attempts += 1
                        if self.form_submit_attempts > 3:
                            logger.error("فشل متكرر في الإرسال")
                            return False
                        
                        # نعود لكابتشا الفورم
                        self._transition_to(BookingState.CAPTCHA_FORM, "إعادة المحاولة")
                
                # انتظار قصير بين الحالات
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"[STATE] خطأ في State Machine: {e}")
                # نعود لحالة INIT في حال خطأ كبير
                if self.current_state.value < BookingState.FORM_READY.value:
                    self._transition_to(BookingState.INIT, "خطأ - إعادة البدء")
                time.sleep(2)
        
        return self.current_state == BookingState.SUCCESS
    
    # ==================== Single Session Mode ====================
    
    def _run_single_session(self, browser: Browser, worker_id: int):
        """
        Single session mode with State Machine
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode with State Machine")
        
        # Proxy configuration
        proxy = None  # Disabled for testing
        
        # Create context and page
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        
        worker_logger.info(f"[INIT] Session {session.session_id} created")
        
        try:
            # تنفيذ State Machine
            success = self.execute_state_machine(page, session)
            
            if success:
                worker_logger.critical("[SUCCESS] تم الحجز بنجاح!")
            else:
                worker_logger.error("[FAILED] فشل في الحجز")
                
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
        logger.info("[MODE] Single Session with State Machine")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info(f"[CURRENT TIME] Aden: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # Send startup notification
            send_alert(
                f"[Elite Sniper v{self.VERSION} Started]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Session with State Machine\n"
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