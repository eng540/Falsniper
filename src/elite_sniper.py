import time
import random
import datetime
import logging
import pytz
import ntplib
from playwright.sync_api import sync_playwright

from .config import Config
from .captcha import CaptchaSolver
from .notifier import send_alert, send_photo

# ---------------------------------------------------------
# 1. Logging Speed & Precision
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("EliteSniper")

class EliteSniper:
    def __init__(self):
        self.solver = CaptchaSolver()
        self.base_url = Config.TARGET_URL + "&request_locale=en"
        self.tz_yemen = pytz.timezone('Asia/Aden')
        self.time_offset = 0
        self.user_agents = [
             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
             "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        self.poisoned_session = False
        
        # NTP Sync on init
        self.sync_time()

    # ---------------------------------------------------------
    # 2. Time Warfare (NTP & Zero Hour)
    # ---------------------------------------------------------
    def sync_time(self):
        try:
            client = ntplib.NTPClient()
            response = client.request('pool.ntp.org', version=3)
            self.time_offset = response.offset
            logger.info(f"⏱️ Time Synced. Offset: {self.time_offset:.4f}s")
        except:
            logger.warning("⚠️ NTP Sync Failed. Using local time.")

    def get_precise_time(self):
        return datetime.datetime.now(self.tz_yemen) + datetime.timedelta(seconds=self.time_offset)

    def wait_for_zero_hour(self):
        target_hour = 1
        target_minute = 59
        target_second = 50
        
        while True:
            now = self.get_precise_time()
            if now.hour == target_hour and now.minute == target_minute and now.second >= target_second:
                logger.info("⚔️ ZERO HOUR REACHED! LAUNCHING ATTACK!")
                break
            
            # Blocking wait for precision (no sleep inside critical window)
            if now.hour == target_hour and now.minute == target_minute and now.second > 45:
                pass # Busy wait
            else:
                time.sleep(0.5)

    def get_mode(self):
        now = self.get_precise_time()
        # Beast Mode: 01:59:50 to 02:05:00
        if (now.hour == 1 and now.minute == 59 and now.second >= 50) or (now.hour == 2 and now.minute <= 5):
            return "BEAST"
        if now.hour == 1 and now.minute >= 45:
            return "WARMUP"
        return "PATROL"

    # ---------------------------------------------------------
    # 3. Infrastructure (Rebirth & Resource Blocking)
    # ---------------------------------------------------------
    def rebirth(self, context, browser):
        logger.critical("☣️ REBIRTH PROTOCOL ACTIVATED.")
        try: context.close()
        except: pass
        
        mode = self.get_mode()
        sleep_time = 0.5 if mode == "BEAST" else random.uniform(5, 8)
        time.sleep(sleep_time)
        
        new_context = browser.new_context(
            user_agent=random.choice(self.user_agents),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Aden"
        )
        
        page = new_context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        
        # AGGRESSIVE RESOURCE BLOCKING
        page.route("**/*", lambda route: route.abort() 
                   if route.request.resource_type in ["image", "media", "font", "stylesheet"] 
                   else route.continue_())

        self.poisoned_session = False
        logger.info("✨ REBIRTH COMPLETE.")
        return new_context, page

    # ---------------------------------------------------------
    # 4. Injection & Ghost Click
    # ---------------------------------------------------------
    def fast_inject(self, page, selector, value):
        if page.locator(selector).count() == 0: return False
        try:
            page.evaluate(f"""
                const el = document.querySelector("{selector}");
                if(el) {{ el.value = "{value}"; el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            """)
            return True
        except: return False

    def robust_fill_form(self, page):
        # 1. Standard Fields
        self.fast_inject(page, "input[name='lastname']", Config.LAST_NAME)
        self.fast_inject(page, "input[name='firstname']", Config.FIRST_NAME)
        self.fast_inject(page, "input[name='email']", Config.EMAIL)
        if not self.fast_inject(page, "input[name='emailrepeat']", Config.EMAIL):
             self.fast_inject(page, "input[name='emailRepeat']", Config.EMAIL)

        # 2. Dynamic Fields (Passport/Phone) via ID Finding or Fallback
        passport = Config.PASSPORT
        phone = Config.PHONE.replace("+", "00").strip()
        
        # Try finding by Definition ID (Most robust if known) logic or fallbacks
        if not self.fast_inject(page, "input[name='fields[0].content']", passport):
             # Try label search
             pass 
        self.fast_inject(page, "input[name='fields[1].content']", phone)

        # 3. Select Category
        try:
            page.evaluate("document.querySelector('select').selectedIndex = 1; document.querySelector('select').dispatchEvent(new Event('change'));")
        except: pass

    # ---------------------------------------------------------
    # 5. Deathmatch Loop (Form Submission)
    # ---------------------------------------------------------
    def deathmatch_submit(self, page, mode):
        logger.info("💀 ENTERING DEATHMATCH SUBMISSION LOOP (10 Attempts)...")
        
        for i in range(10):
            # 1. Solve Captcha
            if not self.solve_captcha(page, mode):
                # If captcha failed but form still there, retry loop
                if page.locator("input[name='lastname']").count() > 0: continue
                return False # Lost the page
            
            # 2. Check Result
            try: page.wait_for_load_state("networkidle", timeout=5000)
            except: pass
            
            content = page.content().lower()
            if "appointment number" in content:
                logger.info("🏆 VICTORY! APPOINTMENT SECURED.")
                send_photo(page.screenshot(), "✅ VICTORY!")
                return True
            
            # Silent Reject?
            if page.locator("input[name='lastname']").count() > 0:
                logger.warning(f"⚔️ Silent Reject (Attempt {i+1}). RELOADING WEAPON...")
                continue # Immediate loop
            
            # Error Page?
            if "error" in content:
                logger.error("❌ Server Error.")
                return False
                
        return False

    # ---------------------------------------------------------
    # 6. Checks & Solvers
    # ---------------------------------------------------------
    def check_poison(self, page, location="Unknown"):
        # Context-Aware: Month Captcha is ONLY poison if we are NOT in Month View
        # But for safety, we rely mainly on "Black Captcha" detection or "Bounced back" logic
        if location == "Form" and page.locator("form#appointment_captcha_month").count() > 0:
            logger.warning("☠️ POISON: Bounced to Month Captcha from Form.")
            self.poisoned_session = True
            return True
        return False

    def solve_captcha(self, page, mode):
        if not page.locator("input[name='captchaText']").is_visible(): return True
        
        captcha_div = page.locator("captcha > div").first
        if captcha_div.is_visible():
            img_bytes = captcha_div.screenshot()
            # Black Captcha Check
            if len(img_bytes) < 1500:
                logger.critical("⚫ BLACK CAPTCHA. POISONED.")
                self.poisoned_session = True
                return False
                
            code = self.solver.solve(img_bytes).replace(" ","")
            if len(code) > 3:
                self.fast_inject(page, "input[name='captchaText']", code)
                page.keyboard.press("Enter")
                try: page.wait_for_load_state("domcontentloaded", timeout=3000)
                except: pass
                
                # Check if still there
                if page.locator("input[name='captchaText']").is_visible(): return False
                return True
        return False

    # ---------------------------------------------------------
    # 7. Main Engine
    # ---------------------------------------------------------
    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu"]
            )
            context, page = self.rebirth(None, browser)

            while True:
                try:
                    if self.poisoned_session: 
                        context, page = self.rebirth(context, browser)
                    
                    mode = self.get_mode()
                    
                    # ZERO HOUR WAIT
                    if mode == "WARMUP" and self.get_precise_time().minute >= 58:
                         self.wait_for_zero_hour()
                         mode = "BEAST"

                    # 1. PRIORITY SCANNING
                    # Months relative to current: 3 -> 4 -> 2 -> 5 (Example logic)
                    today = datetime.date.today()
                    # Calculate target months dynamically
                    targets = []
                    # Logic: If April (4), Priority is +2 months (June), +3 months (July)
                    # Adjust 'range' to produce priority list. 
                    # Simulating explicit priority for demo: [2, 3, 1, 4] offset indices
                    priority_offsets = [2, 3, 1, 4] 
                    
                    for off in priority_offsets:
                        d = today + datetime.timedelta(days=30*off)
                        date_str = d.strftime("15.%m.%Y")
                        targets.append(f"{self.base_url.split('&dateStr')[0]}&dateStr={date_str}")
                    
                    for url in targets:
                        # GHOST NAVIGATE
                        try: page.goto(url, timeout=20000, wait_until="domcontentloaded")
                        except: continue

                        # Captcha Check (Is it valid here? Yes, it's Month View)
                        if page.locator("input[name='captchaText']").count() > 0:
                            if not self.solve_captcha(page, mode):
                                if self.poisoned_session: break # Rebirth
                                continue
                        
                        # Check Poison (Did we bounce?)
                        if self.check_poison(page, "Month"): break

                        # 2. SCAN DAYS
                        day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                        if day_links:
                            logger.info(f"🔥 DAYS FOUND! Ghost Jumping...")
                            href = day_links[0].get_attribute("href")
                            page.goto(self.base_url.split("/extern")[0] + "/" + href)
                            
                            # Day Captcha
                            if not self.solve_captcha(page, mode):
                                if self.poisoned_session: break
                                continue

                            # 3. SCAN SLOTS
                            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                            if time_links:
                                href = time_links[0].get_attribute("href")
                                logger.info(f"⏰ SLOT FOUND! Ghost Jumping to Form...")
                                page.goto(self.base_url.split("/extern")[0] + "/" + href)
                                
                                # Pre-Form Captcha
                                if not self.solve_captcha(page, mode):
                                    if self.poisoned_session: break
                                    continue
                                
                                # Check Poison
                                if self.check_poison(page, "Form"): break

                                # 4. DEATHMATCH SUBMIT
                                self.robust_fill_form(page)
                                if self.deathmatch_submit(page, mode):
                                    return # Victory
                                else:
                                    # Failed 10 times, go back to scan
                                    break 

                except Exception as e:
                    logger.error(f"Loop Error: {e}")
                    time.sleep(1)

if __name__ == "__main__":
    EliteSniper().run()
