"""
Elite Sniper v2.0 - النسخة المصححة السلوكية
تطبيق حرفي للقواعد التنفيذية من التقرير التشخيصي
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
        logging.FileHandler('elite_sniper_v2_corrected.log')
    ]
)
logger = logging.getLogger("EliteSniperV2.Corrected")


class EliteSniperV2Corrected:
    """
    النسخة المصححة: جلسة واحدة، سلوك بشري، تدفق طبيعي
    """
    
    VERSION = "2.0.1.CORRECTED"
    
    def __init__(self, run_mode: str = "AUTO"):
        """تهيئة النسخة المصححة"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER {self.VERSION} - النسخة المصححة")
        logger.info(f"[MODE] {self.run_mode}")
        logger.info("=" * 70)
        
        # التحقق من الإعدادات
        self._validate_config()
        
        # إدارة الجلسة
        self.session_id = f"corrected_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        # حالة النظام
        self.stop_event = Event()
        self.lock = Lock()
        
        # المكونات
        self.solver = EnhancedCaptchaSolver(manual_only=(self.run_mode == "MANUAL"))
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        
        # التكوين
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        # إحصائيات
        self.stats = SessionStats()
        
        # بدء مزامنة الوقت
        self.ntp_sync.start_background_sync()
        
        logger.info(f"[ID] {self.session_id}")
        logger.info(f"[URL] {self.base_url[:60]}...")
        logger.info(f"[TZ] {self.timezone}")
        logger.info(f"[NTP] Offset: {self.ntp_sync.offset:.4f}s")
        logger.info("[OK] التهيئة مكتملة")
    
    def _validate_config(self):
        """التحقق من الإعدادات المطلوبة"""
        required = [
            'TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 
            'EMAIL', 'PASSPORT', 'PHONE'
        ]
        
        missing = [field for field in required if not getattr(Config, field, None)]
        
        if missing:
            raise ValueError(f"[ERR] Missing config: {', '.join(missing)}")
        
        logger.info("[OK] الإعدادات صالحة")
    
    def _prepare_base_url(self, url: str) -> str:
        """تحضير الرابط الأساسي"""
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url
    
    def get_current_time_aden(self) -> datetime.datetime:
        """الحصول على الوقت الحالي في عدن"""
        corrected_utc = self.ntp_sync.get_corrected_time()
        aden_time = corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        return aden_time
    
    def is_attack_time(self) -> bool:
        """التحقق من وقت الهجوم"""
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def create_natural_context(self, browser: Browser) -> Tuple[Page, SessionState]:
        """
        إنشاء سياق طبيعي بسلوك بشري
        
        القاعدة 1: جلسة واحدة = قصة واحدة
        """
        try:
            # إنشاء context مع سلوك بشري
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Aden",
                ignore_https_errors=True
            )
            
            # إضافة سكريبت لإخفاء الأدلة الأوتوماتيكية
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { 
                    get: () => undefined 
                });
                
                // Heartbeat بسيط
                setInterval(() => {
                    fetch(location.href, { method: 'HEAD' }).catch(()=>{});
                }, 30000);
            """)
            
            # ضبط المهلات
            context.set_default_timeout(30000)
            context.set_default_navigation_timeout(40000)
            
            # إنشاء حالة الجلسة
            session = SessionState(
                session_id=self.session_id,
                role=None,
                worker_id=1,
                max_age=Config.SESSION_MAX_AGE,
                max_idle=Config.SESSION_MAX_IDLE,
                max_failures=10,  # متساهل
                max_captcha_attempts=10
            )
            
            logger.info("[CTX] الجلسة المنشأة - سلوك بشري")
            
            with self.lock:
                self.stats.rebirths += 1
            
            return page, session
            
        except Exception as e:
            logger.error(f"[ERR] فشل إنشاء السياق: {e}")
            raise
    
    def human_type(self, page: Page, selector: str, text: str) -> bool:
        """
        الكتابة البشرية حرفًا حرفًا
        
        القاعدة 4: الإدخال يجب أن يكون حدثيًا
        """
        try:
            locator = page.locator(selector).first
            if not locator.is_visible():
                logger.debug(f"[TYPE] العنصر غير مرئي: {selector}")
                return False
            
            # 1. التركيز
            locator.click()
            time.sleep(0.1)
            
            # 2. مسح المحتوى القديم
            locator.fill("")
            time.sleep(0.1)
            
            # 3. الكتابة حرفًا حرفًا
            for char in text:
                locator.type(char, delay=random.uniform(20, 50))
                time.sleep(random.uniform(0.01, 0.03))
            
            # 4. الخروج من الحقل
            page.evaluate(f"""
                document.querySelector("{selector}")?.blur();
            """)
            
            time.sleep(0.2)
            return True
            
        except Exception as e:
            logger.warning(f"[TYPE] خطأ في الكتابة: {e}")
            return False
    
    def human_click(self, page: Page, selector: str) -> bool:
        """
        نقر بشري
        
        القاعدة 5: Click في صفحات التقويم
        """
        try:
            locator = page.locator(selector).first
            if not locator.is_visible(timeout=2000):
                return False
            
            # نقر بشري مع حركة عشوائية
            locator.click(delay=random.uniform(50, 150))
            return True
            
        except Exception as e:
            logger.debug(f"[CLICK] خطأ في النقر: {e}")
            return False
    
    def navigate_with_patience(self, page: Page, url: str, location: str) -> bool:
        """
        الانتقال بصبر
        
        القاعدة 6: لا تحقق أثناء الانتقال
        """
        try:
            logger.info(f"[NAV] {location} → {url[:80]}...")
            
            # الانتقال مع انتظار الاستقرار
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # انتظار إضافي للاستقرار
            time.sleep(2)
            
            with self.lock:
                self.stats.pages_loaded += 1
            
            return True
            
        except Exception as e:
            logger.warning(f"[NAV] خطأ في الانتقال إلى {location}: {e}")
            return False
    
    def handle_month_captcha(self, page: Page, session: SessionState) -> bool:
        """
        معالجة كابتشا الشهر بهدوء
        
        القاعدة 3: الكابتشا لا تغيّر الحالة
        """
        try:
            # التحقق بهدوء
            has_captcha, _ = self.solver.safe_captcha_check(page, "MONTH")
            
            if not has_captcha:
                return True  # لا توجد كابتشا، استمر
            
            logger.info("[CAPTCHA] كابتشا شهر - حل بهدوء...")
            
            # الحل بهدوء
            success, code, status = self.solver.solve_from_page(
                page, "MONTH", 
                session_age=session.age(),
                attempt=1,
                max_attempts=3
            )
            
            if not success or not code:
                logger.warning(f"[CAPTCHA] فشل حل كابتشا الشهر: {status}")
                return False
            
            # الإدخال البشري للكابتشا
            captcha_input = page.locator("input[name='captchaText']").first
            if captcha_input.is_visible():
                captcha_input.click()
                captcha_input.fill("")
                self.human_type(page, "input[name='captchaText']", code)
                
                # النقر على زر الإرسال (ليس Enter!)
                submit_btn = page.locator("input[type='submit']").first
                if submit_btn.is_visible():
                    self.human_click(page, "input[type='submit']")
                else:
                    # Fallback: Enter فقط إذا لم يكن هناك زر
                    page.keyboard.press("Enter")
                
                # انتظار الاستجابة بهدوء
                time.sleep(3)
                
                # التحقق بهدوء
                solved, _ = self.solver.verify_captcha_solved(page, "MONTH_VERIFY")
                if solved:
                    logger.info(f"[CAPTCHA] تم حل كابتشا الشهر: '{code}'")
                    session.mark_captcha_solved()
                    return True
                else:
                    logger.warning("[CAPTCHA] كابتشا الشهر فشلت بعد الإرسال")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"[CAPTCHA] خطأ في معالجة كابتشا الشهر: {e}")
            return False
    
    def scan_month_for_days(self, page: Page, url: str, session: SessionState) -> Optional[str]:
        """
        فحص الشهر بحثًا عن أيام متاحة
        
        تدفق طبيعي: شهر → يوم
        """
        try:
            # الانتقال إلى صفحة الشهر
            if not self.navigate_with_patience(page, url, "MONTH"):
                return None
            
            # معالجة كابتشا الشهر بهدوء
            if not self.handle_month_captcha(page, session):
                return None
            
            # التحقق من وجود "لا توجد مواعيد"
            content = page.content().lower()
            if "no appointments" in content or "keine termine" in content:
                logger.debug("[SCAN] لا توجد مواعيد في هذا الشهر")
                return None
            
            # البحث عن أيام متاحة
            day_selectors = [
                "a.arrow[href*='appointment_showDay']",
                "td.buchbar a",
                "a[href*='showDay']"
            ]
            
            for selector in day_selectors:
                day_links = page.locator(selector).all()
                if day_links:
                    num_days = len(day_links)
                    logger.critical(f"[FOUND] {num_days} يوم متاح!")
                    
                    with self.lock:
                        self.stats.days_found += num_days
                    
                    # العودة مع رابط اليوم الأول
                    first_href = day_links[0].get_attribute("href")
                    if first_href:
                        base_domain = self.base_url.split("/extern")[0]
                        return f"{base_domain}/{first_href}"
            
            return None
            
        except Exception as e:
            logger.warning(f"[SCAN] خطأ في فحص الشهر: {e}")
            return None
    
    def scan_day_for_times(self, page: Page, day_url: str, session: SessionState) -> Optional[str]:
        """
        فحص اليوم بحثًا عن أوقات متاحة
        
        تدفق طبيعي: يوم → وقت
        """
        try:
            # الانتقال إلى صفحة اليوم
            if not self.navigate_with_patience(page, day_url, "DAY"):
                return None
            
            # البحث عن أوقات متاحة
            time_selectors = [
                "a.arrow[href*='appointment_showForm']",
                "a[href*='showForm']",
                "td.frei a"
            ]
            
            for selector in time_selectors:
                time_links = page.locator(selector).all()
                if time_links:
                    num_times = len(time_links)
                    logger.critical(f"[FOUND] {num_times} وقت متاح!")
                    
                    with self.lock:
                        self.stats.slots_found += num_times
                    
                    # العودة مع رابط الوقت الأول
                    first_href = time_links[0].get_attribute("href")
                    if first_href:
                        base_domain = self.base_url.split("/extern")[0]
                        return f"{base_domain}/{first_href}"
            
            return None
            
        except Exception as e:
            logger.warning(f"[SCAN] خطأ في فحص اليوم: {e}")
            return None
    
    def fill_form_naturally(self, page: Page, session: SessionState) -> bool:
        """
        تعبئة النموذج بشكل طبيعي
        
        القاعدة 4: إدخال حدثي كامل
        """
        try:
            logger.info("[FORM] تعبئة النموذج بشكل طبيعي...")
            
            # قائمة الحقول بالقيم
            fields = [
                ("input[name='lastname']", Config.LAST_NAME),
                ("input[name='firstname']", Config.FIRST_NAME),
                ("input[name='email']", Config.EMAIL),
                ("input[name='emailrepeat']", Config.EMAIL),
                ("input[name='emailRepeat']", Config.EMAIL),
                ("input[name='fields[0].content']", Config.PASSPORT),
                ("input[name='fields[1].content']", Config.PHONE.replace("+", "00").strip())
            ]
            
            # تعبئة كل حقل بشكل بشري
            for selector, value in fields:
                if page.locator(selector).count() > 0:
                    self.human_type(page, selector, value)
                    time.sleep(0.3)
            
            # اختيار الفئة (إن وجد)
            try:
                select_locator = page.locator("select").first
                if select_locator.is_visible():
                    # اختيار الخيار الثاني (عادة يكون الخيار الأول فارغ)
                    select_locator.select_option(index=1)
                    time.sleep(0.5)
            except:
                pass
            
            with self.lock:
                self.stats.forms_filled += 1
            
            logger.info("[FORM] النموذج معبأ")
            return True
            
        except Exception as e:
            logger.error(f"[FORM] خطأ في تعبئة النموذج: {e}")
            return False
    
    def submit_form_naturally(self, page: Page, session: SessionState) -> bool:
        """
        إرسال النموذج بشكل طبيعي مع Retry ذكي
        
        القاعدة 7: Retry داخل نفس الصفحة
        القاعدة 8: الصمت ≠ فشل نهائي
        """
        max_attempts = 8
        worker_id = session.worker_id
        
        logger.info(f"[SUBMIT] بدء التسلسل الطبيعي للإرسال")
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"[SUBMIT] المحاولة {attempt}/{max_attempts}")
                
                # 1. التحقق من أننا على صفحة الفورم
                lastname_input = page.locator("input[name='lastname']").first
                if not lastname_input.is_visible(timeout=2000):
                    logger.warning("[SUBMIT] لم يتم العثور على نموذج")
                    return False
                
                # 2. حل كابتشا الفورم
                captcha_input = page.locator("input[name='captchaText']").first
                if not captcha_input.is_visible():
                    logger.warning("[SUBMIT] لم يتم العثور على حقل الكابتشا")
                    return False
                
                success, code, status = self.solver.solve_from_page(
                    page, f"FORM_{attempt}",
                    session_age=session.age(),
                    attempt=attempt,
                    max_attempts=3
                )
                
                if not success or not code:
                    logger.warning(f"[SUBMIT] فشل حل الكابتشا: {status}")
                    
                    # تحديث صورة الكابتشا والمحاولة مرة أخرى
                    self.solver.reload_captcha(page)
                    time.sleep(1)
                    continue
                
                # 3. إدخال الكابتشا بشكل بشري
                captcha_input.click()
                captcha_input.fill("")
                self.human_type(page, "input[name='captchaText']", code)
                time.sleep(0.5)
                
                # 4. البحث عن زر الإرسال والنقر عليه
                submit_selectors = [
                    "input[type='submit'][value='Submit']",
                    "input[type='submit'][value='submit']",
                    "input[name='action:appointment_addAppointment']",
                    "#appointment_newAppointmentForm_appointment_addAppointment"
                ]
                
                submitted = False
                for selector in submit_selectors:
                    if self.human_click(page, selector):
                        submitted = True
                        logger.info(f"[SUBMIT] نقر على: {selector}")
                        break
                
                if not submitted:
                    # Fallback: Enter على حقل الكابتشا
                    logger.info("[SUBMIT] استخدام Enter كبديل")
                    page.keyboard.press("Enter")
                
                # 5. الانتظار الهادئ للنتيجة
                logger.info("[SUBMIT] انتظار الاستجابة...")
                time.sleep(4)  # انتظار طويل للاستقرار
                
                # 6. التحقق من النتيجة بهدوء
                content = page.content().lower()
                
                # ✅ النجاح
                success_indicators = [
                    "appointment number",
                    "termin wurde gebucht",
                    "ihre buchung",
                    "successfully",
                    "confirmation"
                ]
                
                for indicator in success_indicators:
                    if indicator in content:
                        logger.critical(f"[SUCCESS] تم العثور على: '{indicator}'")
                        
                        # حفظ الأدلة
                        self.debug_manager.save_critical_screenshot(page, "SUCCESS", worker_id)
                        self.debug_manager.save_debug_html(page, "SUCCESS", worker_id)
                        
                        # إرسال إشعار
                        try:
                            send_success_notification(self.session_id, worker_id, None)
                        except:
                            pass
                        
                        with self.lock:
                            self.stats.success = True
                        
                        self.stop_event.set()
                        return True
                
                # 🔄 الفشل الصامت - استمر في المحاولة
                if page.locator("input[name='lastname']").is_visible():
                    logger.info(f"[SILENT] رفض صامت - إعادة المحاولة {attempt}")
                    
                    # تحديث الكابتشا للمحاولة التالية
                    self.solver.reload_captcha(page)
                    time.sleep(2)
                    continue
                
                # ❌ فشل صريح
                error_indicators = [
                    "beginnen sie den buchungsvorgang neu",
                    "session expired",
                    "invalid session"
                ]
                
                for indicator in error_indicators:
                    if indicator in content:
                        logger.error(f"[HARD_FAIL] فشل صريح: '{indicator}'")
                        return False
                
                # حالة غير معروفة - انتظر ثم حاول مرة أخرى
                logger.warning(f"[UNKNOWN] حالة غير معروفة بعد المحاولة {attempt}")
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"[SUBMIT] خطأ في المحاولة {attempt}: {e}")
                time.sleep(2)
        
        logger.warning(f"[SUBMIT] تم تجاوز الحد الأقصى للمحاولات ({max_attempts})")
        return False
    
    def run_single_natural_session(self, browser: Browser) -> bool:
        """
        جلسة واحدة طبيعية من البداية إلى النهاية
        
        تطبيق حرفي لجميع القواعد التنفيذية
        """
        logger.info("[SESSION] بدء الجلسة الطبيعية الواحدة")
        
        # إنشاء السياق
        page, session = self.create_natural_context(browser)
        
        try:
            # توليد روابط الأشهر للأولوية
            def generate_priority_urls():
                today = datetime.datetime.now().date()
                base_clean = self.base_url.split("&dateStr=")[0] if "&dateStr=" in self.base_url else self.base_url
                
                urls = []
                priority_offsets = [2, 3, 1, 4, 5, 6]  # الأولوية: 2، 3، 1، 4، 5، 6 أشهر
                
                for offset in priority_offsets:
                    future_date = today + datetime.timedelta(days=30 * offset)
                    date_str = f"15.{future_date.month:02d}.{future_date.year}"
                    urls.append(f"{base_clean}&dateStr={date_str}")
                
                return urls
            
            cycle = 0
            max_cycles = 50
            
            while not self.stop_event.is_set() and cycle < max_cycles:
                cycle += 1
                logger.info(f"[CYCLE] الدورة {cycle}/{max_cycles}")
                
                # الحصول على روابط الأشهر
                month_urls = generate_priority_urls()
                
                for month_url in month_urls:
                    if self.stop_event.is_set():
                        break
                    
                    # ═══════════════════════════════════════════════
                    # الخطوة 1: فحص الشهر
                    # ═══════════════════════════════════════════════
                    day_url = self.scan_month_for_days(page, month_url, session)
                    
                    if not day_url:
                        continue  # جرب الشهر التالي
                    
                    # ═══════════════════════════════════════════════
                    # الخطوة 2: فحص اليوم
                    # ═══════════════════════════════════════════════
                    time_url = self.scan_day_for_times(page, day_url, session)
                    
                    if not time_url:
                        continue  # جرب الشهر التالي
                    
                    # ═══════════════════════════════════════════════
                    # الخطوة 3: الانتقال إلى نموذج الحجز
                    # ═══════════════════════════════════════════════
                    if not self.navigate_with_patience(page, time_url, "FORM"):
                        continue
                    
                    # حفظ صفحة الفورم للأدلة
                    self.debug_manager.save_debug_html(page, "form_page", 1)
                    
                    # ═══════════════════════════════════════════════
                    # الخطوة 4: تعبئة النموذج
                    # ═══════════════════════════════════════════════
                    if not self.fill_form_naturally(page, session):
                        logger.warning("[FLOW] فشل تعبئة النموذج")
                        continue
                    
                    # ═══════════════════════════════════════════════
                    # الخطوة 5: إرسال النموذج (نقطة اللاعودة)
                    # ═══════════════════════════════════════════════
                    logger.critical("[FLOW] نقطة اللاعودة - بدء الإرسال")
                    
                    if self.submit_form_naturally(page, session):
                        # ✅ النجاح
                        return True
                    else:
                        # ❌ فشل في هذا المسار، جرب شهرًا آخر
                        logger.info("[FLOW] فشل في هذا المسار، الانتقال إلى الشهر التالي")
                        break  # الخروج من حلقة الأشهر، ابدأ دورة جديدة
                
                # انتظار بين الدورات
                if not self.stop_event.is_set():
                    wait_time = 5 if self.is_attack_time() else 10
                    logger.info(f"[WAIT] انتظار {wait_time} ثانية")
                    time.sleep(wait_time)
            
            logger.info("[SESSION] انتهت الدورات القصوى")
            return False
            
        except Exception as e:
            logger.error(f"[SESSION] خطأ في الجلسة: {e}", exc_info=True)
            return False
            
        finally:
            try:
                page.context.close()
            except:
                pass
            logger.info("[SESSION] الجلسة مغلقة")
    
    def run(self) -> bool:
        """
        نقطة الدخول الرئيسية
        
        العودة:
            True إذا نجح الحجز، False بخلاف ذلك
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER {self.VERSION}] - بدء التنفيذ")
        logger.info(f"[TIME] وقت الهجوم: {Config.ATTACK_HOUR}:00 صباحًا بتوقيت عدن")
        logger.info(f"[NOW] الوقت الحالي في عدن: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        try:
            # إرسال إشعار البدء
            send_alert(
                f"[Elite Sniper {self.VERSION} Started]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Natural Session\n"
                f"Attack: {Config.ATTACK_HOUR}:00 AM Aden\n"
                f"NTP Offset: {self.ntp_sync.offset:.4f}s"
            )
            
            with sync_playwright() as p:
                # تشغيل المتصفح
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                logger.info("[BROWSER] تم تشغيل المتصفح")
                
                try:
                    # تشغيل الجلسة الطبيعية الواحدة
                    success = self.run_single_natural_session(browser)
                except Exception as e:
                    logger.error(f"[ERROR] خطأ في الجلسة: {e}")
                    success = False
                
                # إيقاف مزامنة الوقت
                self.ntp_sync.stop_background_sync()
                
                # التنظيف
                browser.close()
                
                # حفظ الإحصائيات النهائية
                final_stats = self.stats.to_dict()
                self.debug_manager.save_stats(final_stats, "final_stats.json")
                self.debug_manager.create_session_report(final_stats)
                
                if success:
                    self._handle_success()
                    return True
                else:
                    self._handle_completion()
                    return False
                
        except KeyboardInterrupt:
            logger.info("\n[STOP] إيقاف يدوي")
            self.stop_event.set()
            self.ntp_sync.stop_background_sync()
            send_alert("⏸️ Elite Sniper متوقف يدويًا")
            return False
            
        except Exception as e:
            logger.error(f"💀 خطأ حرج: {e}", exc_info=True)
            send_alert(f"🚨 خطأ حرج: {str(e)[:200]}")
            return False
    
    def _handle_success(self):
        """معالجة النجاح"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] المهمة أنجزت - الحجز ناجح!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"ELITE SNIPER {self.VERSION} - SUCCESS!\n"
            f"[+] تم حجز الموعد!\n"
            f"الجلسة: {self.session_id}\n"
            f"الوقت: {runtime:.0f} ثانية\n"
            f"الإحصائيات: {self.stats.get_summary()}"
        )
    
    def _handle_completion(self):
        """معالجة الانتهاء بدون نجاح"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] انتهت الجلسة بدون حجز")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        logger.info(f"[TIME] وقت التشغيل: {runtime:.0f} ثانية")
        logger.info(f"[STATS] الإحصائيات النهائية: {self.stats.get_summary()}")


# نقطة الدخول
if __name__ == "__main__":
    sniper = EliteSniperV2Corrected()
    success = sniper.run()
    sys.exit(0 if success else 1)