"""
Elite Sniper v2.0 - Enhanced Captcha System
Integrates KingSniperV12 safe captcha checking with pre-solving capability
"""

import time
import logging
from typing import Optional, List, Tuple
from playwright.sync_api import Page

logger = logging.getLogger("EliteSniperV2.Captcha")

# Try to import ddddocr
try:
    import ddddocr
    DDDDOCR_AVAILABLE = True
except ImportError:
    DDDDOCR_AVAILABLE = False
    logger.warning("ddddocr not available - captcha solving disabled")

# Import config and notifier for manual captcha
from .config import Config
try:
    from . import notifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False


class TelegramCaptchaHandler:
    """
    Handle manual captcha solving via Telegram.
    Sends captcha image to user and waits for reply.
    """
    
    def __init__(self):
        self.enabled = Config.MANUAL_CAPTCHA_ENABLED and NOTIFIER_AVAILABLE
        self.timeout = Config.MANUAL_CAPTCHA_TIMEOUT
        self._attempt_count = 0
        
        if self.enabled:
            logger.info("[MANUAL] Telegram captcha handler enabled")
        else:
            logger.info("[MANUAL] Telegram captcha handler disabled")
    
    def request_manual_solution(
        self, 
        image_bytes: bytes, 
        location: str = "CAPTCHA",
        session_age: int = 0,
        attempt: int = 1,
        max_attempts: int = 5
    ) -> Optional[str]:
        """
        Send captcha to Telegram and wait for user solution.
        
        Args:
            image_bytes: Captcha image data
            location: Where captcha was found (MONTH, DAY, FORM)
            session_age: Session age in seconds
            attempt: Current attempt number
            max_attempts: Maximum attempts
        
        Returns:
            User's captcha solution or None if timeout/disabled
        """
        if not self.enabled:
            logger.warning("[MANUAL] Telegram captcha disabled")
            return None
        
        self._attempt_count += 1
        
        # Build caption for Telegram message
        caption = (
            f"🔐 CAPTCHA REQUIRED\n\n"
            f"📍 Location: {location}\n"
            f"⏱️ Session Age: {session_age}s\n"
            f"🔄 Attempt: {attempt}/{max_attempts}\n\n"
            f"Reply with the 6 characters you see.\n"
            f"Timeout: {self.timeout} seconds"
        )
        
        # Send captcha image
        logger.info(f"[MANUAL] Sending captcha to Telegram for manual solving...")
        result = notifier.send_photo_bytes(image_bytes, caption)
        
        if not result.get("success"):
            logger.error("[MANUAL] Failed to send captcha to Telegram")
            return None
        
        # Wait for user reply
        logger.info(f"[MANUAL] Waiting for reply (timeout: {self.timeout}s)...")
        solution = notifier.wait_for_captcha_reply(timeout=self.timeout)
        
        if solution:
            logger.info(f"[MANUAL] Received solution: '{solution}'")
            # Notify user
            notifier.send_alert(f"✅ Received: '{solution}'\nSubmitting...")
            return solution
        else:
            logger.warning("[MANUAL] No reply received within timeout")
            notifier.send_alert("⏱️ Timeout - no reply received. Trying OCR again...")
            return None
    
    def notify_result(self, success: bool, location: str = ""):
        """Notify user of captcha result"""
        if not self.enabled:
            return
        
        if success:
            notifier.send_alert(f"🎯 CAPTCHA SUCCESS! Moving to {location}...")
        else:
            notifier.send_alert(f"❌ CAPTCHA WRONG - sending new image...")




