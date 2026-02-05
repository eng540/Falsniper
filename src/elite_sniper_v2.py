#--- START OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: src/elite_sniper_v2.py ---
import os
import time
import random
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# --- 1. CONFIGURATION LOADING ---
# محاولة استيراد الإعدادات والوحدات المساعدة مع دعم مرونة المسارات
try:
    from src.config import (
        URL_APPOINTMENT, URL_CAPTCHA_IMAGE, 
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, USE_PROXY
    )
    from src.captcha import solve_captcha_generic
    from src.notifier import send_telegram_msg, send_telegram_photo
    from src.debug_utils import save_debug_screenshot
except ImportError:
    # في حالة التشغيل المباشر من المجلد أو مسار مختلف
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from src.config import *
    from src.captcha import solve_captcha_generic
    from src.notifier import send_telegram_msg, send_telegram_photo
    from src.debug_utils import save_debug_screenshot

# --- 2. LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("EliteSniperV2")

class EliteSniperV2:
    def __init__(self, thread_id=1, is_scout=False):
        self.thread_id = thread_id
        self.is_scout = is_scout
        self.prefix = f"[EliteSniperV2.{'Scout' if is_scout else 'Single'}]"
        self.browser = None
        self.context = None
        self.page = None
        
    def start_browser(self, p):
        """تهيئة المتصفح مع إعدادات التخفي العالية (Anti-Detection)"""
        proxy_conf = None
        if USE_PROXY and PROXY_HOST:
            proxy_conf = {
                "server": f"{PROXY_HOST}:{PROXY_PORT}",
                "username": PROXY_USER,
                "password": PROXY_PASS
            }
            logger.info(f"{self.prefix} 🛡️ Using Proxy: {PROXY_HOST}")

        # إخفاء خصائص الأتمتة لتجاوز الحماية
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1280,800"
        ]

        self.browser = p.chromium.launch(
            headless=False, # يمكن تغييره لـ True في السيرفرات (Headless Mode)
            args=args,
            proxy=proxy_conf
        )
        
        # تدوير User-Agents لتقليل البصمة
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        
        self.context = self.browser.new_context(
            user_agent=random.choice(user_agents),
            viewport={"width": 1280, "height": 800},
            locale="de-DE",
            timezone_id="Europe/Berlin"
        )
        
        # حقن سكربتات التخفي (Stealth Injection)
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.navigator.chrome = { runtime: {} };
        """)
        
        self.page = self.context.new_page()
        self.page.set_default_timeout(30000)

    def run(self):
        """الحلقة الرئيسية للتشغيل وإدارة الأخطاء الكارثية"""
        with sync_playwright() as p:
            while True:
                try:
                    self.start_browser(p)
                    self.session_loop()
                except KeyboardInterrupt:
                    logger.info("🛑 Stopped by user.")
                    break
                except Exception as e:
                    logger.error(f"{self.prefix} 🔥 CRITICAL SYSTEM CRASH: {e}")
                    time.sleep(5)
                finally:
                    try:
                        if self.context: self.context.close()
                        if self.browser: self.browser.close()
                    except:
                        pass

    def session_loop(self):
        """دورة حياة الجلسة الواحدة (Session Lifecycle)"""
        logger.info(f"{self.prefix} 🚀 Session Started.")
        
        try:
            # 1. الذهاب للصفحة الرئيسية
            logger.info(f"{self.prefix} Loading URL: {URL_APPOINTMENT}")
            self.page.goto(URL_APPOINTMENT, timeout=60000)
            self.page.wait_for_load_state("domcontentloaded")
            
            # 2. معالجة كابتشا الدخول (مع الإصلاح الجديد لمنع اللوب)
            if not self.handle_captcha_loop("ENTRY"):
                logger.warning(f"{self.prefix} Captcha failed or loop detected. Restarting session.")
                return 
            
            # 3. التنقل للتقويم (استدعاء دالة التنقل الذكية)
            self.navigate_to_calendar()
            
        except PlaywrightTimeout:
            logger.warning(f"{self.prefix} ⌛ Timeout. Restarting session.")
        except Exception as e:
            logger.error(f"{self.prefix} ⚠️ Unexpected Error: {e}")
            save_debug_screenshot(self.page, "session_error")

    def handle_captcha_loop(self, stage_name):
        """
        نظام معالجة الكابتشا المحدث (v3.1):
        - يمنع التكرار اللانهائي.
        - يتحقق بذكاء من نجاح الحل.
        - يدعم إعادة المحاولة عند الفشل.
        Returns: True if passed, False if failed.
        """
        attempts = 0
        max_attempts = 10 
        
        while attempts < max_attempts:
            try:
                time.sleep(1) # استقرار الصفحة
                
                # فحص وجود الكابتشا في DOM
                captcha_img = self.page.query_selector("div.captcha img, img[alt='Captcha']")
                captcha_input = self.page.query_selector("input[name='captchaText'], input#captchaText")
                
                # إذا لم يوجد كابتشا، نعتبر أن الطريق سالك
                if not captcha_img or not captcha_input:
                    logger.info(f"{self.prefix} [{stage_name}] No captcha found. Path seems clear.")
                    return True
                
                captcha_input.scroll_into_view_if_needed()
                logger.info(f"{self.prefix} [{stage_name}] Solving Captcha (Attempt {attempts+1}/{max_attempts})...")
                
                # التقاط الصورة والحل باستخدام المحرك المحلي
                screenshot_bytes = self.page.screenshot()
                solution = solve_captcha_generic(screenshot_bytes)
                
                # التحقق من صحة طول الحل (عادة 6 خانات)
                if not solution or len(solution) < 4:
                    logger.warning(f"{self.prefix} [{stage_name}] Invalid solution '{solution}'. Refreshing...")
                    self.refresh_captcha()
                    attempts += 1
                    continue
                
                # الكتابة والإرسال
                captcha_input.fill("")
                time.sleep(0.3)
                captcha_input.type(solution, delay=100)
                time.sleep(0.5)
                
                # محاولة العثور على زر الإرسال أو استخدام Enter
                submit_btn = self.page.query_selector("button#continue, button[type='submit'], input[type='submit'], button:has-text('Weiter')")
                if submit_btn:
                    submit_btn.click()
                else:
                    self.page.keyboard.press("Enter")
                
                logger.info(f"{self.prefix} [{stage_name}] Submitted '{solution}'. Waiting for server response...")
                
                # --- FIX: ROBUST VERIFICATION (التحقق الصبور) ---
                if self.verify_success_robust():
                    logger.info(f"{self.prefix} [{stage_name}] ✅ Captcha Passed! (Verified)")
                    return True
                else:
                    logger.warning(f"{self.prefix} [{stage_name}] ❌ Failed (Server rejected or Page Reloaded). Retrying...")
                    # في حالة الفشل، نحدث الصورة لتجنب تكرار نفس الحل الخاطئ
                    self.refresh_captcha()
                    
                attempts += 1
                
            except Exception as e:
                logger.error(f"{self.prefix} [{stage_name}] Error in loop: {e}")
                attempts += 1
                time.sleep(1)
                
        logger.error(f"{self.prefix} [{stage_name}] 💀 Max attempts reached. Session Poisoned.")
        return False

    def verify_success_robust(self):
        """
        آلية التحقق القوية: تنتظر حتى تتأكد من الانتقال أو الخطأ.
        تعالج مشكلة بطء السيرفر في التوجيه وتمنع الحكم المتسرع بالفشل.
        """
        try:
            # ننتظر 5 ثوانٍ كحد أقصى (فحص كل نصف ثانية)
            for _ in range(10): 
                time.sleep(0.5)
                
                # 1. علامة النجاح: اختفاء حقل الكابتشا
                if not self.page.query_selector("input[name='captchaText']"):
                    # تأكيد إضافي: هل ظهر محتوى الصفحة التالية؟
                    if self.page.query_selector("form, .wrapper, #content, .calendar-table"): 
                        return True 
                
                # 2. علامة الفشل: ظهور رسالة خطأ صريحة
                error_msg = self.page.query_selector(".alert-danger, .error-message, div[class*='error']")
                if error_msg and error_msg.is_visible():
                    txt = error_msg.inner_text().lower()
                    # كلمات مفتاحية للخطأ بالألمانية أو الإنجليزية
                    if "captcha" in txt or "code" in txt or "sicherheitscode" in txt:
                        logger.info(f"{self.prefix} Error detected: {txt.strip()}")
                        return False 
                        
            # بعد انتهاء الوقت، فحص أخير
            if self.page.query_selector("input[name='captchaText']"):
                # الكابتشا لا تزال موجودة ولم تظهر رسالة خطأ -> غالباً إعادة تحميل صامتة (Silent Reload)
                return False
                
            return True 
        except Exception:
            return False

    def refresh_captcha(self):
        """تحديث الصورة في حالة التعليق أو الحل الخاطئ"""
        try:
            refresh_btn = self.page.query_selector("a.refresh-captcha, button.refresh")
            if refresh_btn:
                logger.info(f"{self.prefix} Refreshing Captcha Image...")
                refresh_btn.click()
                time.sleep(1.5)
        except:
            pass

    def navigate_to_calendar(self):
        """
        منطق التنقل بعد الكابتشا للوصول للتقويم.
        يتعامل مع السيناريوهات المختلفة للموقع (زر حجز مباشر، زر التالي، إلخ).
        """
        logger.info(f"{self.prefix} 🏁 Navigating to Services/Calendar...")
        time.sleep(1) 
        
        try:
            # السيناريو 1: زر 'Termin buchen' الرئيسي
            booking_btn = self.page.query_selector("input[value='Termin buchen'], button:has-text('Termin buchen')")
            if booking_btn:
                logger.info(f"{self.prefix} Clicking 'Termin buchen'...")
                booking_btn.click()
                self.page.wait_for_load_state("networkidle")
            
            # السيناريو 2: زر 'Weiter' (اختيار الفئات)
            continue_btn = self.page.query_selector("input[name='next'], button:has-text('Weiter'), input[value='Weiter']")
            if continue_btn:
                logger.info(f"{self.prefix} Found 'Weiter' button. Clicking...")
                continue_btn.click()
                self.page.wait_for_load_state("networkidle")
            
            # السيناريو 3: التحقق من الوصول للتقويم
            if self.page.query_selector(".month-view, .calendar-table, select[name='month']"):
                logger.info(f"{self.prefix} 📅 CALENDAR DETECTED! Ready to Scan.")
                send_telegram_msg(TELEGRAM_CHAT_ID, "✅ BINGO! Calendar Page Reached.")
                return

            # حالة طارئة: كابتشا ثانية؟ (بعض المسارات تتطلب كابتشا إضافية)
            if self.page.query_selector("input[name='captchaText']"):
                logger.info(f"{self.prefix} 🛡️ Secondary Captcha detected.")
                self.handle_captcha_loop("SECONDARY")
                
            logger.info(f"{self.prefix} Navigation step complete. Current URL: {self.page.url}")

        except Exception as e:
            logger.error(f"{self.prefix} Navigation Error: {e}")
            save_debug_screenshot(self.page, "nav_error")

#--- END OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: src/elite_sniper_v2.py ---