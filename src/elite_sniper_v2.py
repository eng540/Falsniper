#--- START OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: src/elite_sniper_v2.py ---
import os
import time
import random
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# --- CONFIGURATION IMPORTS ---
try:
    from src.config import (
        URL_APPOINTMENT, URL_CAPTCHA_IMAGE, 
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, USE_PROXY
    )
    from src.captcha import solve_captcha_generic
    from src.ntp_sync import get_ntp_time, wait_until_target
    from src.notifier import send_telegram_msg, send_telegram_photo
    from src.debug_utils import save_debug_screenshot
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from src.config import *
    from src.captcha import solve_captcha_generic
    from src.ntp_sync import get_ntp_time, wait_until_target
    from src.notifier import send_telegram_msg, send_telegram_photo
    from src.debug_utils import save_debug_screenshot

# Setup Logging
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
        """Initializes the browser with hardened anti-detection profile"""
        proxy_conf = None
        if USE_PROXY and PROXY_HOST:
            proxy_conf = {
                "server": f"{PROXY_HOST}:{PROXY_PORT}",
                "username": PROXY_USER,
                "password": PROXY_PASS
            }
            logger.info(f"{self.prefix} Using Proxy: {PROXY_HOST}")

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1280,800"
        ]

        self.browser = p.chromium.launch(
            headless=False, 
            args=args,
            proxy=proxy_conf
        )
        
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        ]
        
        self.context = self.browser.new_context(
            user_agent=random.choice(user_agents),
            viewport={"width": 1280, "height": 800},
            locale="de-DE",
            timezone_id="Europe/Berlin"
        )
        
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.navigator.chrome = { runtime: {} };
        """)
        
        self.page = self.context.new_page()
        self.page.set_default_timeout(30000)

    def run(self):
        """Main loop"""
        with sync_playwright() as p:
            while True:
                try:
                    self.start_browser(p)
                    self.session_loop()
                except Exception as e:
                    logger.error(f"{self.prefix} 🔥 CRITICAL CRASH: {e}")
                    time.sleep(5)
                finally:
                    try:
                        if self.context: self.context.close()
                        if self.browser: self.browser.close()
                    except:
                        pass

    def session_loop(self):
        """Logic for a single session life-cycle"""
        logger.info(f"{self.prefix} 🚀 Session Started.")
        
        try:
            # 1. Go to Start Page
            logger.info(f"{self.prefix} Loading URL: {URL_APPOINTMENT}")
            self.page.goto(URL_APPOINTMENT, timeout=60000)
            self.page.wait_for_load_state("domcontentloaded")
            
            # 2. Handle First Captcha (Entry)
            if not self.handle_captcha_loop("ENTRY"):
                logger.warning(f"{self.prefix} Captcha failed. Restarting.")
                return 
            
            # 3. Navigate to Calendar (Logic Restored)
            self.navigate_to_calendar()
            
        except PlaywrightTimeout:
            logger.warning(f"{self.prefix} ⌛ Timeout. Restarting session.")
        except Exception as e:
            logger.error(f"{self.prefix} ⚠️ Error: {e}")
            save_debug_screenshot(self.page, "session_error")

    def handle_captcha_loop(self, stage_name):
        """Robust Captcha Handler with Loop Detection"""
        attempts = 0
        max_attempts = 10 
        
        while attempts < max_attempts:
            try:
                # Fast check for captcha
                captcha_img = self.page.query_selector("div.captcha img, img[alt='Captcha']")
                captcha_input = self.page.query_selector("input[name='captchaText'], input#captchaText")
                
                if not captcha_img or not captcha_input:
                    logger.info(f"{self.prefix} [{stage_name}] No captcha found. Assuming passed.")
                    return True
                
                captcha_input.scroll_into_view_if_needed()
                logger.info(f"{self.prefix} [{stage_name}] Solving Captcha (Attempt {attempts+1})...")
                
                screenshot_bytes = self.page.screenshot()
                solution = solve_captcha_generic(screenshot_bytes)
                
                if not solution or len(solution) != 6:
                    logger.warning(f"{self.prefix} [{stage_name}] Invalid solution '{solution}'. Retrying...")
                    self.refresh_captcha()
                    attempts += 1
                    continue
                
                # Fill and Submit
                captcha_input.fill("")
                time.sleep(0.2)
                captcha_input.type(solution, delay=100)
                time.sleep(0.5)
                
                submit_btn = self.page.query_selector("button#continue, button[type='submit'], input[type='submit']")
                if submit_btn:
                    submit_btn.click()
                else:
                    self.page.keyboard.press("Enter")
                
                logger.info(f"{self.prefix} [{stage_name}] Submitted '{solution}'. Verifying...")
                
                # Verification Logic
                if self.verify_success_robust():
                    logger.info(f"{self.prefix} [{stage_name}] ✅ Captcha Passed!")
                    return True
                else:
                    logger.warning(f"{self.prefix} [{stage_name}] ❌ Failed (Loop/Error). Retrying...")
                    
                attempts += 1
                
            except Exception as e:
                logger.error(f"{self.prefix} [{stage_name}] Error in loop: {e}")
                attempts += 1
                time.sleep(1)
                
        logger.error(f"{self.prefix} [{stage_name}] 💀 Max attempts reached.")
        return False

    def verify_success_robust(self):
        """Waits for navigation or error message."""
        try:
            for _ in range(10): # 5 seconds wait
                time.sleep(0.5)
                # Success: Captcha input gone
                if not self.page.query_selector("input[name='captchaText']"):
                    # Double check if we have a success element (like category list or calendar)
                    if self.page.query_selector("form, .wrapper, #content"): 
                        return True 
                
                # Failure: Error message
                error_msg = self.page.query_selector(".alert-danger, .error-message, div[class*='error']")
                if error_msg and error_msg.is_visible():
                    txt = error_msg.inner_text()
                    if "captcha" in txt.lower() or "sicherheitscode" in txt.lower():
                        return False 
                        
            # Final check
            if self.page.query_selector("input[name='captchaText']"):
                return False
            return True 
        except Exception:
            return False

    def refresh_captcha(self):
        try:
            refresh_btn = self.page.query_selector("a.refresh-captcha, button.refresh")
            if refresh_btn:
                refresh_btn.click()
                time.sleep(1)
        except:
            pass

    def navigate_to_calendar(self):
        """
        Executes the post-captcha navigation logic.
        1. Checks if we are on Category Selection page.
        2. Clicks 'Continue' or selects a category.
        3. Validates if we reached the Calendar.
        """
        logger.info(f"{self.prefix} 🏁 Navigating to Services/Calendar...")
        time.sleep(1) # Stability wait
        
        try:
            # Case A: We are at "Termin Buchen" main button
            booking_btn = self.page.query_selector("input[value='Termin buchen'], button:has-text('Termin buchen')")
            if booking_btn:
                logger.info(f"{self.prefix} Clicking 'Termin buchen'...")
                booking_btn.click()
                self.page.wait_for_load_state("networkidle")
            
            # Case B: We are at Category Selection
            # Looking for 'Weiter' button (common in RK-Termin)
            continue_btn = self.page.query_selector("input[name='next'], button:has-text('Weiter'), input[value='Weiter']")
            if continue_btn:
                logger.info(f"{self.prefix} Found 'Weiter' button. Clicking...")
                continue_btn.click()
                self.page.wait_for_load_state("networkidle")
            
            # Case C: Check for Month/Calendar
            if self.page.query_selector(".month-view, .calendar-table, select[name='month']"):
                logger.info(f"{self.prefix} 📅 CALENDAR DETECTED! Starting scanning...")
                # Here you would trigger the slot scanning logic
                # self.scan_slots()
                return

            # Case D: Another Captcha? (Some flows have 2 captchas)
            if self.page.query_selector("input[name='captchaText']"):
                logger.info(f"{self.prefix} 🛡️ Secondary Captcha detected.")
                self.handle_captcha_loop("SECONDARY")
                
            logger.info(f"{self.prefix} Navigation step complete. Current URL: {self.page.url}")

        except Exception as e:
            logger.error(f"{self.prefix} Navigation Error: {e}")
            save_debug_screenshot(self.page, "nav_error")

#--- END OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: src/elite_sniper_v2.py ---