class EnhancedCaptchaSolver:
    """
    Enhanced captcha solver with:
    - Multiple selector attempts (from KingSniperV12)
    - Safe checking without failures
    - Black captcha detection
    - Pre-solving capability
    - Session-aware solving
    """
    
    def __init__(self, manual_only: bool = False):
        """Initialize OCR engine and manual handler"""
        self.manual_only = manual_only
        self.ocr = None
        self._pre_solved_code: Optional[str] = None
        self._pre_solved_time: float = 0.0
        self._pre_solve_timeout: float = 30.0  # Pre-solved code expires after 30s
        
        # Initialize manual captcha handler (Telegram fallback)
        self.manual_handler = TelegramCaptchaHandler()
        
        if self.manual_only:
             logger.info("[CAPTCHA] Initialized in MANUAL MODE (OCR Disabled)")
        elif DDDDOCR_AVAILABLE:
            try:
                self.ocr = ddddocr.DdddOcr(beta=True)
                logger.info("Captcha solver initialized (beta mode)")
            except Exception as e:
                logger.error(f"Captcha solver init failed: {e}")
                self.ocr = None
        else:
            logger.warning("ddddocr not installed - run: pip install ddddocr")
    
    def safe_captcha_check(self, page: Page, location: str = "GENERAL") -> Tuple[bool, bool]:
        """
        Safe captcha presence check (from KingSniperV12)
        
        Returns:
            (has_captcha: bool, check_successful: bool)
        """
        try:
            # Step 1: Check page content for captcha keywords
            page_content = page.content().lower()
            
            captcha_keywords = [
                "captcha", 
                "security code", 
                "verification", 
                "human check",
                "verkaptxt"  # German sites
            ]
            
            has_captcha_text = any(keyword in page_content for keyword in captcha_keywords)
            
            if not has_captcha_text:
                logger.debug(f"[{location}] No captcha keywords found")
                return False, True
            
            # Step 2: Search for captcha input (multiple selectors)
            # Increased timeout to 3000ms for better reliability
            captcha_selectors = self._get_captcha_selectors()
            
            for selector in captcha_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=3000):
                        logger.info(f"[{location}] Captcha found: {selector}")
                        return True, True
                except:
                    continue
            
            # Found keywords but no input field
            logger.warning(f"[{location}] Captcha text found but NO INPUT VISIBLE")
            return False, True
            
        except Exception as e:
            logger.error(f"[{location}] Captcha check error: {e}")
            return False, False
    
    def verify_captcha_solved(self, page: Page, location: str = "VERIFY") -> Tuple[bool, str]:
        """
        Verify if captcha was successfully solved and we're on the next page
        
        Returns:
            (success: bool, page_type: str)
            page_type: CAPTCHA_PAGE, CALENDAR_PAGE, TIME_SLOTS_PAGE, FORM_PAGE, SUCCESS_PAGE, UNKNOWN
        """
        import time as time_module
        
        # Wait for page to stabilize (max 3 retries)
        for attempt in range(3):
            try:
                # Wait for page to be ready
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=3000)
                except:
                    pass
                
                content = page.content().lower()
                
                # Check if still on captcha page
                has_captcha_input = page.locator("input[name='captchaText']").count() > 0
                
                if has_captcha_input:
                    return False, "CAPTCHA_PAGE"
                
                # Check for calendar page indicators
                calendar_indicators = [
                    "please select a date",
                    "appointments are available",
                    "appointment_showday",
                    "no appointments",
                    "keine termine"
                ]
                if any(ind in content for ind in calendar_indicators):
                    return True, "CALENDAR_PAGE"
                
                # Check for time slots page
                time_indicators = [
                    "please select an appointment",
                    "book this appointment",
                    "appointment_showform"
                ]
                if any(ind in content for ind in time_indicators):
                    return True, "TIME_SLOTS_PAGE"
                
                # Check for booking form page
                form_indicators = [
                    "new appointment",
                    "appointment_newappointmentform",
                    "appointment_addappointment"
                ]
                if any(ind in content for ind in form_indicators):
                    return True, "FORM_PAGE"
                
                # Check for success page
                success_indicators = [
                    "appointment number",
                    "confirmation",
                    "successfully"
                ]
                if any(ind in content for ind in success_indicators):
                    return True, "SUCCESS_PAGE"
                
                return False, "UNKNOWN"
                
            except Exception as e:
                if attempt < 2:
                    time_module.sleep(0.5)
                    continue
                logger.error(f"[{location}] Verification error: {e}")
                return False, "ERROR"
        
        return False, "TIMEOUT"
    
    def _get_captcha_selectors(self) -> List[str]:
        """
        Get list of possible captcha selectors
        From KingSniperV12 with additions
        """
        return [
            "input[name='captchaText']",
            "input[name='captcha']",
            "input#captchaText",
            "input#captcha",
            "input[type='text'][placeholder*='code']",
            "input[type='text'][placeholder*='Code']",
            "#appointment_captcha_month input[type='text']",
            "input.verkaptxt",
            "input.captcha-input",
            "input[id*='captcha']",
            "input[name*='captcha']",
            "form[id*='captcha'] input[type='text']"
        ]
    
    def _get_captcha_image_selectors(self) -> List[str]:
        """Get list of possible captcha image selectors"""
        return [
            "captcha > div",
            "div.captcha-image",
            "div#captcha",
            "img[alt*='captcha']",
            "img[alt*='CAPTCHA']",
            "canvas.captcha"
        ]
    
    def _extract_base64_captcha(self, page: Page, location: str = "EXTRACT") -> Optional[bytes]:
        """
        Extract captcha image from CSS background-image base64 data URL
        This is how the German embassy website embeds captcha images
        
        Returns:
            Image bytes or None if not found
        """
        import base64
        import re
        
        try:
            # Try to find captcha div with base64 background
            captcha_div = page.locator("captcha > div").first
            
            if not captcha_div.is_visible(timeout=2000):
                logger.debug(f"[{location}] Captcha div not visible")
                return None
            
            # Get the style attribute
            style = captcha_div.get_attribute("style")
            
            if not style:
                logger.debug(f"[{location}] No style attribute on captcha div")
                return None
            
            # Extract base64 from: background:white url('data:image/jpg;base64,XXXXX') 
            # Pattern matches the base64 data
            pattern = r"url\(['\"]?data:image/[^;]+;base64,([A-Za-z0-9+/=]+)['\"]?\)"
            match = re.search(pattern, style)
            
            if not match:
                logger.debug(f"[{location}] No base64 pattern found in style")
                return None
            
            base64_data = match.group(1)
            
            # Decode base64 to bytes
            image_bytes = base64.b64decode(base64_data)
            
            logger.info(f"[{location}] Extracted captcha from base64 ({len(image_bytes)} bytes)")
            return image_bytes
            
        except Exception as e:
            logger.warning(f"[{location}] Base64 extraction failed: {e}")
            return None
    
    def _get_captcha_image(self, page: Page, location: str = "GET_IMG") -> Optional[bytes]:
        """
        Get captcha image using multiple methods:
        1. First try CSS background base64 extraction (most reliable for this website)
        2. Fallback to screenshot method
        
        Returns:
            Image bytes or None
        """
        # Method 1: Try base64 extraction first (most reliable for this website)
        image_bytes = self._extract_base64_captcha(page, location)
        if image_bytes:
            return image_bytes
        
        # Method 2: Fallback to screenshot
        for img_selector in self._get_captcha_image_selectors():
            try:
                element = page.locator(img_selector).first
                if element.is_visible(timeout=1000):
                    image_bytes = element.screenshot(timeout=5000)
                    logger.info(f"[{location}] Got captcha via screenshot: {img_selector}")
                    return image_bytes
            except:
                continue
        
        logger.warning(f"[{location}] Could not get captcha image by any method")
        return None
    
    def detect_black_captcha(self, image_bytes: bytes) -> bool:
        """
        Detect poisoned/black captcha
        Black captcha = session is poisoned and needs to be recreated
        
        Black captcha indicators:
        - Very small file size (< 1500 bytes)
        - OCR returns garbage like "4333"
        """
        if len(image_bytes) < 1500:
            logger.critical("[BLACK CAPTCHA] Detected! Size: {} bytes - Session POISONED".format(len(image_bytes)))
            return True
        
        return False
    
    def validate_captcha_result(self, code: str, location: str = "VALIDATE") -> Tuple[bool, str]:
        """
        Validate captcha OCR result
        
        Rules based on German embassy website behavior:
        - 6 characters = VALID (normal captcha)
        - 7-8 characters = WARNING (session aging, too many refreshes)
        - < 4 or > 8 characters = INVALID (likely OCR error)
        - "4333" or similar repeated = BLACK CAPTCHA garbage
        
        Returns:
            (is_valid: bool, status: str)
            status: VALID, AGING, INVALID, BLACK_DETECTED, TOO_SHORT, TOO_LONG
        """
        if not code:
            logger.warning(f"[{location}] Empty captcha code")
            return False, "EMPTY"
        
        # Clean the code
        code = code.strip().replace(" ", "")
        code_len = len(code)
        
        # Detect black captcha garbage patterns
        # Only truly repeated patterns like "4444", "333", "0000" are garbage
        black_patterns = ["4333", "333", "444", "1111", "0000", "4444", "3333"]
        is_all_same = len(set(code)) == 1  # All characters are the same
        if code in black_patterns or is_all_same:
            logger.critical(f"[{location}] BLACK CAPTCHA pattern detected: '{code}'")
            return False, "BLACK_DETECTED"
        
        # Check length
        if code_len < 4:
            logger.warning(f"[{location}] Captcha too short: '{code}' ({code_len} chars)")
            return False, "TOO_SHORT"
        
        if code_len == 6:
            # Perfect! Normal captcha
            logger.info(f"[{location}] Valid 6-char captcha: '{code}'")
            return True, "VALID"
        
        if code_len == 7:
            # Warning - session aging, but still usable
            logger.warning(f"[{location}] 7-char captcha (session aging): '{code}'")
            return True, "AGING_7"
        
        if code_len == 8:
            # Critical warning - session near death
            logger.warning(f"[{location}] 8-char captcha (session near death): '{code}'")
            return True, "AGING_8"
        
        if code_len > 8:
            logger.error(f"[{location}] Captcha too long: '{code}' ({code_len} chars)")
            return False, "TOO_LONG"
        
        # 4-5 chars - REJECT! Embassy requires exactly 6 chars
        # OCR probably missed a character
        if code_len in [4, 5]:
            logger.warning(f"[{location}] OCR incomplete: '{code}' ({code_len} chars) -需要6个字符!")
            return False, "TOO_SHORT"
    def solve(self, image_bytes: bytes, location: str = "SOLVE") -> Tuple[str, str]:
        """
        Solve captcha from image bytes with validation
        
        German embassy captcha ALWAYS has 6 characters.
        If OCR returns less, we retry or reject.
        
        Returns:
            (captcha_code: str, status: str)
            status: VALID, AGING_7, AGING_8, BLACK_DETECTED, TOO_SHORT, etc.
        """
        if self.manual_only:
             logger.info(f"[{location}] Manual Mode active - Skipping OCR")
             return "", "MANUAL_REQUIRED"

        if not self.ocr:
            logger.error("[OCR] Engine not initialized")
            return "", "NO_OCR"
        
        try:
            # Detect black captcha first (by image size)
            if self.detect_black_captcha(image_bytes):
                return "", "BLACK_IMAGE"
            
            # Try OCR multiple times if result is short
            max_attempts = 3
            best_result = ""
            best_len = 0
            
            for attempt in range(max_attempts):
                # Solve using OCR
                result = self.ocr.predict(image_bytes)
                result = result.replace(" ", "").strip().lower()
                
                # Clean common OCR mistakes
                result = self._clean_ocr_result(result)
                
                current_len = len(result)
                
                # Keep the longest result
                if current_len > best_len:
                    best_result = result
                    best_len = current_len
                
                # If we got 6 chars, that's perfect - stop trying
                if current_len == 6:
                    break
                
                # If we got 7-8 chars (aging), that's acceptable
                if current_len >= 7:
                    break
                
                # Otherwise, try again
                if attempt < max_attempts - 1:
                    logger.debug(f"[{location}] OCR returned {current_len} chars, retrying... ({attempt+1}/{max_attempts})")
                    time.sleep(0.1)  # Small delay before retry
            
            # Use the best result we got
            result = best_result
            
            # Validate the result
            is_valid, status = self.validate_captcha_result(result, location)
            
            if not is_valid:
                logger.warning(f"[{location}] Invalid captcha result: '{result}' - Status: {status}")
                return "", status
            
            logger.info(f"[{location}] Captcha solved: '{result}' - Status: {status}")
            return result, status
            
        except Exception as e:
            logger.error(f"[{location}] Captcha solve error: {e}")
            return "", "ERROR"
    
    def _clean_ocr_result(self, text: str) -> str:
        """
        Clean common OCR mistakes for the German embassy captcha.
        The captcha uses lowercase letters and digits only.
        """
        # Remove any characters that shouldn't be there
        allowed_chars = set('abcdefghijklmnopqrstuvwxyz0123456789')
        cleaned = ''.join(c for c in text if c in allowed_chars)
        
        # Common OCR substitution corrections
        # OCR sometimes confuses similar-looking characters
        replacements = {
            'o': '0',  # letter o -> digit 0 (less common in captchas)
            'O': '0',
            'l': '1',  # lowercase L -> digit 1
            'I': '1',  # uppercase I -> digit 1
            'i': '1',  # lowercase i -> digit 1 (if at wrong position)
            's': '5',  # s -> 5
            'S': '5',
            'z': '2',  # z -> 2
            'Z': '2',
            'b': '6',  # b -> 6
            'g': '9',  # g -> 9
        }
        
        # Only apply if result is too short - maybe OCR got confused
        if len(cleaned) < 6:
            # Try alternate interpretations - disabled for now as it might make things worse
            pass
        
        return cleaned
    
    def pre_solve(self, page: Page, location: str = "PRE_SOLVE") -> Tuple[bool, Optional[str], str]:
        """
        Pre-solve captcha for instant submission later
        
        Returns:
            (success: bool, captcha_code: Optional[str], status: str)
        """
        try:
            # Check if captcha exists
            has_captcha, check_ok = self.safe_captcha_check(page, location)
            
            if not check_ok:
                logger.error(f"[{location}] Pre-solve captcha check failed")
                return False, None, "CHECK_FAILED"
            
            if not has_captcha:
                logger.debug(f"[{location}] No captcha to pre-solve")
                return True, None, "NO_CAPTCHA"
            
            # Find captcha image using unified method
            image_bytes = self._get_captcha_image(page, location)
            
            if not image_bytes:
                logger.warning(f"[{location}] Captcha image not found for pre-solve")
                return False, None, "NO_IMAGE"
            
            # Solve captcha with validation
            code, status = self.solve(image_bytes, location)
            
            if not code:
                logger.warning(f"[{location}] Pre-solve failed: {status}")
                return False, None, status
            
            # Cache the solution
            self._pre_solved_code = code
            self._pre_solved_time = time.time()
            self._pre_solved_status = status
            
            logger.info(f"[{location}] Pre-solved captcha: '{code}' - Status: {status}")
            return True, code, status
            
        except Exception as e:
            logger.error(f"[{location}] Pre-solve error: {e}")
            return False, None, "ERROR"
    
    def get_pre_solved(self) -> Optional[str]:
        """
        Get pre-solved captcha code if still valid
        
        Returns:
            Captcha code or None if expired/unavailable
        """
        if not self._pre_solved_code:
            return None
        
        # Check if expired
        age = time.time() - self._pre_solved_time
        if age > self._pre_solve_timeout:
            logger.warning("Pre-solved captcha expired")
            self._pre_solved_code = None
            return None
        
        return self._pre_solved_code
    
    def clear_pre_solved(self):
        """Clear pre-solved captcha"""
        self._pre_solved_code = None
        self._pre_solved_time = 0.0
    
    def solve_from_page(
        self, 
        page: Page, 
        location: str = "GENERAL",
        timeout: int = 10000,
        session_age: int = 0,
        attempt: int = 1,
        max_attempts: int = 5
    ) -> Tuple[bool, Optional[str]]:
        """
        Complete captcha solving workflow
        Uses pre-solved code if available, then OCR, then manual Telegram fallback
        
        Returns:
            (success: bool, captcha_code: Optional[str], status: str)
        """
        try:
            # Check if captcha exists
            has_captcha, check_ok = self.safe_captcha_check(page, location)
            
            if not check_ok:
                logger.error(f"[{location}] Captcha check failed")
                return False, None, "CHECK_FAILED"
            
            if not has_captcha:
                logger.debug(f"[{location}] No captcha present")
                return True, None, "NO_CAPTCHA"
            
            # Find captcha input field
            input_selector = None
            for selector in self._get_captcha_selectors():
                try:
                    if page.locator(selector).first.is_visible(timeout=1000):
                        input_selector = selector
                        break
                except:
                    continue
            
            if not input_selector:
                logger.warning(f"[{location}] Captcha input not found")
                return False, None, "NO_INPUT"
            
            # Check for pre-solved code first
            code = self.get_pre_solved()
            status = getattr(self, '_pre_solved_status', 'VALID')
            
            if code:
                logger.info(f"[{location}] Using pre-solved captcha: '{code}'")
                self.clear_pre_solved()
            else:
                # Find captcha image using unified method
                image_bytes = self._get_captcha_image(page, location)
                
                if not image_bytes:
                    logger.warning(f"[{location}] Captcha image not found")
                    return False, None, "NO_IMAGE"
                
                # Solve captcha with OCR validation
                code, status = self.solve(image_bytes, location)
                
                # ═══════════════════════════════════════════════════════════════
                # MANUAL FALLBACK: If OCR fails, try Telegram manual solving
                # ═══════════════════════════════════════════════════════════════
                is_auto_full = getattr(self, 'auto_full', False)
                if not code or status in ["TOO_SHORT", "TOO_LONG", "NO_OCR", "MANUAL_REQUIRED"]:
                    if is_auto_full:
                        logger.warning(f"[{location}] OCR failed ({status}) and Auto Full is ON - SKIPPING MANUAL")
                        return False, None, f"AUTO_FULL_SKIP_{status}"

                    logger.info(f"[{location}] OCR failed ({status}), trying manual Telegram...")
                    
                    # Request manual solution via Telegram
                    manual_code = self.manual_handler.request_manual_solution(
                        image_bytes=image_bytes,
                        location=location,
                        session_age=session_age,
                        attempt=attempt,
                        max_attempts=max_attempts
                    )
                    
                    if manual_code:
                        code = manual_code
                        status = "MANUAL"
                        logger.info(f"[{location}] Using manual solution: '{code}'")
                    else:
                        logger.warning(f"[{location}] Manual solve also failed/timeout")
                        return False, None, "MANUAL_TIMEOUT"
            
            # Fill captcha
            try:
                page.fill(input_selector, code, timeout=3000)
                logger.info(f"[{location}] Captcha filled: '{code}' - Status: {status}")
                return True, code, status
            except Exception as e:
                logger.error(f"[{location}] Failed to fill captcha: {e}")
                return False, None, "FILL_ERROR"
            
        except Exception as e:
            logger.error(f"[{location}] Captcha solving workflow error: {e}")
            return False, None, "ERROR"
    
    def submit_captcha(self, page: Page, method: str = "auto") -> bool:
        """
        Submit captcha with enhanced reliability
        """
        try:
            logger.info(f"[CAPTCHA] Submitting answer (Method: {method})...")
            
            # 1. Try generic submit buttons first if method is auto or click
            if method in ["auto", "click"]:
                # Specific buttons for this appointment system
                buttons = [
                    "input[name='submit']",
                    "input[value='Weiter']",
                    "input[value='Continue']",
                    "button:has-text('Weiter')",
                    "button:has-text('Continue')",
                    "input[type='submit']"
                ]
                
                for selector in buttons:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            logger.info(f"Clicked submit button: {selector}")
                            return True
                    except:
                        continue
            
            # 2. Fallback to Enter key (or if method='enter')
            page.keyboard.press("Enter")
            logger.info("Sent Enter key")
            return True
            
        except Exception as e:
            logger.error(f"[CAPTCHA] Submit error: {e}")
            return False
    
    def verify_captcha_solved(self, page: Page, location: str = "VERIFY") -> Tuple[bool, str]:
        """
        Verify if captcha was solved successfully by checking if we moved to next page
        or if captcha is still present.
        """
        logger.info(f"[{location}] Verifying captcha solution...")
        
        # Give it time to load - use extended timeout for manual mode
        start_time = time.time()
        timeout = 10.0 if getattr(self, 'manual_only', False) else 5.0
        
        while time.time() - start_time < timeout:
            try:
                current_url = page.url
                # Safe access to content - if navigating, this might fail, which is fine
                try:
                    content = page.content().lower()
                except Exception:
                    # Page is likely navigating/loading - this is actually a good sign!
                    time.sleep(0.5)
                    continue

                # 1. Check if we moved to Day view (Success)
                if "appointment_showday" in current_url.lower() or page.locator("a.arrow").count() > 0:
                     return True, "DAY_PAGE"
                
                # 2. Check for form page (Success)
                if "appointment_showform" in current_url.lower():
                    return True, "FORM_PAGE"

                # 3. Check for explicitly wrong captcha error
                if "security code" in content and ("valid" in content or "match" in content or "nicht korrekt" in content):
                     logger.warning(f"[{location}] Server reported WRONG captcha")
                     return False, "WRONG_CAPTCHA"

            except Exception as e:
                logger.debug(f"[{location}] Verification check transient error: {e}")
            
            time.sleep(0.5)
            
        # If we are still here, check if captcha is still visible
        has_captcha, _ = self.safe_captcha_check(page, location)
        if has_captcha:
             return False, "CAPTCHA_STILL_PRESENT"
             
        # If captcha is gone but we aren't on success page, assume success for now (maybe loading)
        return True, "UNKNOWN_PAGE"

    def reload_captcha(self, page: Page, location: str = "RELOAD") -> bool:
        """
        Reload captcha image by clicking "Load another picture" button.
        This is used when captcha solving fails - instead of going back to start,
        we just reload and try again.
        
        Returns:
            True if reload was successful
        """
        try:
            # FACT-BASED SELECTORS from RK-Termin form.html
            reload_selectors = [
                # 1. The exact ID from the booking form (RK-Termin form.html)
                "#appointment_newAppointmentForm_form_newappointment_refreshcaptcha",
                # 2. The name attribute from the booking form
                "input[name='action:appointment_refreshCaptcha']",
                # 3. The exact ID from the category form (RK-Termin - Kategorie.html)
                "#appointment_captcha_month_refreshcaptcha",
                "input[name='action:appointment_refreshCaptchamonth']",
                # 4. Fallbacks based on value (confirmed "Load another picture")
                "input[value='Load another picture']",
                "input[value='Bild laden']"
            ]
            
            for selector in reload_selectors:
                try:
                    button = page.locator(selector).first
                    if button.is_visible(timeout=1000):
                        # Try regular click first
                        try:
                            button.click(timeout=2000)
                        except:
                            # JavaScript fallback click
                            page.evaluate(f'document.querySelector("{selector}")?.click()')
                        
                        logger.info(f"[{location}] Clicked reload button - waiting for new captcha...")
                        page.wait_for_timeout(1500)
                        return True
                except:
                    continue
            
            # Final fallback: Try JavaScript to find any reload-related button
            try:
                result = page.evaluate("""
                    const buttons = Array.from(document.querySelectorAll('input[type="submit"], button'));
                    for(const btn of buttons) {
                        const val = (btn.value || btn.textContent || '').toLowerCase();
                        if(val.includes('another') || val.includes('refresh') || val.includes('reload') || val.includes('anderes')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                """)
                if result:
                    logger.info(f"[{location}] Clicked reload via JS fallback")
                    page.wait_for_timeout(1500)
                    return True
            except:
                pass
            
            logger.warning(f"[{location}] Could not find reload captcha button")
            return False
            
        except Exception as e:
            logger.error(f"[{location}] Reload captcha error: {e}")
            return False
    
    def solve_form_captcha_with_retry(
        self, 
        page: Page, 
        location: str = "FORM_RETRY",
        max_attempts: int = 5,
        session_age: int = 0
    ) -> Tuple[bool, Optional[str], str]:
        """
        Solve form captcha with retry logic.
        
        IMPORTANT: This method is used specifically for FORM page captcha.
        When captcha solving fails, instead of returning to start,
        it clicks "Load another picture" and tries again.
        
        This is the SMART logic: we don't lose our valuable slot by going back,
        we just reload the captcha and try again until we succeed.
        
        Args:
            page: Playwright page
            location: Log location identifier
            max_attempts: Maximum number of attempts
            
        Returns:
            (success: bool, captcha_code: Optional[str], status: str)
        """
        if self.manual_only:
            logger.info("🛠️ MANUAL MODE: Enabling INFINITE RETRY loop on form page!")
            max_attempts = 1000  # Virtually infinite for manual mode
            
        for attempt in range(max_attempts):
            attempt_num = attempt + 1
            
            logger.info(f"[{location}] Captcha attempt {attempt_num}/{max_attempts}")
            
            # Try to solve
            success, code, status = self.solve_from_page(
                page, 
                f"{location}_A{attempt_num}",
                session_age=session_age,
                attempt=attempt_num,
                max_attempts=1 # Inside the loop we scan once per cycle
            )
            
            if success and code:
                # Got a valid solution!
                logger.info(f"[{location}] SUCCESS on attempt {attempt_num}: '{code}'")
                return True, code, status
            
            # Failed - try to reload captcha
            if attempt < max_attempts - 1:  # Don't reload on last attempt
                logger.warning(f"[{location}] Attempt {attempt_num} failed ({status}), reloading captcha...")
                
                # Check session age to prevent zombie loops
                if session_age > 1800: # 30 minutes
                     logger.critical(f"[{location}] Session too old during infinite loop - aborting")
                     return False, None, "SESSION_TOO_OLD"

                if not self.reload_captcha(page, f"{location}_RELOAD"):
                    logger.error(f"[{location}] Could not reload captcha - aborting")
                    # If reload click fails (button gone?), we might have lost the page. Return False.
                    return False, None, "RELOAD_FAILED"
                
                # Small delay after reload
                time.sleep(1.0)
        
        # All attempts failed
        logger.error(f"[{location}] All {max_attempts} attempts failed")
        return False, None, "MAX_ATTEMPTS_REACHED"


# Backward compatibility
class CaptchaSolver:
    """Original captcha solver for backward compatibility"""
    
    def __init__(self):
        if DDDDOCR_AVAILABLE:
            self.ocr = ddddocr.DdddOcr(beta=True)
        else:
            self.ocr = None
    
    def solve(self, image_bytes: bytes) -> str:
        if not self.ocr:
            return ""
        try:
            res = self.ocr.predict(image_bytes)
            res = res.replace(" ", "").strip()
            print(f"[AI] Captcha Solved: {res}")
            return res
        except Exception as e:
            print(f"[AI] Error solving captcha: {e}")
            return ""