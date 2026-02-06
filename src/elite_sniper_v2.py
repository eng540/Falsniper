"""
Elite Sniper v2.1 - Enhanced Production-Grade Appointment System
WITH NETWORK RESILIENCE AND HEALTH MONITORING
FIXED VERSION WITH PROPER LOGGER HANDLING
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

# ==================== LOGGING SETUP (MUST BE FIRST) ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('elite_sniper_v2.log')
    ]
)

# Create module-level logger
logger = logging.getLogger("EliteSniperV2")

# ==================== INTERNAL IMPORTS ====================

try:
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
except ImportError:
    # Fallback for testing
    logger.warning("Some internal imports failed - running in fallback mode")
    
    # Mock classes for fallback
    class Config:
        TARGET_URL = ""
        LAST_NAME = ""
        FIRST_NAME = ""
        EMAIL = ""
        PASSPORT = ""
        PHONE = ""
        TIMEZONE = "Asia/Aden"
        HEADLESS = True
        NTP_SERVERS = ["pool.ntp.org"]
        NTP_SYNC_INTERVAL = 300
        ATTACK_HOUR = 2
        PRE_ATTACK_MINUTE = 59
        PRE_ATTACK_SECOND = 30
        ATTACK_WINDOW_MINUTES = 2
        ATTACK_SLEEP_MIN = 0.1
        ATTACK_SLEEP_MAX = 0.3
        PRE_ATTACK_SLEEP = 0.1
        WARMUP_SLEEP = 1.0
        PATROL_SLEEP_MIN = 10.0
        PATROL_SLEEP_MAX = 20.0
        HEARTBEAT_INTERVAL = 30
        SESSION_MAX_AGE = 60
        SESSION_MAX_IDLE = 15
        MAX_CONSECUTIVE_ERRORS = 3
        MAX_CAPTCHA_ATTEMPTS = 3
        EVIDENCE_DIR = "evidence"
        BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]
        CATEGORY_IDS = {}
    
    class NTPTimeSync:
        def __init__(self, servers, interval):
            self.offset = 0.0
        def start_background_sync(self): pass
        def stop_background_sync(self): pass
        def get_corrected_time(self): return datetime.datetime.utcnow()
    
    class SessionState:
        def __init__(self, **kwargs): pass
        def is_expired(self): return False
        def age(self): return 0
        def idle_time(self): return 0
        def should_terminate(self): return False
        def touch(self): pass
        def increment_failure(self, reason): pass
        def mark_captcha_solved(self): pass
        def reset_for_new_flow(self): pass
    
    class SessionStats:
        def __init__(self): 
            self.rebirths = 0
            self.pages_loaded = 0
            self.months_scanned = 0
            self.scans = 0
            self.days_found = 0
            self.slots_found = 0
            self.captchas_solved = 0
            self.captchas_failed = 0
            self.navigation_errors = 0
            self.forms_filled = 0
            self.success = False
        def to_dict(self): return {}
        def get_summary(self): return ""
    
    class SystemState:
        STANDBY = "STANDBY"
    
    class SessionHealth:
        CLEAN = "CLEAN"
        WARNING = "WARNING"
        DEGRADED = "DEGRADED"
        POISONED = "POISONED"
    
    class SessionRole:
        SCOUT = "SCOUT"
        ATTACKER = "ATTACKER"
    
    class Incident:
        pass
    
    class IncidentManager:
        def create_incident(self, *args): pass
    
    class IncidentType:
        SESSION_EXPIRED = "SESSION_EXPIRED"
        SESSION_POISONED = "SESSION_POISONED"
        DOUBLE_CAPTCHA = "DOUBLE_CAPTCHA"
        FORM_REJECTED = "FORM_REJECTED"
        SLOT_DETECTED = "SLOT_DETECTED"
        BOOKING_ATTEMPT = "BOOKING_ATTEMPT"
    
    class IncidentSeverity:
        CRITICAL = "CRITICAL"
        ERROR = "ERROR"
        INFO = "INFO"
    
    class EnhancedCaptchaSolver:
        def __init__(self, manual_only=False):
            self.auto_full = False
        def solve_from_page(self, *args): return True, "TEST", "SUCCESS"
        def safe_captcha_check(self, *args): return False, True
        def submit_captcha(self, *args): pass
        def reload_captcha(self, *args): pass
        def verify_captcha_solved(self, *args): return True, "PAGE"
    
    def send_alert(msg): logger.info(f"[ALERT] {msg}")
    def send_success_notification(session_id, worker_id, msg): logger.info(f"[SUCCESS] {msg}")
    
    class DebugManager:
        def __init__(self, session_id, evidence_dir):
            self.session_dir = evidence_dir
        def save_debug_html(self, *args): pass
        def save_critical_screenshot(self, *args): pass
        def save_forensic_state(self, *args): pass
        def save_stats(self, *args): pass
        def create_session_report(self, *args): pass
    
    class PageFlowDetector:
        pass

# ==================== ENHANCEMENT CLASSES WITH FIXED LOGGER ====================

class NetworkHealthMonitor:
    """مراقب صحة الشبكة مع Circuit Breaker pattern"""
    
    def __init__(self, max_consecutive_failures: int = 5, reset_timeout: int = 300):
        self.failures = 0
        self.consecutive_failures = 0
        self.total_attempts = 0
        self.last_success = None
        self.last_failure = None
        self.circuit_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.circuit_opened_at = None
        self.max_failures = max_consecutive_failures
        self.reset_timeout = reset_timeout
        self.lock = Lock()
        
        # إحصائيات مفصلة
        self.stats = {
            'timeouts': 0,
            'connection_errors': 0,
            'other_errors': 0,
            'successes': 0
        }
        
        # Use module logger
        self.logger = logging.getLogger("EliteSniperV2.NetworkHealth")
    
    def record_attempt(self, success: bool, error_type: str = None):
        """تسجيل محاولة اتصال"""
        with self.lock:
            self.total_attempts += 1
            
            if success:
                self._record_success()
            else:
                self._record_failure(error_type)
            
            return self.should_proceed()
    
    def _record_success(self):
        """تسجيل نجاح"""
        self.failures = 0
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.stats['successes'] += 1
        
        if self.circuit_state == "HALF_OPEN":
            self.circuit_state = "CLOSED"
            self.logger.info("✅ Circuit CLOSED - Network recovered")
        elif self.circuit_state == "OPEN":
            self.circuit_state = "HALF_OPEN"
            self.logger.info("🟡 Circuit HALF_OPEN - Testing recovery")
    
    def _record_failure(self, error_type: str):
        """تسجيل فشل"""
        self.failures += 1
        self.consecutive_failures += 1
        self.last_failure = time.time()
        
        # تحديث الإحصائيات حسب نوع الخطأ
        if error_type == "timeout":
            self.stats['timeouts'] += 1
        elif error_type == "connection":
            self.stats['connection_errors'] += 1
        else:
            self.stats['other_errors'] += 1
        
        # تفعيل Circuit Breaker إذا لزم الأمر
        if (self.consecutive_failures >= self.max_failures and 
            self.circuit_state == "CLOSED"):
            self.circuit_state = "OPEN"
            self.circuit_opened_at = time.time()
            self.logger.critical(f"🚨 CIRCUIT BREAKER OPENED after {self.consecutive_failures} consecutive failures")
            
            # إرسال إنذار فوري
            try:
                send_alert(
                    f"🚨 <b>NETWORK CRITICAL FAILURE</b>\n"
                    f"Circuit breaker activated!\n"
                    f"Consecutive failures: {self.consecutive_failures}\n"
                    f"Total attempts: {self.total_attempts}\n"
                    f"Will retry in {self.reset_timeout//60} minutes"
                )
            except Exception as e:
                self.logger.error(f"Failed to send alert: {e}")
    
    def should_proceed(self) -> bool:
        """هل يجب المتابعة أم الانتظار؟"""
        if self.circuit_state == "CLOSED":
            return True
        elif self.circuit_state == "OPEN":
            # تحقق إذا انتهى وقت الانتظار
            if time.time() - self.circuit_opened_at > self.reset_timeout:
                self.circuit_state = "HALF_OPEN"
                self.logger.warning("🔄 Circuit transitioning to HALF_OPEN for testing")
                return True
            return False
        elif self.circuit_state == "HALF_OPEN":
            return True  # في وضع الاختبار، نسمح بمحاولة واحدة
    
    def get_retry_delay(self) -> float:
        """احسب تأخير إعادة المحاولة بشكل ذكي"""
        if self.consecutive_failures == 0:
            return random.uniform(2, 5)  # مهلة عادية
        
        # Exponential backoff مع حد أقصى 5 دقائق
        delay = min(300, 2 ** min(self.consecutive_failures, 8))
        
        # إضافة عشوائية لتجنب التزامن
        jitter = random.uniform(0.8, 1.2)
        
        final_delay = delay * jitter
        self.logger.info(f"⏳ Smart retry delay: {final_delay:.1f}s (Failures: {self.consecutive_failures})")
        return final_delay
    
    def get_health_report(self) -> Dict:
        """تقرير صحة الشبكة"""
        with self.lock:
            success_rate = (self.stats['successes'] / max(1, self.total_attempts)) * 100
            
            return {
                'circuit_state': self.circuit_state,
                'total_attempts': self.total_attempts,
                'consecutive_failures': self.consecutive_failures,
                'success_rate': f"{success_rate:.1f}%",
                'stats': self.stats.copy(),
                'last_success': self._format_time(self.last_success),
                'last_failure': self._format_time(self.last_failure),
                'health_score': self._calculate_health_score()
            }
    
    def _calculate_health_score(self) -> float:
        """حساب درجة الصحة (0-100)"""
        if self.total_attempts == 0:
            return 100
        
        success_rate = (self.stats['successes'] / self.total_attempts) * 100
        
        # عقوبة الفشل المتتالي
        failure_penalty = min(50, self.consecutive_failures * 15)
        
        # عقوبة حالة Circuit OPEN
        circuit_penalty = 0
        if self.circuit_state == "OPEN":
            circuit_penalty = 30
        elif self.circuit_state == "HALF_OPEN":
            circuit_penalty = 15
        
        return max(0, success_rate - failure_penalty - circuit_penalty)
    
    def _format_time(self, timestamp: float) -> str:
        """تنسيق الوقت للإنسان"""
        if not timestamp:
            return "Never"
        
        delta = time.time() - timestamp
        if delta < 60:
            return f"{int(delta)}s ago"
        elif delta < 3600:
            return f"{int(delta/60)}m ago"
        else:
            return f"{int(delta/3600)}h ago"


class PerformanceOptimizer:
    """محسن أداء مع تقليل الحمل على الخادم"""
    
    def __init__(self):
        self.request_count = 0
        self.last_request_time = time.time()
        self.request_timestamps = []
        
        # إعدادات التحكم في المعدل
        self.rate_limits = {
            'normal': 1.0,      # طلب واحد في الثانية
            'aggressive': 0.5,  # طلبين في الثانية (هجوم)
            'conservative': 2.0 # طلب كل ثانيتين (حفظاً)
        }
        
        self.current_rate = 'normal'
        self.logger = logging.getLogger("EliteSniperV2.Performance")
    
    def should_make_request(self) -> bool:
        """هل يجب عمل طلب الآن أم الانتظار؟"""
        now = time.time()
        
        # تنظيف الطلبات القديمة
        cutoff = now - 60  # آخر دقيقة
        self.request_timestamps = [t for t in self.request_timestamps if t > cutoff]
        
        # حساب المعدل الحالي
        current_rate = len(self.request_timestamps) / 60.0  # طلبات في الثانية
        
        # تحديد المعدل المناسب
        if current_rate > 2.0:
            self.current_rate = 'conservative'
            wait_time = self.rate_limits['conservative']
            self.logger.debug(f"⚠️ High request rate ({current_rate:.2f}/s), switching to conservative mode")
        elif current_rate < 0.2:
            self.current_rate = 'aggressive'
            wait_time = self.rate_limits['aggressive']
        else:
            self.current_rate = 'normal'
            wait_time = self.rate_limits['normal']
        
        # التحقق من الوقت منذ آخر طلب
        time_since_last = now - self.last_request_time
        if time_since_last >= wait_time:
            self.request_timestamps.append(now)
            self.last_request_time = now
            return True
        
        # الانتظار المتبقي
        remaining = wait_time - time_since_last
        if remaining > 0.1:  # فقط إذا كان الانتظار كبير
            time.sleep(min(remaining, 1.0))
        
        self.request_timestamps.append(time.time())
        self.last_request_time = time.time()
        return True
    
    def get_status(self) -> Dict:
        """حالة التحكم في المعدل"""
        now = time.time()
        recent_requests = [t for t in self.request_timestamps if now - t < 60]
        
        return {
            'current_rate': self.current_rate,
            'requests_last_minute': len(recent_requests),
            'avg_rate_per_second': len(recent_requests) / 60.0,
            'time_since_last': now - self.last_request_time
        }


# ==================== MAIN EliteSniperV2 CLASS ====================

class EliteSniperV2:
    """
    Production-Grade Multi-Session Appointment Booking System
    ENHANCED VERSION WITH NETWORK RESILIENCE
    """
    
    VERSION = "2.1.0 RESILIENT"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Elite Sniper v2.1 RESILIENT"""
        self.run_mode = run_mode
        
        # Use the module logger
        self.logger = logger
        
        self.logger.info("=" * 70)
        self.logger.info(f"[INIT] ELITE SNIPER {self.VERSION} - RESILIENT EDITION")
        self.logger.info(f"[MODE] Running Mode: {self.run_mode}")
        self.logger.info("[FEATURE] Network resilience: ✓ | Health monitoring: ✓ | Circuit breaker: ✓")
        self.logger.info("=" * 70)
        
        # Validate configuration
        self._validate_config()
        
        # Session management
        self.session_id = f"elite_v2.1_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        # System state
        self.system_state = SystemState.STANDBY
        self.stop_event = Event()      # Global kill switch
        self.slot_event = Event()      # Scout → Attacker signal
        self.target_url: Optional[str] = None  # Discovered appointment URL
        self.lock = Lock()              # Thread-safe coordination
        
        # NEW: Resilience components
        self.health_monitor = NetworkHealthMonitor(max_consecutive_failures=3, reset_timeout=180)
        self.performance_opt = PerformanceOptimizer()
        
        # Existing components
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full:
            self.logger.info("[MODE] AUTO FULL ENABLED (No Manual Fallback)")
            self.solver.auto_full = True
        
        self.debug_manager = DebugManager(self.session_id, Config.EVIDENCE_DIR)
        self.incident_manager = IncidentManager()
        self.ntp_sync = NTPTimeSync(Config.NTP_SERVERS, Config.NTP_SYNC_INTERVAL)
        self.page_flow = PageFlowDetector()
        
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
        
        self.logger.info(f"[ID] Session ID: {self.session_id}")
        self.logger.info(f"[URL] Base URL: {self.base_url[:60]}...")
        self.logger.info(f"[TZ] Timezone: {self.timezone}")
        self.logger.info(f"[NTP] NTP Offset: {self.ntp_sync.offset:.4f}s")
        self.logger.info(f"[DIR] Evidence Dir: {self.debug_manager.session_dir}")
        self.logger.info(f"[PROXY] Proxies: {len([p for p in self.proxies if p])} configured")
        self.logger.info(f"[RESILIENCE] Health monitor: ✓ | Rate control: ✓ | Circuit breaker: ✓")
        self.logger.info(f"[OK] Initialization complete")
    
    # ==================== CONFIGURATION METHODS ====================
    
    def _validate_config(self):
        """Validate required configuration"""
        required = [
            'TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 
            'EMAIL', 'PASSPORT', 'PHONE'
        ]
        
        missing = [field for field in required if not getattr(Config, field, None)]
        
        if missing:
            raise ValueError(f"[ERR] Missing configuration: {', '.join(missing)}")
        
        self.logger.info("[OK] Configuration validated")
    
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
            self.logger.warning(f"⚠️ Failed to load proxies.txt: {e}")
        
        # Ensure we have at least 3 slots (None = direct connection)
        while len(proxies) < 3:
            proxies.append(None)
        
        return proxies[:3]  # Only use first 3
    
    # ==================== ENHANCED NAVIGATION METHOD ====================
    
    def smart_goto(self, page: Page, url: str, location: str = "UNKNOWN", worker_id: int = 1) -> bool:
        """
        تنقل ذكي مع مراقبة الصحة واستراتيجيات التعافي
        """
        start_time = time.time()
        
        # التحقق من صحة الشبكة أولاً
        if not self.health_monitor.should_proceed():
            health = self.health_monitor.get_health_report()
            self.logger.warning(
                f"⏸️ [W{worker_id}][{location}] Circuit breaker {health['circuit_state']} - "
                f"Delaying request (Failures: {health['consecutive_failures']})"
            )
            
            # انتظار ذكي قبل إعادة المحاولة
            delay = self.health_monitor.get_retry_delay()
            time.sleep(delay)
            return False
        
        # التحكم في معدل الطلبات
        if not self.performance_opt.should_make_request():
            self.logger.debug(f"⏳ [W{worker_id}][{location}] Rate limiting active")
            time.sleep(0.5)
        
        try:
            # المحاولة مع مهلة ذكية
            timeout = 30000  # 30 ثانية
            
            # تقليل المهلة بناءً على صحة الشبكة
            health_score = self.health_monitor.get_health_report()['health_score']
            if health_score < 50:
                timeout = 15000  # نصف المهلة إذا كانت الصحة ضعيفة
            
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            
            response_time = time.time() - start_time
            
            # تسجيل النجاح
            self.health_monitor.record_attempt(success=True)
            
            self.logger.info(
                f"✓ [W{worker_id}][{location}] Navigation succeeded in {response_time:.2f}s "
                f"(Health: {self.health_monitor.get_health_report()['health_score']:.1f}%)"
            )
            
            with self.lock:
                self.global_stats.pages_loaded += 1
            
            return True
            
        except Exception as e:
            response_time = time.time() - start_time
            error_str = str(e).lower()
            
            # تحديد نوع الخطأ
            error_type = "other"
            if "timeout" in error_str:
                error_type = "timeout"
            elif "connection" in error_str or "network" in error_str:
                error_type = "connection"
            
            # تسجيل الفشل
            self.health_monitor.record_attempt(success=False, error_type=error_type)
            
            # الحصول على تقرير الصحة الحالي
            health = self.health_monitor.get_health_report()
            
            self.logger.warning(
                f"✗ [W{worker_id}][{location}] Navigation failed in {response_time:.2f}s: "
                f"{error_type.upper()} - Health: {health['health_score']:.1f}% "
                f"(Circuit: {health['circuit_state']})"
            )
            
            with self.lock:
                self.global_stats.navigation_errors += 1
            
            return False
    
    # ==================== SIMPLIFIED RUN METHOD (FOR IMMEDIATE DEPLOYMENT) ====================
    
    def run(self) -> bool:
        """
        Main execution entry point - SIMPLIFIED FOR IMMEDIATE DEPLOYMENT
        """
        self.logger.info("=" * 70)
        self.logger.info(f"[ELITE SNIPER {self.VERSION}] - STARTING EXECUTION")
        self.logger.info("[MODE] Single Session with Enhanced Resilience")
        self.logger.info("=" * 70)
        
        try:
            # Send startup notification
            try:
                send_alert(
                    f"[Elite Sniper {self.VERSION} Started]\n"
                    f"Session: {self.session_id}\n"
                    f"Mode: {self.run_mode}\n"
                    f"Enhanced with Network Resilience"
                )
            except Exception as e:
                self.logger.error(f"Failed to send startup alert: {e}")
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                self.logger.info("[BROWSER] Launched successfully")
                
                # Create context
                context = browser.new_context(
                    user_agent=random.choice(self.user_agents),
                    viewport={"width": 1366, "height": 768},
                    locale="en-US"
                )
                page = context.new_page()
                
                try:
                    # Test connection first
                    self.logger.info("[TEST] Testing connection to target server...")
                    
                    # Generate test URLs
                    test_urls = self.generate_month_urls()
                    
                    for i, url in enumerate(test_urls[:2]):  # Test only 2 URLs
                        if self.stop_event.is_set():
                            break
                        
                        self.logger.info(f"[TEST {i+1}/2] Testing: {url[:60]}...")
                        
                        success = self.smart_goto(page, url, f"TEST_{i+1}", 1)
                        
                        if success:
                            self.logger.info(f"[TEST {i+1}] ✓ Connection successful!")
                            
                            # Check for captcha
                            has_captcha, _ = self.solver.safe_captcha_check(page, "TEST")
                            if has_captcha:
                                self.logger.info("[TEST] Captcha detected - system is responsive")
                            else:
                                self.logger.info("[TEST] No captcha - ready for operation")
                            
                            # Close test context
                            context.close()
                            
                            # Start main operation
                            return self._start_main_operation(browser)
                        else:
                            self.logger.warning(f"[TEST {i+1}] ✗ Connection failed")
                    
                    # If all tests failed
                    health = self.health_monitor.get_health_report()
                    self.logger.critical(f"🚨 ALL CONNECTION TESTS FAILED!")
                    self.logger.critical(f"Health Score: {health['health_score']:.1f}%")
                    self.logger.critical(f"Circuit State: {health['circuit_state']}")
                    self.logger.critical(f"Total Failures: {health['consecutive_failures']}")
                    
                    # Send critical alert
                    try:
                        send_alert(
                            f"🚨 <b>CRITICAL NETWORK FAILURE</b>\n"
                            f"All connection tests failed!\n"
                            f"Session: {self.session_id}\n"
                            f"Health Score: {health['health_score']:.1f}%\n"
                            f"Circuit State: {health['circuit_state']}\n"
                            f"Recommendation: Check network/internet connection"
                        )
                    except:
                        pass
                    
                    return False
                    
                except Exception as e:
                    self.logger.error(f"[TEST ERROR] {e}")
                    return False
                finally:
                    try:
                        context.close()
                    except:
                        pass
                    
        except Exception as e:
            self.logger.error(f"💀 Critical error: {e}", exc_info=True)
            return False
    
    def _start_main_operation(self, browser: Browser) -> bool:
        """Start the main booking operation after successful test"""
        self.logger.info("[MAIN] Starting main booking operation...")
        
        # Create main context
        context = browser.new_context(
            user_agent=random.choice(self.user_agents),
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = context.new_page()
        
        try:
            max_cycles = 100
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    break
                
                # Get month URLs
                month_urls = self.generate_month_urls()
                self.logger.info(f"[CYCLE {cycle+1}] Scanning {len(month_urls)} months...")
                
                for i, url in enumerate(month_urls):
                    if self.stop_event.is_set():
                        break
                    
                    self.logger.debug(f"[SCAN {i+1}/{len(month_urls)}] {url[:60]}...")
                    
                    # Use smart navigation
                    success = self.smart_goto(page, url, f"MONTH_{i+1}", 1)
                    
                    if not success:
                        continue
                    
                    # Check for appointments
                    content = page.content().lower()
                    if "no appointments" not in content and "keine termine" not in content:
                        self.logger.critical(f"🔥 APPOINTMENTS MAY BE AVAILABLE!")
                        
                        # Save evidence
                        try:
                            screenshot_path = f"evidence/possible_slots_cycle{cycle+1}.png"
                            page.screenshot(path=screenshot_path, full_page=True)
                            self.logger.info(f"[EVIDENCE] Saved screenshot: {screenshot_path}")
                        except:
                            pass
                        
                        # Send alert
                        try:
                            send_alert(
                                f"🔥 <b>POSSIBLE APPOINTMENTS DETECTED!</b>\n"
                                f"Cycle: {cycle+1}\n"
                                f"URL: {url[:50]}...\n"
                                f"Health: {self.health_monitor.get_health_report()['health_score']:.1f}%"
                            )
                        except:
                            pass
                
                # Sleep between cycles
                sleep_time = random.uniform(10, 20)
                health = self.health_monitor.get_health_report()
                
                if health['health_score'] < 50:
                    sleep_time *= 2
                    self.logger.info(f"[SLEEP] Extended to {sleep_time:.1f}s due to poor health")
                
                self.logger.info(f"[SLEEP] {sleep_time:.1f}s")
                time.sleep(sleep_time)
            
            self.logger.info("[END] Max cycles reached")
            return False
            
        except Exception as e:
            self.logger.error(f"[OPERATION ERROR] {e}")
            return False
        finally:
            try:
                context.close()
            except:
                pass
    
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
            self.logger.error(f"❌ Month URL generation failed: {e}")
            return []


# ==================== SIMPLE ENTRY POINT ====================

if __name__ == "__main__":
    try:
        # Try to run with resilience
        sniper = EliteSniperV2(run_mode="AUTO_FULL")
        success = sniper.run()
        
        # Save final health report
        health_report = sniper.health_monitor.get_health_report()
        logger.info(f"Final Health Score: {health_report['health_score']:.1f}%")
        logger.info(f"Success Rate: {health_report['success_rate']}")
        logger.info(f"Total Attempts: {health_report['total_attempts']}")
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
        sys.exit(1)