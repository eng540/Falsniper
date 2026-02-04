"""
Elite Sniper v2.0 - Production-Grade Multi-Session Appointment Booking System
[FIXED - Connection Handling + State Machine Fix]
"""

import time
import random
import datetime
import logging
import os
import sys
from enum import Enum, auto
from typing import List, Tuple, Optional
from threading import Event, Lock

import pytz
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, TimeoutError

# Internal imports
from .config import Config
from .ntp_sync import NTPTimeSync
from .session_state import SessionState, SessionStats, SessionRole, SessionHealth
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


class BookingState(Enum):
    """State Machine States"""
    INIT = auto()
    MONTH_SELECTION = auto()
    DAY_SELECTION = auto()
    TIME_SELECTION = auto()
    FORM_READY = auto()         # نقطة اللاعودة
    FORM_FILLING = auto()
    FORM_SUBMITTING = auto()
    SUCCESS = auto()
    FAILED = auto()
    CONNECTION_ERROR = auto()   # حالة جديدة: خطأ اتصال


class EliteSniperV2:
    VERSION = "2.0.0"
    
    def __init__(self, run_mode: str = "AUTO"):
        self.run_mode = run_mode
        logger.info(f"[INIT] ELITE SNIPER V{self.VERSION}")
        
        self._validate_config()
        self.session_id = f"elite_v2_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        self.stop_event = Event()
        self.lock = Lock()
        
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full:
            self.solver.auto_full = True
        
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        
        self.proxies = self._load_proxies()
        self.global_stats = SessionStats()
        self.ntp_sync.start_background_sync()
        
        # State Machine
        self.current_state = BookingState.INIT
        self.form_submit_attempts = 0
        self.max_submit_attempts = 10
        self.connection_retries = 0
        self.max_connection_retries = 3
    
    # ==================== Configuration ====================
    
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
        while len(proxies) < 3:
            proxies.append(None)
        return proxies[:3]
    
    # ==================== Time Management ====================
    
    def get_current_time_aden(self) -> datetime.datetime:
        corrected_utc = self.ntp_sync.get_corrected_time()
        return corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
    
    def is_attack_time(self) -> bool:
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def get_sleep_interval(self) -> float:
        if self.is_attack_time():
            return random.uniform(Config.ATTACK_SLEEP_MIN, Config.ATTACK_SLEEP_MAX)
        return random.uniform(Config.PATROL_SLEEP_MIN, Config.PATROL_SLEEP_MAX)
    
    # ==================== Session Management ====================
    
    def create_context(self, browser: Browser, worker_id: int, proxy: Optional[str] = None):
        try:
            role = SessionRole.SCOUT if worker_id == 1 else SessionRole.ATTACKER
            user_agent = random.choice(self.user_agents)
            
            context_args = {
                "user_agent": user_agent,
                "viewport": {"width": 1366, "height": 768},
                "locale": "en-US",
                "timezone_id": "Asia/Aden",
                "ignore_https_errors": True
            }
            
            if proxy:
                context_args["proxy"] = {"server": proxy}
                logger.info(f"[PROXY] [W{worker_id}] Using proxy: {proxy[:30]}...")
            
            context = browser.new_context(**context_args)
            page = context.new_page()
            
            # Anti-detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)
            
            # Timeouts
            context.set_default_timeout(45000)  # زادنا المهلة
            context.set_default_navigation_timeout(50000)
            
            # Block unnecessary resources
            def route_handler(route):
                resource_type = route.request.resource_type
                if resource_type in ["image", "media", "font", "stylesheet"]:
                    route.abort()
                else:
                    route.continue_()
            
            page.route("**/*", route_handler)
            
            session_state = SessionState(
                session_id=f"{self.session_id}_w{worker_id}",
                role=role,
                worker_id=worker_id,
                max_age=Config.SESSION_MAX_AGE,
                max_idle=Config.SESSION_MAX_IDLE,
                max_failures=Config.MAX_CONSECUTIVE_ERRORS,
                max_captcha_attempts=Config.MAX_CAPTCHA_ATTEMPTS
            )
            
            logger.info(f"[CTX] [W{worker_id}] Context created")
            with self.lock:
                self.global_stats.rebirths += 1
            
            return context, page, session_state
            
        except Exception as e:
            logger.error(f"[ERR] [W{worker_id}] Context creation failed: {e}")
            raise
    
    # ==================== Navigation & Form Filling ====================
    
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
    
    def safe_navigate(self, page: Page, url: str, timeout: int = 40000) -> bool:
        """تنقل آمن مع معالجة الأخطاء"""
        try:
            logger.info(f"[NAV] Navigating to: {url[:80]}...")
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            time.sleep(2)  # استقرار الصفحة
            return True
        except TimeoutError:
            logger.warning(f"[NAV] Timeout for: {url[:60]}...")
            return False
        except Exception as e:
            logger.error(f"[NAV] Error navigating: {e}")
            return False
    
    def handle_captcha_safe(self, page: Page, location: str, session: SessionState) -> bool:
        """معالجة كابتشا آمنة"""
        worker_id = session.worker_id
        
        try:
            # فحص الكابتشا
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if not has_captcha:
                return True
            
            logger.info(f"[CAPTCHA] Solving {location} captcha...")
            
            # حل الكابتشا
            success, code, captcha_status = self.solver.solve_from_page(page, location)
            
            # كابتشا سوداء = فشل
            if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                logger.error(f"[W{worker_id}] Black captcha detected")
                return False
            
            if success and code:
                # إدخال الكابتشا
                captcha_input = page.locator("input[name='captchaText']").first
                if captcha_input.is_visible():
                    captcha_input.fill(code)
                    time.sleep(0.5)
                    
                    # الضغط على Enter
                    captcha_input.press("Enter")
                    time.sleep(2)
                    
                    with self.lock:
                        self.global_stats.captchas_solved += 1
                    
                    logger.info(f"[W{worker_id}] Captcha solved: '{code}'")
                    return True
            
            logger.warning(f"[W{worker_id}] Captcha solve failed")
            with self.lock:
                self.global_stats.captchas_failed += 1
            return False
            
        except Exception as e:
            logger.warning(f"[W{worker_id}] Captcha handling error: {e}")
            return False
    
    def fill_booking_form_humanized(self, page: Page, session: SessionState) -> bool:
        """ملء النموذج بطريقة إنسانية"""
        worker_id = session.worker_id
        logger.info(f"[FORM] [W{worker_id}] Filling form...")
        
        try:
            # الحقول الأساسية
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
            ]
            
            for selector, value in fields:
                try:
                    if page.locator(selector).count() > 0:
                        # تركيز وملء
                        page.locator(selector).first.focus()
                        time.sleep(0.1)
                        page.locator(selector).first.fill(value)
                        time.sleep(0.1)
                        # حدث blur
                        page.evaluate(f"document.querySelector('{selector}')?.blur()")
                except:
                    continue
            
            # جواز السفر
            try:
                passport_field = page.locator("input[name='fields[0].content']").first
                if passport_field.is_visible():
                    passport_field.fill(Config.PASSPORT)
            except:
                pass
            
            # الهاتف
            try:
                phone_field = page.locator("input[name='fields[1].content']").first
                if phone_field.is_visible():
                    phone_value = Config.PHONE.replace("+", "00").strip()
                    phone_field.fill(phone_value)
            except:
                pass
            
            # اختيار الفئة
            try:
                selects = page.locator("select").all()
                for select in selects:
                    options = select.locator("option").all()
                    if len(options) > 1:
                        select.select_option(index=1)
                        break
            except:
                pass
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            logger.info(f"[FORM] [W{worker_id}] Form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"[FORM] [W{worker_id}] Form fill error: {e}")
            return False
    
    def submit_form_smart(self, page: Page, session: SessionState) -> bool:
        """إرسال ذكي للنموذج"""
        worker_id = session.worker_id
        
        for attempt in range(1, self.max_submit_attempts + 1):
            logger.info(f"[SUBMIT] [W{worker_id}] Attempt {attempt}/{self.max_submit_attempts}")
            
            try:
                # 1. حل كابتشا الفورم إن وجدت
                self.handle_captcha_safe(page, f"FORM_SUBMIT_{attempt}", session)
                
                # 2. الضغط على Enter
                captcha_input = page.locator("input[name='captchaText']").first
                if captcha_input.is_visible():
                    captcha_input.press("Enter")
                
                # 3. انتظار النتيجة
                time.sleep(3)
                
                # 4. تحليل النتيجة
                content = page.content().lower()
                
                # النجاح
                if "appointment number" in content or "successfully" in content:
                    logger.critical(f"[SUCCESS] [W{worker_id}] 🏆 APPOINTMENT BOOKED!")
                    
                    self.debug_manager.save_critical_screenshot(page, "SUCCESS", worker_id)
                    
                    with self.lock:
                        self.global_stats.success = True
                    
                    # إشعار
                    try:
                        send_success_notification(self.session_id, worker_id, None)
                    except:
                        pass
                    
                    return True
                
                # فشل صريح
                if "beginnen sie den buchungsvorgang neu" in content:
                    logger.error(f"[FAIL] [W{worker_id}] Session expired")
                    return False
                
                # فشل صامت - لا يزال في الفورم
                if page.locator("input[name='lastname']").is_visible():
                    logger.warning(f"[RETRY] [W{worker_id}] Silent failure - retrying")
                    time.sleep(1)
                    continue
                
                # حالة غير معروفة
                logger.warning(f"[UNKNOWN] [W{worker_id}] Unknown state")
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"[ERROR] [W{worker_id}] Submit error: {e}")
                time.sleep(1)
        
        logger.error(f"[FAIL] [W{worker_id}] All submit attempts failed")
        return False
    
    # ==================== State Machine Execution ====================
    
    def execute_state_machine(self, page: Page, session: SessionState) -> bool:
        """تنفيذ State Machine محسّنة"""
        worker_id = session.worker_id
        logger.info(f"[STATE] Starting State Machine [W{worker_id}]")
        
        # إعادة تعيين عداد الاتصال
        self.connection_retries = 0
        
        while not self.stop_event.is_set():
            try:
                # === STATE: INIT ===
                if self.current_state == BookingState.INIT:
                    logger.info(f"[STATE] [W{worker_id}] State: INIT")
                    
                    # توليد روابط الشهور
                    month_urls = self.generate_month_urls()
                    if not month_urls:
                        logger.error("[STATE] No month URLs generated")
                        self.current_state = BookingState.FAILED
                        return False
                    
                    # تجربة الروابط بالترتيب
                    for url in month_urls:
                        if self.safe_navigate(page, url):
                            self.global_stats.pages_loaded += 1
                            self.current_state = BookingState.MONTH_SELECTION
                            logger.info(f"[STATE] [W{worker_id}] INIT → MONTH_SELECTION")
                            break
                        else:
                            self.connection_retries += 1
                            if self.connection_retries >= self.max_connection_retries:
                                logger.error("[STATE] Max connection retries reached")
                                self.current_state = BookingState.CONNECTION_ERROR
                                return False
                            time.sleep(5)  # انتظار قبل إعادة المحاولة
                    
                    # إذا فشل كل شيء
                    if self.current_state == BookingState.INIT:
                        self.current_state = BookingState.CONNECTION_ERROR
                        return False
                
                # === STATE: MONTH_SELECTION ===
                elif self.current_state == BookingState.MONTH_SELECTION:
                    logger.info(f"[STATE] [W{worker_id}] State: MONTH_SELECTION")
                    
                    # معالجة كابتشا الشهر
                    self.handle_captcha_safe(page, "MONTH", session)
                    
                    # البحث عن أيام متاحة
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    
                    if day_links:
                        # الانتقال لأول يوم
                        first_href = day_links[0].get_attribute("href")
                        if first_href:
                            base_domain = self.base_url.split("/extern")[0]
                            day_url = f"{base_domain}/{first_href}"
                            
                            if self.safe_navigate(page, day_url):
                                self.global_stats.days_found += 1
                                self.current_state = BookingState.DAY_SELECTION
                                logger.info(f"[STATE] [W{worker_id}] MONTH → DAY (found {len(day_links)} days)")
                            else:
                                self.current_state = BookingState.INIT  # نعيد من البداية
                        else:
                            self.current_state = BookingState.INIT
                    else:
                        # لا توجد أيام - نعود للبداية
                        logger.info("[STATE] No days found, returning to INIT")
                        self.current_state = BookingState.INIT
                
                # === STATE: DAY_SELECTION ===
                elif self.current_state == BookingState.DAY_SELECTION:
                    logger.info(f"[STATE] [W{worker_id}] State: DAY_SELECTION")
                    
                    # معالجة كابتشا اليوم
                    self.handle_captcha_safe(page, "DAY", session)
                    
                    # البحث عن أوقات متاحة
                    time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    
                    if time_links:
                        # الانتقال لأول وقت
                        first_href = time_links[0].get_attribute("href")
                        if first_href:
                            base_domain = self.base_url.split("/extern")[0]
                            time_url = f"{base_domain}/{first_href}"
                            
                            if self.safe_navigate(page, time_url):
                                self.global_stats.slots_found += len(time_links)
                                self.current_state = BookingState.TIME_SELECTION
                                logger.info(f"[STATE] [W{worker_id}] DAY → TIME (found {len(time_links)} slots)")
                            else:
                                self.current_state = BookingState.INIT
                        else:
                            self.current_state = BookingState.INIT
                    else:
                        # لا توجد أوقات - نعود للشهر
                        logger.info("[STATE] No time slots found, returning to INIT")
                        self.current_state = BookingState.INIT
                
                # === STATE: TIME_SELECTION ===
                elif self.current_state == BookingState.TIME_SELECTION:
                    logger.info(f"[STATE] [W{worker_id}] State: TIME_SELECTION (POINT OF NO RETURN)")
                    
                    # معالجة كابتشا الوقت
                    self.handle_captcha_safe(page, "TIME", session)
                    
                    # التحقق من وجود الفورم
                    if page.locator("input[name='lastname']").count() > 0:
                        self.current_state = BookingState.FORM_READY
                        logger.info(f"[STATE] [W{worker_id}] TIME → FORM_READY")
                    else:
                        logger.error("[STATE] Form not found after time selection")
                        self.current_state = BookingState.INIT
                
                # === STATE: FORM_READY ===
                elif self.current_state == BookingState.FORM_READY:
                    logger.info(f"[STATE] [W{worker_id}] State: FORM_READY")
                    
                    # ملء النموذج
                    if self.fill_booking_form_humanized(page, session):
                        self.current_state = BookingState.FORM_SUBMITTING
                        logger.info(f"[STATE] [W{worker_id}] FORM_READY → FORM_SUBMITTING")
                    else:
                        logger.error("[STATE] Form fill failed")
                        self.current_state = BookingState.FAILED
                        return False
                
                # === STATE: FORM_SUBMITTING ===
                elif self.current_state == BookingState.FORM_SUBMITTING:
                    logger.info(f"[STATE] [W{worker_id}] State: FORM_SUBMITTING")
                    
                    # الإرسال الذكي
                    if self.submit_form_smart(page, session):
                        self.current_state = BookingState.SUCCESS
                        logger.info(f"[STATE] [W{worker_id}] FORM_SUBMITTING → SUCCESS")
                        return True
                    else:
                        # فشل الإرسال
                        self.form_submit_attempts += 1
                        
                        if self.form_submit_attempts >= 3:
                            logger.error("[STATE] Max form submit attempts reached")
                            self.current_state = BookingState.FAILED
                            return False
                        else:
                            # إعادة المحاولة بدون تغيير الحالة
                            logger.info(f"[STATE] Retry submit ({self.form_submit_attempts}/3)")
                            continue
                
                # === STATE: SUCCESS ===
                elif self.current_state == BookingState.SUCCESS:
                    logger.info(f"[STATE] [W{worker_id}] State: SUCCESS")
                    return True
                
                # === STATE: FAILED ===
                elif self.current_state == BookingState.FAILED:
                    logger.info(f"[STATE] [W{worker_id}] State: FAILED")
                    return False
                
                # === STATE: CONNECTION_ERROR ===
                elif self.current_state == BookingState.CONNECTION_ERROR:
                    logger.error(f"[STATE] [W{worker_id}] State: CONNECTION_ERROR")
                    return False
                
                # انتظار قصير بين الحالات
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"[STATE] [W{worker_id}] State Machine error: {e}")
                
                # في حالة خطأ، نعود للبداية لكن مع حد أقصى
                if self.connection_retries >= self.max_connection_retries:
                    self.current_state = BookingState.CONNECTION_ERROR
                    return False
                
                self.current_state = BookingState.INIT
                time.sleep(3)
        
        return False
    
    # ==================== Single Session Mode ====================
    
    def _run_single_session(self, browser: Browser, worker_id: int):
        """Single session mode"""
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode")
        
        # لا بروكسي للاختبار
        proxy = None
        
        # إنشاء الجلسة
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        
        try:
            # تنفيذ State Machine
            success = self.execute_state_machine(page, session)
            
            if success:
                worker_logger.critical("[SUCCESS] Appointment booked!")
            else:
                worker_logger.error("[FAILED] Booking failed")
                
        except Exception as e:
            worker_logger.error(f"[FATAL] Session error: {e}", exc_info=True)
        
        finally:
            try:
                context.close()
            except:
                pass
            worker_logger.info("[END] Session closed")
    
    # ==================== Main Entry Point ====================
    
    def run(self) -> bool:
        """Main execution"""
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER V{self.VERSION}] - STARTING")
        logger.info("[MODE] Single Session")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info(f"[CURRENT TIME] Aden: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # Startup notification
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
                
                # Single session
                worker_id = 1
                
                try:
                    self._run_single_session(browser, worker_id)
                except Exception as e:
                    logger.error(f"[SESSION ERROR] {e}")
                
                # Cleanup
                self.ntp_sync.stop_background_sync()
                browser.close()
                
                # Save stats
                final_stats = self.global_stats.to_dict()
                self.debug_manager.save_stats(final_stats, "final_stats.json")
                
                if self.global_stats.success:
                    self._handle_success()
                    return True
                else:
                    self._handle_completion()
                    return False
                
        except KeyboardInterrupt:
            logger.info("\n[STOP] Manual stop")
            self.stop_event.set()
            self.ntp_sync.stop_background_sync()
            send_alert("⏸️ Elite Sniper stopped manually")
            return False
            
        except Exception as e:
            logger.error(f"💀 Critical error: {e}", exc_info=True)
            send_alert(f"🚨 Critical error: {str(e)[:200]}")
            return False
    
    def _handle_success(self):
        """Handle success"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] BOOKING SUCCESSFUL!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"ELITE SNIPER V2.0 - SUCCESS!\n"
            f"[+] Appointment booked!\n"
            f"Session: {self.session_id}\n"
            f"Runtime: {runtime:.0f}s"
        )
    
    def _handle_completion(self):
        """Handle completion"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Session completed")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        logger.info(f"[TIME] Runtime: {runtime:.0f}s")


# Entry point
if __name__ == "__main__":
    sniper = EliteSniperV2()
    success = sniper.run()
    sys.exit(0 if success else 1)