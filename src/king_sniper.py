import time
import random
import datetime
import logging
import pytz
import re
from playwright.sync_api import sync_playwright

# Assuming these modules exist based on the file list
from .config import Config
from .captcha import CaptchaSolver
from .notifier import send_alert, send_photo

# ---------------------------------------------------------
# 1. Logging Setup
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("KingSniper")

class KingSniper:
    def __init__(self):
        self.solver = CaptchaSolver()
        self.base_url = Config.TARGET_URL + "&request_locale=en"
        # Timezone for "Time Ambush"
        self.tz_yemen = pytz.timezone('Asia/Aden')
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ]
        
        self.poisoned_session = False

    # ---------------------------------------------------------
    # 2. Time Strategy (Patrol, Warmup, Beast)
    # ---------------------------------------------------------
    def get_mode(self):
        now = datetime.datetime.now(self.tz_yemen)
        if (now.hour == 1 and now.minute >= 58) or (now.hour == 2 and now.minute <= 5):
            return "BEAST"
        if now.hour == 1 and now.minute >= 45:
            return "WARMUP"
        return "PATROL"

    # ---------------------------------------------------------
    # 3. Rebirth Protocol (Session Poison/Soft Ban Recovery)
    # ---------------------------------------------------------
    def rebirth(self, context, browser):
        logger.critical("☣️ SESSION POISONED/BOUNCED! INITIATING REBIRTH...")
        send_alert("⚠️ Session Poisoned! Rebirthing...")
        
        try: context.close()
        except: pass
        
        mode = self.get_mode()
        sleep_time = 0.5 if mode == "BEAST" else random.uniform(5, 10)
        time.sleep(sleep_time)
        
        new_context = browser.new_context(
            user_agent=random.choice(self.user_agents),
            viewport={"width": 1366 + random.randint(0, 50), "height": 768 + random.randint(0, 50)},
            locale="en-US",
            timezone_id="Asia/Aden"
        )
        
        new_page = new_context.new_page()
        # Hide automation
        new_page.add_init_script("""Object.defineProperty(navigator, 'webdriver', { get: () => undefined });""")
        
        logger.info("✨ REBIRTH COMPLETE. New Identity Active.")
        self.poisoned_session = False
        return new_context, new_page

    # ---------------------------------------------------------
    # 4. "Surgeon's Injection" (Bypass Constraints)
    # ---------------------------------------------------------
    def fast_inject(self, page, selector, value):
        """Injects value directly into DOM, bypassing onpaste/onkeypress"""
        try:
            # Check existence first to avoid errors
            if page.locator(selector).count() == 0:
                return False
                
            page.evaluate(f"""
                const el = document.querySelector("{selector}");
                if(el) {{ 
                    el.value = "{value}"; 
                    // Dispatch events to satisfy frameworks/listeners
                    el.dispatchEvent(new Event('input', {{ bubbles: true }})); 
                    el.dispatchEvent(new Event('change', {{ bubbles: true }})); 
                    el.dispatchEvent(new Event('blur', {{ bubbles: true }})); 
                }}
            """)
            return True
        except Exception as e:
            logger.warning(f"Injection Failed for {selector}: {e}")
            return False
            
    def robust_fill_form(self, page):
        """Fills form using Label Mapping + Injection"""
        # Map known labels to Config values
        field_map = {
            "lastname": Config.LAST_NAME,
            "family name": Config.LAST_NAME,
            "firstname": Config.FIRST_NAME,
            "email*": Config.EMAIL,
            "repeat email": Config.EMAIL, # Capture "Repeat email:" label
            "passport number": Config.PASSPORT,
            "telephone number": Config.PHONE,
            "purpose of your stay": "student" # Keyword for select
        }

        # 1. Standard Fields (Lastname, Firstname, Email)
        self.fast_inject(page, "input[name='lastname']", Config.LAST_NAME)
        self.fast_inject(page, "input[name='firstname']", Config.FIRST_NAME)
        self.fast_inject(page, "input[name='email']", Config.EMAIL)
        
        # 2. Variable Fields (Email Repeat)
        # Try standard names first
        if not self.fast_inject(page, "input[name='emailrepeat']", Config.EMAIL):
             self.fast_inject(page, "input[name='emailRepeat']", Config.EMAIL)

        # 3. Dynamic Fields (Passport, Phone) - Try Definition ID Mapping if possible, else Labels, else Index
        # Looking for labels with specific text to find the 'for' attribute
        
        # Passport
        passport_input_id = self.find_input_id_by_label(page, "Passport number")
        if passport_input_id:
            logger.info(f"Targeting Passport Field: #{passport_input_id}")
            self.fast_inject(page, f"#{passport_input_id}", Config.PASSPORT)
        else:
             # Fallback to Index [0]
             self.fast_inject(page, "input[name='fields[0].content']", Config.PASSPORT)

        # Phone
        phone_input_id = self.find_input_id_by_label(page, "Telephone number")
        phone_val = Config.PHONE.replace("+", "00").strip()
        if phone_input_id:
            self.fast_inject(page, f"#{phone_input_id}", phone_val)
        else:
             self.fast_inject(page, "input[name='fields[1].content']", phone_val)

        # Purpose (Select)
        try:
            # Try to find select by label "Purpose"
            # Or just use the first select found in the dynamic area
            page.evaluate("""
                const selects = document.querySelectorAll('select');
                for (let s of selects) {
                    for (let opt of s.options) {
                        if (opt.text.toLowerCase().includes('study') || opt.text.toLowerCase().includes('student') || opt.text.toLowerCase().includes('speech')) {
                            s.value = opt.value;
                            s.dispatchEvent(new Event('change', { bubbles: true }));
                            break;
                        }
                    }
                    if (s.selectedIndex <= 0 && s.options.length > 1) {
                         s.selectedIndex = 1; // Default to first available
                         s.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            """)
        except: pass

    def find_input_id_by_label(self, page, label_text):
        try:
            # Find label containing text
            return page.evaluate(f"""
                () => {{
                    const labels = Array.from(document.querySelectorAll('label'));
                    const target = labels.find(l => l.innerText.toLowerCase().includes("{label_text.lower()}"));
                    return target ? target.getAttribute('for') : null;
                }}
            """)
        except: return None

    # ---------------------------------------------------------
    # 5. Poison Detection (The "Pulse Check")
    # ---------------------------------------------------------
    def check_session_poison(self, page):
        """Returns True if session is dead/bounced"""
        try:
            # 1. Check for Month Captcha Form on non-month pages
            if page.locator("form#appointment_captcha_month").count() > 0:
                logger.warning("☠️ POISON DETECTED: Bounced to Month Captcha.")
                self.poisoned_session = True
                return True
            
            # 2. Global Error
            if page.locator("div.global-error").count() > 0:
                 logger.warning("☠️ POISON DETECTED: Global Error Div.")
                 self.poisoned_session = True
                 return True
                 
            return False
        except: return False

    # ---------------------------------------------------------
    # 6. Captcha Logic with Poison Check
    # ---------------------------------------------------------
    def solve_captcha(self, page, mode):
        # Basic check
        if not page.locator("input[name='captchaText']").is_visible():
            return True

        if mode == "PATROL": time.sleep(random.uniform(1, 2))

        try:
            captcha_div = page.locator("captcha > div").first
            if captcha_div.is_visible():
                
                # Check for "Black Captcha" (Size check)
                img_bytes = captcha_div.screenshot()
                if len(img_bytes) < 1500:
                    logger.critical("⚫ BLACK CAPTCHA DETECTED.")
                    self.poisoned_session = True
                    return False

                code = self.solver.solve(img_bytes).replace(" ", "").strip()
                if len(code) > 3:
                    logger.info(f"🧩 Solving: {code}")
                    self.fast_inject(page, "input[name='captchaText']", code)
                    page.keyboard.press("Enter")
                    
                    try: page.wait_for_load_state("domcontentloaded", timeout=4000)
                    except: pass
                    
                    # Did we bounce back?
                    if self.check_session_poison(page): return False
                    
                    return not page.locator("input[name='captchaText']").is_visible()
        except: pass
        return False

    # ---------------------------------------------------------
    # 7. Main Loop with "Ghost Click"
    # ---------------------------------------------------------
    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu"]
            )
            
            context, page = self.rebirth(None, browser)
            logger.info("👑 KING SNIPER (Reforged) ONLINE.")

            while True:
                try:
                    if self.poisoned_session:
                        context, page = self.rebirth(context, browser)
                        continue

                    mode = self.get_mode()
                    
                    # Patrol logic (Simplified for brevity)
                    valid_urls = self.get_target_urls() 
                    
                    for url in valid_urls:
                        try:
                            page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        except: continue

                        if self.check_session_poison(page): break
                        
                        if not self.solve_captcha(page, mode):
                            if self.poisoned_session: break
                            continue

                        # GHOST CLICK IMPLEMENTATION
                        # Instead of clicking 'a.arrow', assume we parse hrefs for speed
                        
                        # 1. Day Selection
                        day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                        if day_links:
                            logger.info(f"🔥 {len(day_links)} DAYS FOUND!")
                            
                            # Ghost Click: Get HREF and Jump
                            target_href = day_links[0].get_attribute("href")
                            if target_href:
                                logger.info(f"👻 Ghost Jump to Day: {target_href}")
                                page.goto(self.base_url.split("/extern")[0] + "/" + target_href)
                            else:
                                day_links[0].click() # Fallback

                            if self.check_session_poison(page): break
                            if not self.solve_captcha(page, mode):
                                if self.poisoned_session: break
                                continue
                            
                            # 2. Time Selection
                            # Search for 'appointment_showForm' in 'a.arrow'
                            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                            if time_links:
                                target_href = time_links[0].get_attribute("href")
                                opening_period_id = "UNKNOWN"
                                if "openingPeriodId=" in target_href:
                                     opening_period_id = target_href.split("openingPeriodId=")[1].split("&")[0]

                                logger.info(f"⏰ TIME FOUND! ID: {opening_period_id}. Ghost Jumping...")
                                page.goto(self.base_url.split("/extern")[0] + "/" + target_href)

                                if self.check_session_poison(page): break
                                if not self.solve_captcha(page, mode):
                                    if self.poisoned_session: break
                                    continue

                                # 3. Booking Form
                                self.robust_fill_form(page)
                                # Submit
                                if self.solve_captcha(page, mode):
                                    if self.check_session_poison(page): break
                                    logger.info("🚀 Submitted. Checking for Success...")
                                    # ... Success check logic ...
                                    return 

                except Exception as e:
                    logger.error(f"Loop Error: {e}")
                    time.sleep(5)

    def get_target_urls(self):
        # Helper to generate current targets
        urls = []
        today = datetime.date.today()
        for i in range(2): # Look 2 months ahead
             d = today + datetime.timedelta(days=30*i)
             date_str = d.strftime("15.%m.%Y")
             urls.append(f"{self.base_url.split('&dateStr')[0]}&dateStr={date_str}")
        return urls

if __name__ == "__main__":
    bot = KingSniper()
    bot.run()
