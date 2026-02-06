"""
Elite Sniper v2.1 - Enhanced Production-Grade Appointment System
WITH NETWORK RESILIENCE AND HEALTH MONITORING

MAINTAINS ALL ORIGINAL FUNCTIONALITY:
- Multi-session architecture (Scout/Attacker pattern)
- Multi-language success detection
- Advanced captcha solving
- Full booking flow
- All original methods preserved

ENHANCEMENTS ADDED:
1. Network failure detection and recovery
2. Smart retry with exponential backoff
3. Real-time health monitoring
4. Circuit breaker pattern
5. Performance optimization

Version: 2.1.0 ENHANCED (Full Preservation)
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

# Internal imports - ALL PRESERVED
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

# ==================== NEW ENHANCEMENTS (ADDED, NOT REPLACED) ====================

class NetworkHealthMonitor:
    """مراقب صحة الشبكة مع Circuit Breaker pattern - NEW ADDITION"""
    
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
            logger.info("✅ Circuit CLOSED - Network recovered")
        elif self.circuit_state == "OPEN":
            self.circuit_state = "HALF_OPEN"
            logger.info("🟡 Circuit HALF_OPEN - Testing recovery")
    
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
            logger.critical(f"🚨 CIRCUIT BREAKER OPENED after {self.consecutive_failures} consecutive failures")
            
            # إرسال إنذار فوري
            try:
                send_alert(
                    f"🚨 <b>NETWORK CRITICAL FAILURE</b>\n"
                    f"Circuit breaker activated!\n"
                    f"Consecutive failures: {self.consecutive_failures}\n"
                    f"Total attempts: {self.total_attempts}\n"
                    f"Will retry in {self.reset_timeout//60} minutes"
                )
            except:
                pass
    
    def should_proceed(self) -> bool:
        """هل يجب المتابعة أم الانتظار؟"""
        if self.circuit_state == "CLOSED":
            return True
        elif self.circuit_state == "OPEN":
            # تحقق إذا انتهى وقت الانتظار
            if time.time() - self.circuit_opened_at > self.reset_timeout:
                self.circuit_state = "HALF_OPEN"
                logger.warning("🔄 Circuit transitioning to HALF_OPEN for testing")
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
        logger.info(f"⏳ Smart retry delay: {final_delay:.1f}s (Failures: {self.consecutive_failures})")
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
    """محسن أداء مع تقليل الحمل على الخادم - NEW ADDITION"""
    
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
            logger.debug(f"⚠️ High request rate ({current_rate:.2f}/s), switching to conservative mode")
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


# ==================== ORIGINAL EliteSniperV2 CLASS - FULLY PRESERVED ====================

class EliteSniperV2:
    """
    Production-Grade Multi-Session Appointment Booking System
    FINAL VERSION WITH MULTI-LANGUAGE SUCCESS DETECTION
    
    ORIGINAL CODE FULLY PRESERVED with ENHANCEMENTS ADDED
    """
    
    VERSION = "2.1.0 ENHANCED"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Elite Sniper v2.1 ENHANCED - PRESERVING ALL ORIGINAL FUNCTIONALITY"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER {self.VERSION} - ENHANCED WITH RESILIENCE")
        logger.info(f"[MODE] Running Mode: {self.run_mode}")
        logger.info("=" * 70)
        
        # Validate configuration - ORIGINAL
        self._validate_config()
        
        # Session management - ORIGINAL
        self.session_id = f"elite_v2_{int(time.time())}_{random.randint(1000, 9999)}"
        self.start_time = datetime.datetime.now()
        
        # System state - ORIGINAL
        self.system_state = SystemState.STANDBY
        self.stop_event = Event()      # Global kill switch
        self.slot_event = Event()      # Scout → Attacker signal
        self.target_url: Optional[str] = None  # Discovered appointment URL
        self.lock = Lock()              # Thread-safe coordination
        
        # Components - ORIGINAL
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
        
        # NEW: Enhanced components - ADDED, NOT REPLACED
        self.health_monitor = NetworkHealthMonitor(max_consecutive_failures=3, reset_timeout=180)
        self.performance_opt = PerformanceOptimizer()
        
        # Configuration - ORIGINAL
        self.base_url = self._prepare_base_url(Config.TARGET_URL)
        self.timezone = pytz.timezone(Config.TIMEZONE)
        
        # User agents for rotation - ORIGINAL
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        
        # Proxies (optional) - ORIGINAL
        self.proxies = self._load_proxies()
        
        # Global statistics - ORIGINAL
        self.global_stats = SessionStats()
        
        # Start background NTP sync - ORIGINAL
        self.ntp_sync.start_background_sync()
        
        logger.info(f"[ID] Session ID: {self.session_id}")
        logger.info(f"[URL] Base URL: {self.base_url[:60]}...")
        logger.info(f"[TZ] Timezone: {self.timezone}")
        logger.info(f"[NTP] NTP Offset: {self.ntp_sync.offset:.4f}s")
        logger.info(f"[DIR] Evidence Dir: {self.debug_manager.session_dir}")
        logger.info(f"[PROXY] Proxies: {len([p for p in self.proxies if p])} configured")
        logger.info(f"[RESILIENCE] Health monitor: ✓ | Rate control: ✓ | Circuit breaker: ✓")
        logger.info(f"[OK] Initialization complete")
    
    # ==================== ENHANCED NAVIGATION METHOD - ADDED, NOT REPLACED ====================
    
    def smart_goto(self, page: Page, url: str, location: str = "UNKNOWN", worker_id: int = 1) -> bool:
        """
        تنقل ذكي مع مراقبة الصحة واستراتيجيات التعافي
        NEW METHOD - ENHANCES ORIGINAL FUNCTIONALITY
        
        Returns:
            True إذا نجح الاتصال، False إذا فشل
        """
        start_time = time.time()
        
        # التحقق من صحة الشبكة أولاً - NEW
        if not self.health_monitor.should_proceed():
            health = self.health_monitor.get_health_report()
            logger.warning(
                f"⏸️ [W{worker_id}][{location}] Circuit breaker {health['circuit_state']} - "
                f"Delaying request (Failures: {health['consecutive_failures']})"
            )
            
            # إرسال إنذار إذا كانت الحالة حرجة - NEW
            if health['health_score'] < 30:
                try:
                    send_alert(
                        f"⚠️ <b>NETWORK HEALTH CRITICAL</b>\n"
                        f"Worker: W{worker_id}\n"
                        f"Health Score: {health['health_score']:.1f}%\n"
                        f"Circuit State: {health['circuit_state']}\n"
                        f"Failures: {health['consecutive_failures']}"
                    )
                except:
                    pass
            
            # انتظار ذكي قبل إعادة المحاولة - NEW
            delay = self.health_monitor.get_retry_delay()
            time.sleep(delay)
            return False
        
        # التحكم في معدل الطلبات - NEW
        if not self.performance_opt.should_make_request():
            logger.debug(f"⏳ [W{worker_id}][{location}] Rate limiting active")
            time.sleep(0.5)
        
        try:
            # المحاولة مع مهلة ذكية - ENHANCED
            timeout = 30000  # الأصل: 30000
            
            # تقليل المهلة بناءً على صحة الشبكة - NEW
            health_score = self.health_monitor.get_health_report()['health_score']
            if health_score < 50:
                timeout = 15000  # نصف المهلة إذا كانت الصحة ضعيفة
            
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            
            response_time = time.time() - start_time
            
            # تسجيل النجاح - NEW
            self.health_monitor.record_attempt(success=True)
            
            logger.info(
                f"✓ [W{worker_id}][{location}] Navigation succeeded in {response_time:.2f}s "
                f"(Health: {self.health_monitor.get_health_report()['health_score']:.1f}%)"
            )
            
            with self.lock:
                self.global_stats.pages_loaded += 1
            
            return True
            
        except Exception as e:
            response_time = time.time() - start_time
            error_str = str(e).lower()
            
            # تحديد نوع الخطأ - NEW
            error_type = "other"
            if "timeout" in error_str:
                error_type = "timeout"
            elif "connection" in error_str or "network" in error_str:
                error_type = "connection"
            
            # تسجيل الفشل - NEW
            self.health_monitor.record_attempt(success=False, error_type=error_type)
            
            # الحصول على تقرير الصحة الحالي - NEW
            health = self.health_monitor.get_health_report()
            
            logger.warning(
                f"✗ [W{worker_id}][{location}] Navigation failed in {response_time:.2f}s: "
                f"{error_type.upper()} - Health: {health['health_score']:.1f}% "
                f"(Circuit: {health['circuit_state']})"
            )
            
            with self.lock:
                self.global_stats.navigation_errors += 1
            
            return False
    
    # ==================== CONFIGURATION - ORIGINAL PRESERVED ====================
    
    def _validate_config(self):
        """Validate required configuration - ORIGINAL"""
        required = [
            'TARGET_URL', 'LAST_NAME', 'FIRST_NAME', 
            'EMAIL', 'PASSPORT', 'PHONE'
        ]
        
        missing = [field for field in required if not getattr(Config, field, None)]
        
        if missing:
            raise ValueError(f"[ERR] Missing configuration: {', '.join(missing)}")
        
        logger.info("[OK] Configuration validated")
    
    def _prepare_base_url(self, url: str) -> str:
        """Prepare base URL with locale - ORIGINAL"""
        if "request_locale" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}request_locale=en"
        return url
    
    def _load_proxies(self) -> List[Optional[str]]:
        """Load proxies from config or file - ORIGINAL"""
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
    
    # ==================== TIME MANAGEMENT - ORIGINAL PRESERVED ====================
    
    def get_current_time_aden(self) -> datetime.datetime:
        """Get current time in Aden timezone with NTP correction - ORIGINAL"""
        corrected_utc = self.ntp_sync.get_corrected_time()
        aden_time = corrected_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        return aden_time
    
    def is_pre_attack(self) -> bool:
        """Check if in pre-attack window (1:59:30 - 1:59:59 Aden time) - ORIGINAL"""
        now = self.get_current_time_aden()
        return (now.hour == 1 and 
                now.minute == Config.PRE_ATTACK_MINUTE and 
                now.second >= Config.PRE_ATTACK_SECOND)
    
    def is_attack_time(self) -> bool:
        """Check if in attack window (2:00:00 - 2:02:00 Aden time) - ORIGINAL"""
        now = self.get_current_time_aden()
        return now.hour == Config.ATTACK_HOUR and now.minute < Config.ATTACK_WINDOW_MINUTES
    
    def get_sleep_interval(self) -> float:
        """Calculate dynamic sleep interval based on current mode - ORIGINAL"""
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
        """Get current operational mode - ORIGINAL"""
        if self.is_attack_time():
            return "ATTACK"
        elif self.is_pre_attack():
            return "PRE_ATTACK"
        else:
            now = self.get_current_time_aden()
            if now.hour == 1 and now.minute >= 45:
                return "WARMUP"
            return "PATROL"
    
    # ==================== SESSION MANAGEMENT - ORIGINAL PRESERVED ====================
    
    def create_context(
        self, 
        browser: Browser, 
        worker_id: int,
        proxy: Optional[str] = None
    ) -> Tuple[BrowserContext, Page, SessionState]:
        """
        Create browser context with session state - ORIGINAL
        
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
    
    def validate_session_health(
        self, 
        page: Page, 
        session: SessionState, 
        location: str = "UNKNOWN"
    ) -> bool:
        """
        Validate session health with strict kill rules - ORIGINAL
        
        Returns:
            True if session is healthy, False if should be terminated
        """
        worker_id = session.worker_id
        
        # Rule 1: Session expired (age > 60s or idle > 15s)
        if session.is_expired():
            age = session.age()
            idle = session.idle_time()
            logger.critical(
                f"[EXP] [W{worker_id}][{location}] "
                f"Session EXPIRED - Age: {age:.1f}s, Idle: {idle:.1f}s"
            )
            self.incident_manager.create_incident(
                session.session_id, IncidentType.SESSION_EXPIRED,
                IncidentSeverity.CRITICAL,
                f"Session expired: age={age:.1f}s, idle={idle:.1f}s"
            )
            return False
        
        # Rule 2: Too many failures
        if session.should_terminate():
            logger.critical(
                f"💀 [W{worker_id}][{location}] "
                f"Session POISONED - Failures: {session.failures}"
            )
            self.incident_manager.create_incident(
                session.session_id, IncidentType.SESSION_POISONED,
                IncidentSeverity.CRITICAL,
                f"Session poisoned: failures={session.failures}"
            )
            return False
        
        # Rule 3: Double captcha detection (captcha appears twice in same flow)
        if session.captcha_solved:
            has_captcha, _ = self.solver.safe_captcha_check(page, location)
            if has_captcha:
                logger.critical(
                    f"💀 [W{worker_id}][{location}] "
                    f"DOUBLE CAPTCHA detected - Session INVALID"
                )
                session.health = SessionHealth.POISONED
                self.incident_manager.create_incident(
                    session.session_id, IncidentType.DOUBLE_CAPTCHA,
                    IncidentSeverity.CRITICAL,
                    "Double captcha in same flow - session poisoned"
                )
                return False
        
        # Rule 4: Silent rejection (form still visible after submit)
        if location == "POST_SUBMIT":
            try:
                if page.locator("input[name='lastname']").count() > 0:
                    logger.critical(
                        f"🔁 [W{worker_id}][{location}] "
                        f"Silent rejection - Form reappeared"
                    )
                    self.incident_manager.create_incident(
                        session.session_id, IncidentType.FORM_REJECTED,
                        IncidentSeverity.ERROR,
                        "Form reappeared after submit - silent rejection"
                    )
                    return False
            except:
                pass
        
        # Rule 5: Bounce detection (month captcha in form view)
        if location == "FORM":
            try:
                if page.locator("form#appointment_captcha_month").count() > 0:
                    logger.critical(
                        f"↩️ [W{worker_id}][{location}] "
                        f"Bounced to month captcha"
                    )
                    return False
            except:
                pass
        
        # Session is healthy
        session.touch()
        return True
    
    def soft_recovery(self, session: SessionState, reason: str):
        """
        Soft recovery without full context recreation
        From KingSniperV12 - ORIGINAL
        """
        logger.info(f"🔄 [W{session.worker_id}] Soft recovery: {reason}")
        
        # Reset counters
        session.consecutive_errors = 0
        session.failures = max(0, session.failures - 1)  # Forgive one failure
        
        # Update health
        if session.health == SessionHealth.DEGRADED:
            session.health = SessionHealth.WARNING
        elif session.health == SessionHealth.WARNING:
            session.health = SessionHealth.CLEAN
        
        session.touch()
        
        logger.info(f"✅ [W{session.worker_id}] Soft recovery completed")
    
    # ==================== NAVIGATION & FORM FILLING - ORIGINAL PRESERVED ====================
    
    def generate_month_urls(self) -> List[str]:
        """Generate priority month URLs - ORIGINAL"""
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
        then JavaScript fallback for reliability. - ORIGINAL
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
        """Find input ID by label text - ORIGINAL"""
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
        Uses Config.CATEGORY_IDS for accurate selection - ORIGINAL
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
    
    def fill_booking_form(self, page: Page, session: SessionState) -> bool:
        """
        Fill the booking form with user data
        Uses Surgeon's Injection for reliability - ORIGINAL
        """
        worker_id = session.worker_id
        logger.info(f"📝 [W{worker_id}] Filling booking form...")
        
        try:
            # 1. Standard Fields
            self.fast_inject(page, "input[name='lastname']", Config.LAST_NAME)
            self.fast_inject(page, "input[name='firstname']", Config.FIRST_NAME)
            self.fast_inject(page, "input[name='email']", Config.EMAIL)
            
            # Email repeat (try both variants)
            if not self.fast_inject(page, "input[name='emailrepeat']", Config.EMAIL):
                self.fast_inject(page, "input[name='emailRepeat']", Config.EMAIL)
            
            # 2. Dynamic Fields (Passport, Phone)
            phone_value = Config.PHONE.replace("+", "00").strip()
            
            # Try finding by label first
            passport_id = self.find_input_id_by_label(page, "Passport")
            if passport_id:
                self.fast_inject(page, f"#{passport_id}", Config.PASSPORT)
            else:
                self.fast_inject(page, "input[name='fields[0].content']", Config.PASSPORT)
            
            phone_id = self.find_input_id_by_label(page, "Telephone")
            if phone_id:
                self.fast_inject(page, f"#{phone_id}", phone_value)
            else:
                self.fast_inject(page, "input[name='fields[1].content']", phone_value)
            
            # 3. Category Selection
            self.select_category_by_value(page)
            
            with self.lock:
                self.global_stats.forms_filled += 1
            
            # Save debug evidence
            self.debug_manager.save_debug_html(page, "form_filled", worker_id)
            
            logger.info(f"✅ [W{worker_id}] Form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ [W{worker_id}] Form fill error: {e}")
            return False
    
    def submit_form(self, page: Page, session: SessionState) -> bool:
        """
        FINAL VERSION: Multi-Language Success Detection
        Detects real success pages in German and English, distinguishes from error pages
        ORIGINAL - FULLY PRESERVED
        """
        worker_id = session.worker_id
        logger.info(f"[W{worker_id}] === FINAL SUBMISSION (MULTI-LANGUAGE DETECTION) ===")
        
        max_attempts = 15
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"[W{worker_id}] [SUBMIT {attempt}/{max_attempts}]")
                
                # 1. حل الكابتشا
                success, code, _ = self.solver.solve_from_page(page, f"SUBMIT_{attempt}")
                
                if not success or not code:
                    logger.warning(f"[W{worker_id}] Captcha solve failed, refreshing...")
                    self.solver.reload_captcha(page)
                    time.sleep(1.5)
                    continue
                
                # 2. تعبئة الكابتشا
                captcha_input = page.locator("input[name='captchaText']").first
                captcha_input.click()
                captcha_input.fill("")
                captcha_input.type(code, delay=10)
                time.sleep(0.2)
                
                # 3. الإرسال مع انتظار التنقل
                try:
                    with page.expect_navigation(timeout=15000):
                        page.keyboard.press("Enter")
                    logger.info(f"[W{worker_id}] Navigation captured successfully")
                except Exception as nav_error:
                    logger.debug(f"[W{worker_id}] Navigation timeout: {nav_error}")
                    time.sleep(3)
                
                # ===============================================
                # 🔴 التحقق الدقيق من صفحة الخطأ أولاً
                # ===============================================
                content = page.content()
                content_lower = content.lower()
                
                # 🚨 اكتشاف صفحة الخطأ أولاً (جميع اللغات)
                error_patterns = [
                    # الإنجليزية
                    "an error occurred while processing your appointment",
                    "ref-id:",
                    "error occurred",
                    "processing error",
                    "your browser open for a very long time",
                    "changed the address manually",
                    
                    # الألمانية
                    "beginnen sie den buchungsvorgang neu",
                    "fehler bei der verarbeitung",
                    "es ist ein fehler aufgetreten",
                    
                    # مشتركة
                    "ref-id:",  # المؤشر القاطع للخطأ
                ]
                
                for error_pattern in error_patterns:
                    if error_pattern in content_lower:
                        logger.error(f"[W{worker_id}] ❌ ERROR PAGE DETECTED: '{error_pattern}'")
                        
                        # استخراج ref-id إن وجد
                        ref_id_match = re.search(r'ref-id:\s*([A-F0-9]+)', content, re.IGNORECASE)
                        if ref_id_match:
                            logger.error(f"[W{worker_id}] Ref-ID: {ref_id_match.group(1)}")
                        
                        # حفظ أدلة الخطأ
                        self.debug_manager.save_critical_screenshot(page, "ERROR_PAGE", worker_id)
                        self.debug_manager.save_debug_html(page, "ERROR_PAGE", worker_id)
                        
                        # إرسال تنبيه بالخطأ
                        try:
                            send_alert(
                                f"🚨 <b>ERROR PAGE DETECTED!</b>\n"
                                f"Session: {self.session_id}\n"
                                f"Error Type: {error_pattern}\n"
                                f"Ref-ID: {ref_id_match.group(1) if ref_id_match else 'N/A'}\n"
                                f"Worker: W{worker_id}"
                            )
                        except:
                            pass
                        
                        return False  # فشل حقيقي
                
                # ===============================================
                # 🎯 الاكتشاف الدقيق لصفحة النجاح (متعددة اللغات)
                # ===============================================
                
                # 🔍 مؤشرات النجاح بالألمانية
                german_success_patterns = [
                    ("Sie haben erfolgreich einen Termin", "GERMAN_MAIN_SUCCESS"),
                    ("Die Buchungsnummer lautet", "GERMAN_BOOKING_NUMBER"),
                    ("Sie erhalten in Kürze eine E-Mail", "GERMAN_EMAIL_CONFIRMATION"),
                    ("erfolgreich einen Termin", "GERMAN_SUCCESSFUL"),
                    ("gebucht", "GERMAN_BOOKED"),
                    ("Buchungsnummer", "GERMAN_BOOKING_NUM"),
                    ("Bestätigung", "GERMAN_CONFIRMATION"),
                ]
                
                # 🔍 مؤشرات النجاح بالإنجليزية
                english_success_patterns = [
                    ("You have successfully booked an appointment", "ENGLISH_MAIN_SUCCESS"),
                    ("The appointment number is", "ENGLISH_APPOINTMENT_NUMBER"),
                    ("You will shortly receive an email confirming your appointment", "ENGLISH_EMAIL_CONFIRMATION"),
                    ("successfully booked", "ENGLISH_SUCCESSFUL_BOOKED"),
                    ("appointment number", "ENGLISH_APPOINTMENT_NUM"),
                    ("confirming your appointment", "ENGLISH_CONFIRMING"),
                    ("email confirming", "ENGLISH_EMAIL_CONFIRM"),
                ]
                
                # 🔢 استخراج رقم الموعد/الحجز
                booking_number = None
                
                # البحث بالألمانية
                de_booking_match = re.search(
                    r'Die Buchungsnummer lautet\s+(\d+)', 
                    content
                )
                if de_booking_match:
                    booking_number = de_booking_match.group(1)
                    logger.critical(f"[W{worker_id}] ✅ GERMAN BOOKING NUMBER: {booking_number}")
                
                # البحث بالإنجليزية
                en_booking_match = re.search(
                    r'The appointment number is\s+(\d+)', 
                    content
                )
                if en_booking_match:
                    booking_number = en_booking_match.group(1)
                    logger.critical(f"[W{worker_id}] ✅ ENGLISH APPOINTMENT NUMBER: {booking_number}")
                
                # البحث العام
                if not booking_number:
                    general_match = re.search(
                        r'(?:appointment|booking)\s*(?:number|nummer)[:\s]+(\d+)', 
                        content, 
                        re.IGNORECASE
                    )
                    booking_number = general_match.group(1) if general_match else None
                
                # 📊 تقييم مؤشرات النجاح
                success_score = 0
                success_details = []
                detected_language = "UNKNOWN"
                
                # التحقق من اللغة الألمانية
                german_score = 0
                for pattern, description in german_success_patterns:
                    if pattern in content:
                        german_score += 1
                        success_score += 1
                        success_details.append(description)
                        logger.info(f"[W{worker_id}] ✓ German: '{description}'")
                
                # التحقق من اللغة الإنجليزية
                english_score = 0
                for pattern, description in english_success_patterns:
                    if pattern in content:
                        english_score += 1
                        success_score += 1
                        success_details.append(description)
                        logger.info(f"[W{worker_id}] ✓ English: '{description}'")
                
                # تحديد اللغة
                if german_score > english_score:
                    detected_language = "GERMAN"
                elif english_score > german_score:
                    detected_language = "ENGLISH"
                else:
                    detected_language = "MIXED"
                
                logger.info(f"[W{worker_id}] 📚 Detected Language: {detected_language}")
                
                # 📧 استخراج البريد الإلكتروني
                email_matches = re.findall(
                    r'email\s*(?:address|anschrift)[:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', 
                    content, 
                    re.IGNORECASE
                )
                
                if not email_matches:
                    # بحث عام عن البريد
                    email_matches = re.findall(
                        r'[\w.]+@[\w.]+\.[a-zA-Z]{2,}', 
                        content
                    )
                
                if email_matches:
                    confirmation_email = email_matches[0]
                    logger.info(f"[W{worker_id}] 📧 Confirmation email: {confirmation_email}")
                    success_score += 2
                else:
                    confirmation_email = None
                
                # 📅 استخراج التاريخ والوقت
                datetime_match = re.search(
                    r'(?:on|am)\s+(\d{2}\.\d{2}\.\d{4})\s+(?:at|um)\s+(\d{2}:\d{2})', 
                    content, 
                    re.IGNORECASE
                )
                
                if datetime_match:
                    date = datetime_match.group(1)
                    time_str = datetime_match.group(2)
                    logger.info(f"[W{worker_id}] 📅 Appointment: {date} at {time_str}")
                    success_score += 1
                else:
                    date = time_str = None
                
                # ===============================================
                # ✅ شروط النجاح النهائية الصارمة
                # ===============================================
                
                # الشرط الأساسي: يجب أن يحتوي على جملة النجاح الرئيسية
                has_main_success = any([
                    "You have successfully booked an appointment" in content,
                    "Sie haben erfolgreich einen Termin" in content
                ])
                
                # الشرط الأساسي: يجب أن يحتوي على رقم الحجز/الموعد
                has_booking_number = booking_number is not None
                
                # الشرط الأساسي: يجب أن يحتوي على تأكيد البريد الإلكتروني
                has_email_confirmation = any([
                    "You will shortly receive an email" in content,
                    "Sie erhalten in Kürze eine E-Mail" in content
                ])
                
                # الشرط الأساسي: لا يجب أن يحتوي على كلمات خطأ
                has_no_errors = not any(error in content_lower for error in ["error", "fehler", "ref-id:"])
                
                # الشرط الإضافي: يجب أن تكون النقاط كافية
                has_sufficient_score = success_score >= 6
                
                # ===============================================
                # 🏆 التحقق النهائي والحكم
                # ===============================================
                
                success_conditions = {
                    "has_main_success": has_main_success,
                    "has_booking_number": has_booking_number,
                    "has_email_confirmation": has_email_confirmation,
                    "has_no_errors": has_no_errors,
                    "has_sufficient_score": has_sufficient_score,
                }
                
                logger.info(f"[W{worker_id}] Success Conditions: {success_conditions}")
                logger.info(f"[W{worker_id}] Success Score: {success_score}/12")
                logger.info(f"[W{worker_id}] Success Details: {success_details}")
                logger.info(f"[W{worker_id}] Language: {detected_language}")
                
                # الحكم النهائي
                if (has_main_success and has_booking_number and has_email_confirmation and 
                    has_no_errors and has_sufficient_score):
                    
                    logger.critical(f"[W{worker_id}] 🎉🎉🎉 REAL SUCCESS CONFIRMED IN {detected_language}! 🎉🎉🎉")
                    logger.critical(f"[W{worker_id}] 📋 {'Booking' if detected_language == 'GERMAN' else 'Appointment'} Number: {booking_number}")
                    logger.critical(f"[W{worker_id}] 📧 Confirmation email: {confirmation_email if confirmation_email else 'Will be sent'}")
                    if date and time_str:
                        logger.critical(f"[W{worker_id}] 📅 Appointment: {date} at {time_str}")
                    
                    # حفظ أدلة النجاح
                    self.debug_manager.save_critical_screenshot(page, f"SUCCESS_{detected_language}", worker_id)
                    self.debug_manager.save_debug_html(page, f"SUCCESS_{detected_language}", worker_id)
                    
                    # إرسال تنبيه النجاح مع التفاصيل
                    try:
                        success_message = (
                            f"✅ APPOINTMENT BOOKED SUCCESSFULLY!\n"
                            f"🌐 Language: {detected_language}\n"
                            f"📋 {'Booking' if detected_language == 'GERMAN' else 'Appointment'} Number: {booking_number}\n"
                        )
                        
                        if date and time_str:
                            success_message += f"📅 Date: {date}\n⏰ Time: {time_str}\n"
                        
                        if confirmation_email:
                            success_message += f"📧 Confirmation sent to: {confirmation_email}\n"
                        else:
                            success_message += f"📧 Confirmation email will be sent\n"
                        
                        success_message += f"🎯 Success Score: {success_score}/12"
                        
                        send_success_notification(self.session_id, worker_id, success_message)
                    except Exception as e:
                        logger.error(f"[W{worker_id}] Notification error: {e}")
                    
                    with self.lock:
                        self.global_stats.success = True
                    
                    self.stop_event.set()
                    return True
                
                # ===============================================
                # 🔄 اكتشاف العودة للفورم
                # ===============================================
                if page.locator("input[name='lastname']").is_visible(timeout=1000):
                    logger.warning(f"[W{worker_id}] Bounced back to form (Attempt {attempt})")
                    
                    # تحديث الكابتشا
                    self.solver.reload_captcha(page)
                    
                    # إعادة تعبئة الفورم
                    if page.locator("input[name='lastname']").input_value() == "":
                        logger.info(f"[W{worker_id}] Re-filling form...")
                        self.fill_booking_form(page, session)
                    
                    time.sleep(1)
                    continue
                
                # اكتشاف إعادة التوجيه للتقويم
                if "appointment_showMonth" in page.url or "appointment_showDay" in page.url:
                    logger.warning(f"[W{worker_id}] [REDIRECT] Slot taken")
                    return False
                
                # اكتشاف أخطاء الكابتشا
                captcha_error = any(word in content_lower for word in ["incorrect", "wrong", "falsch", "ungültig"])
                if captcha_error:
                    logger.warning(f"[W{worker_id}] Captcha was wrong, refreshing...")
                    self.solver.reload_captcha(page)
                    time.sleep(1)
                    continue
                
                # إذا وصلنا هنا ولم نحدد النجاح، فهي صفحة غير معروفة
                logger.warning(f"[W{worker_id}] Unknown page type - Saving for analysis")
                self.debug_manager.save_debug_html(page, f"unknown_page_attempt_{attempt}", worker_id)
                self.debug_manager.save_critical_screenshot(page, f"unknown_page_attempt_{attempt}", worker_id)
                
                # تحليل إضافي للمحتوى
                content_preview = content[:500].replace('\n', ' ').replace('\r', ' ')
                logger.info(f"[W{worker_id}] Page content preview: {content_preview}")
                
            except Exception as e:
                logger.error(f"[W{worker_id}] Submit attempt {attempt} error: {e}")
                if attempt < max_attempts:
                    time.sleep(1)
                    continue
        
        logger.warning(f"[W{worker_id}] Max submit attempts ({max_attempts}) reached")
        return False
    
    # ==================== SCOUT BEHAVIOR - ORIGINAL PRESERVED ====================
    
    def _scout_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Scout behavior: Fast discovery, signals attackers
        Does NOT book - purely for finding slots
        ORIGINAL - FULLY PRESERVED
        """
        worker_id = session.worker_id
        
        try:
            # Get month URLs to scan
            month_urls = self.generate_month_urls()
            
            for url in month_urls:
                if self.stop_event.is_set():
                    return
                
                # ENHANCED: Use smart navigation instead of original goto
                success = self.smart_goto(page, url, "SCOUT_MONTH", worker_id)
                
                if not success:
                    # إذا فشل الاتصال، تخطي هذا الرابط
                    continue
                
                session.current_url = url
                session.touch()
                
                with self.lock:
                    self.global_stats.months_scanned += 1
                    self.global_stats.scans += 1
                        
                # Check session health
                if not self.validate_session_health(page, session, "SCOUT_MONTH"):
                    return
                
                # Handle captcha if present
                has_captcha, _ = self.solver.safe_captcha_check(page, "SCOUT_MONTH")
                if has_captcha:
                    success, code, captcha_status = self.solver.solve_from_page(page, "SCOUT_MONTH")
                    if success and code:
                        self.solver.submit_captcha(page, "enter")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except:
                            pass
                        
                        with self.lock:
                            self.global_stats.captchas_solved += 1
                        session.mark_captcha_solved()
                    else:
                        with self.lock:
                            self.global_stats.captchas_failed += 1
                        continue
                
                # Check for "no appointments" message
                content = page.content().lower()
                if "no appointments" in content or "keine termine" in content:
                    continue
                
                # Look for available days
                day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                
                if day_links:
                    num_days = len(day_links)
                    worker_logger.critical(f"🔥 SCOUT FOUND {num_days} DAYS!")
                    
                    with self.lock:
                        self.global_stats.days_found += num_days
                    
                    # Get the first day URL
                    first_href = day_links[0].get_attribute("href")
                    if first_href:
                        # Build full URL for attackers
                        base_domain = self.base_url.split("/extern")[0]
                        self.target_url = f"{base_domain}/{first_href}"
                        
                        # Signal attackers!
                        worker_logger.critical(f"🟢 SIGNALING ATTACKERS! URL: {self.target_url[:50]}...")
                        send_alert(
                            f"🟢 <b>SCOUT: SLOTS DETECTED!</b>\n"
                            f"📅 Days found: {num_days}\n"
                            f"⏰ Attackers engaging..."
                        )
                        
                        self.incident_manager.create_incident(
                            session.session_id, IncidentType.SLOT_DETECTED,
                            IncidentSeverity.INFO,
                            f"Found {num_days} available days"
                        )
                        
                        # Signal the event
                        self.slot_event.set()
                        
                        # Scout doesn't proceed to booking - let attackers handle it
                        return
                
        except Exception as e:
            worker_logger.error(f"Scout behavior error: {e}")
            session.increment_failure(str(e))
    
    # ==================== ATTACKER BEHAVIOR - ORIGINAL PRESERVED ====================
    
    def _attacker_behavior(self, page: Page, session: SessionState, worker_logger):
        """
        Attacker behavior: Wait for scout signal or scan independently
        Executes booking when slots are found
        ORIGINAL - FULLY PRESERVED (with smart_goto enhancement)
        """
        worker_id = session.worker_id
        
        try:
            # In attack mode, scan independently
            mode = self.get_mode()
            
            # If not attack mode and no signal, do light scanning
            if mode not in ["ATTACK", "PRE_ATTACK"] and not self.slot_event.is_set():
                # Light patrol - don't overwhelm server
                time.sleep(random.uniform(2, 5))
                
                # Check for scout signal
                if self.slot_event.wait(timeout=1.0):
                    worker_logger.info("📡 Received scout signal!")
            
            # If signal received and we have a target URL, go directly there
            if self.slot_event.is_set() and self.target_url:
                worker_logger.info(f"🎯 Attacking target: {self.target_url[:50]}...")
                
                # ENHANCED: Use smart navigation
                success = self.smart_goto(page, self.target_url, "ATTACK_TARGET", worker_id)
                if not success:
                    worker_logger.warning(f"Target navigation failed")
                    self.slot_event.clear()  # Clear and retry
                    return
                    
                session.touch()
            else:
                # Independent scanning
                month_urls = self.generate_month_urls()
                
                # Attackers scan fewer months to stay ready
                for url in month_urls[:3]:
                    if self.stop_event.is_set():
                        return
                    
                    # ENHANCED: Use smart navigation
                    success = self.smart_goto(page, url, f"ATK_MONTH_{month_urls[:3].index(url)}", worker_id)
                    if not success:
                        continue
                    
                    session.current_url = url
                    session.touch()
                    
                    with self.lock:
                        self.global_stats.scans += 1
                    
                    # Handle captcha
                    has_captcha, _ = self.solver.safe_captcha_check(page, f"ATK_MONTH")
                    if has_captcha:
                        success, code, captcha_status = self.solver.solve_from_page(page, f"ATK_MONTH")
                        if success and code:
                            self.solver.submit_captcha(page, "enter")
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=4000)
                            except:
                                pass
                            
                            with self.lock:
                                self.global_stats.captchas_solved += 1
                            session.mark_captcha_solved()
                        else:
                            continue
                    
                    # Look for days
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    if day_links:
                        break
                else:
                    # No days found in any month
                    return
            
            # Check session health
            if not self.validate_session_health(page, session, "ATK_DAY"):
                return
            
            # Click on first available day (or we're already there from target_url)
            day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
            if day_links:
                target_day = random.choice(day_links)
                href = target_day.get_attribute("href")
                
                worker_logger.info(f"📅 Clicking day: {href[:40] if href else 'N/A'}...")
                
                try:
                    target_day.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as e:
                    # Fallback: direct navigation
                    if href:
                        base_domain = self.base_url.split("/extern")[0]
                        # ENHANCED: Use smart navigation
                        self.smart_goto(page, f"{base_domain}/{href}", "ATK_DAY_NAV", worker_id)
                
                session.reset_for_new_flow()
            
            # Handle day captcha
            has_captcha, _ = self.solver.safe_captcha_check(page, "ATK_DAY")
            if has_captcha:
                success, code, captcha_status = self.solver.solve_from_page(page, "ATK_DAY")
                if success and code:
                    self.solver.submit_captcha(page, "enter")
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=4000)
                    except:
                        pass
                    session.mark_captcha_solved()
                else:
                    return
            
            # Look for time slots
            time_links = page.locator("a.arrow[href*='appointment_showForm']").all()
            
            if time_links:
                with self.lock:
                    self.global_stats.slots_found += len(time_links)
                
                worker_logger.critical(f"⏰ [W{worker_id}] {len(time_links)} TIME SLOTS FOUND!")
                
                # Click first time slot
                target_time = random.choice(time_links)
                href = target_time.get_attribute("href")
                
                try:
                    target_time.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as e:
                    if href:
                        base_domain = self.base_url.split("/extern")[0]
                        # ENHANCED: Use smart navigation
                        self.smart_goto(page, f"{base_domain}/{href}", "ATK_FORM_NAV", worker_id)
                
                session.reset_for_new_flow()
                
                # Handle form captcha
                has_captcha, _ = self.solver.safe_captcha_check(page, "ATK_FORM")
                if has_captcha:
                    success, code, captcha_status = self.solver.solve_from_page(page, "ATK_FORM")
                    if success and code:
                        self.solver.submit_captcha(page, "enter")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=4000)
                        except:
                            pass
                        session.mark_captcha_solved()
                    else:
                        return
                
                # Validate we're on the form
                if not self.validate_session_health(page, session, "FORM"):
                    return
                
                # Check if form is visible
                if page.locator("input[name='lastname']").count() == 0:
                    worker_logger.warning("Form not found after navigation")
                    return
                
                # FILL AND SUBMIT FORM!
                self.incident_manager.create_incident(
                    session.session_id, IncidentType.BOOKING_ATTEMPT,
                    IncidentSeverity.INFO,
                    "Attempting to book appointment"
                )
                
                if self.fill_booking_form(page, session):
                    if self.submit_form(page, session):
                        # SUCCESS!
                        return
                
        except Exception as e:
            worker_logger.error(f"Attacker behavior error: {e}")
            session.increment_failure(str(e))
    
    # ==================== SINGLE SESSION MODE - ENHANCED WITH RESILIENCE ====================
    
    def _run_single_session(self, browser: Browser, worker_id: int):
        """
        Single session mode: Full scan + book flow
        ORIGINAL PRESERVED WITH ENHANCEMENTS
        
        CORRECT FLOW (based on reverse engineering HTML):
        
        1. MONTH PAGE (appointment_showMonth.do)
           - MAY have CAPTCHA (session gate) → Solve if present
           - After captcha: shows available days
           - Look for "Appointments are available" links
           
        2. DAY PAGE (appointment_showDay.do)
           - NO CAPTCHA
           - Shows available time slots
           - Look for "Book this appointment" links
           
        3. FORM PAGE (appointment_showForm.do)
           - ALWAYS has CAPTCHA (confirmation)
           - Fill form fields
           - Solve captcha
           - Submit form
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.Single")
        worker_logger.info("[START] Single session mode started - Enhanced with Resilience")
        
        # Proxy configuration
        proxy = None  # Disabled for testing
        
        # Create context and page
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        
        worker_logger.info(f"[INIT] Session {session.session_id} created")
        if proxy:
            worker_logger.info(f"[PROXY] Using: {proxy[:30]}...")
        else:
            worker_logger.info("[DIRECT] Running without proxy")
        
        try:
            max_cycles = 100
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    break
                
                mode = self.get_mode()
                
                # تقرير الصحة كل 5 دورات - NEW
                if cycle % 5 == 0:
                    health = self.health_monitor.get_health_report()
                    worker_logger.info(
                        f"[CYCLE {cycle+1}] Mode: {mode} | "
                        f"Health: {health['health_score']:.1f}% | "
                        f"Circuit: {health['circuit_state']}"
                    )
                else:
                    worker_logger.info(f"[CYCLE {cycle+1}] Mode: {mode}")
                
                # Get month URLs to scan
                month_urls = self.generate_month_urls()
                worker_logger.info(f"[DEBUG] Generated {len(month_urls)} URLs to scan")
                
                for i, url in enumerate(month_urls):
                    worker_logger.info(f"[DEBUG] Processing URL {i+1}/{len(month_urls)}")
                    if self.stop_event.is_set():
                        worker_logger.info("[DEBUG] Stop event set - breaking loop")
                        break
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 1: MONTH PAGE - MAY HAVE CAPTCHA (Session Gate)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # ENHANCED: Use smart_goto instead of direct goto
                    success = self.smart_goto(page, url, f"MONTH_{i+1}", worker_id)
                    
                    if not success:
                        # فشل الاتصال - تخطي هذا الرابط
                        health = self.health_monitor.get_health_report()
                        
                        # إذا كانت الصحة حرجة، توقف مؤقتاً - NEW
                        if health['health_score'] < 20:
                            worker_logger.critical(
                                f"🚨 CRITICAL HEALTH ({health['health_score']:.1f}%) - "
                                f"Pausing for {health.get('retry_delay', 60):.1f}s"
                            )
                            time.sleep(self.health_monitor.get_retry_delay())
                        
                        continue  # جرب الرابط التالي
                    
                    session.current_url = url
                    session.touch()
                    self.global_stats.months_scanned += 1
                    worker_logger.info(f"[MONTH] Loaded: {url.split('/')[-1][:60]}")
                    
                    # Check session health
                    if not self.validate_session_health(page, session, "MONTH"):
                        worker_logger.warning("[HEALTH] Session invalid, recreating...")
                        try:
                            context.close()
                        except:
                            pass
                        context, page, session = self.create_context(browser, worker_id, proxy)
                        break
                    
                    # Save debug HTML
                    self.debug_manager.save_debug_html(page, "month_scan", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # CHECK FOR CAPTCHA ON MONTH PAGE (Session Gate)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Wait for page stability
                    page.wait_for_timeout(2000)
                    
                    has_captcha, check_ok = self.solver.safe_captcha_check(page, "MONTH")
                    
                    # FALLBACK: Check for Month Captcha Form ID directly
                    if not has_captcha:
                        worker_logger.warning("[DEBUG] Standard captcha check failed. Trying strict fallback...")
                        try:
                            # Check if form exists at all
                            form_loc = page.locator("#appointment_captcha_month")
                            if form_loc.count() > 0:
                                visible = form_loc.is_visible()
                                worker_logger.warning(f"[DEBUG] Fallback: Form found. Visible={visible}")
                                if visible:
                                    has_captcha = True
                                else:
                                    # Force true if exists but hidden (weird, but safe)
                                    worker_logger.warning("[DEBUG] Form exists but reported hidden - forcing check")
                                    has_captcha = True
                            else:
                                worker_logger.warning("[DEBUG] Fallback: Form ID not found in DOM")
                        except Exception as e:
                            worker_logger.warning(f"[DEBUG] Fallback error: {e}")
                    
                    if has_captcha:
                        worker_logger.info("[MONTH] Captcha detected - solving session gate...")
                        self.debug_manager.save_critical_screenshot(page, "month_captcha_before", worker_id)
                        
                        # Calculate session age
                        session_age = int(time.time() - session.created_at)
                        
                        # Solve the captcha (try OCR first, then manual Telegram)
                        success, code, captcha_status = self.solver.solve_from_page(
                            page, 
                            "MONTH",
                            session_age=session_age,
                            attempt=1,
                            max_attempts=1  # Only 1 try for month captcha
                        )
                        
                        # Forensic logging for captcha
                        self.debug_manager.save_forensic_state(
                            page, 
                            "month_captcha_attempt", 
                            worker_id,
                            extra_data={"code": code, "status": captcha_status, "success": success}
                        )
                        
                        # Check for BLACK CAPTCHA - session is poisoned!
                        if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                            worker_logger.critical(f"[BLACK CAPTCHA] Session poisoned! Status: {captcha_status}")
                            self.debug_manager.save_critical_screenshot(page, "black_captcha", worker_id)
                            try:
                                context.close()
                            except:
                                pass
                            context, page, session = self.create_context(browser, worker_id, proxy)
                            worker_logger.info("[RECOVERY] Session recreated after black captcha")
                            break  # Exit month loop, start fresh
                        
                        # Check for AGING session warning
                        if captcha_status in ["AGING_7", "AGING_8"]:
                            worker_logger.warning(f"[SESSION AGING] {captcha_status} - Consider session refresh soon")
                        
                        if success and code:
                            worker_logger.info(f"[CAPTCHA] Submitting: '{code}' (Status: {captcha_status})")
                            
                            # Submit captcha (auto tries click then enter)
                            self.solver.submit_captcha(page, "auto")
                            
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=10000)
                            except:
                                pass
                            
                            # Wait for page to stabilize
                            time.sleep(1)
                            
                            # Verify captcha was solved
                            solved, page_type = self.solver.verify_captcha_solved(page, "MONTH_VERIFY")
                            
                            self.debug_manager.save_critical_screenshot(page, f"month_captcha_after_{page_type}", worker_id)
                            
                            if not solved:
                                # Captcha failed - still on captcha page
                                self.global_stats.captchas_failed += 1
                                worker_logger.warning(f"[CAPTCHA] WRONG! '{code}' - Page: {page_type}")
                                continue  # Try next month
                            else:
                                # SUCCESS! Session gate passed
                                self.global_stats.captchas_solved += 1
                                session.mark_captcha_solved()
                                worker_logger.info(f"[CAPTCHA] SUCCESS! '{code}' - Now on: {page_type}")
                        else:
                            # Captcha solve failed
                            self.global_stats.captchas_failed += 1
                            worker_logger.warning(f"[CAPTCHA] Solve failed: {captcha_status}")
                            self.debug_manager.save_critical_screenshot(page, f"captcha_failed_{captcha_status}", worker_id)
                            continue  # Try next month
                    
                    # ═══════════════════════════════════════════════════════════════
                    # NOW WE'RE ON MONTH PAGE WITH AVAILABLE DAYS (No captcha)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Save debug HTML after captcha
                    self.debug_manager.save_debug_html(page, "after_captcha", worker_id)
                    
                    # Check for "no appointments" message
                    content = page.content().lower()
                    if "no appointments" in content or "keine termine" in content:
                        worker_logger.info("[MONTH] No appointments in this month")
                        continue
                    
                    # Look for available days
                    day_links = page.locator("a.arrow[href*='appointment_showDay']").all()
                    
                    if not day_links:
                        worker_logger.debug("[MONTH] No available days found")
                        continue
                    
                    # FOUND AVAILABLE DAYS!
                    num_days = len(day_links)
                    worker_logger.critical(f"[FOUND] {num_days} DAYS AVAILABLE!")
                    self.global_stats.days_found += num_days
                    
                    # Save evidence
                    self.debug_manager.save_debug_html(page, "days_found", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "days_found", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 2: DAY PAGE - NO CAPTCHA
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Click first available day
                    first_href = day_links[0].get_attribute("href")
                    if not first_href:
                        continue
                    
                    base_domain = self.base_url.split("/extern")[0]
                    day_url = f"{base_domain}/{first_href}" if not first_href.startswith("http") else first_href
                    
                    worker_logger.info(f"[DAY] Navigating to day page...")
                    
                    # ENHANCED: Use smart navigation
                    success = self.smart_goto(page, day_url, "DAY_PAGE", worker_id)
                    if not success:
                        worker_logger.error("[DAY] Navigation failed")
                        continue
                    
                    session.touch()
                    
                    # Save debug HTML
                    self.debug_manager.save_debug_html(page, "day_page", worker_id)
                    
                    # Look for time slots
                    slot_links = page.locator("a.arrow[href*='appointment_showForm']").all()
                    
                    if not slot_links:
                        worker_logger.info("[DAY] No available time slots")
                        continue
                    
                    # FOUND AVAILABLE SLOTS!
                    num_slots = len(slot_links)
                    worker_logger.critical(f"[SLOTS] {num_slots} TIME SLOTS FOUND!")
                    self.global_stats.slots_found += num_slots
                    
                    # Save evidence
                    self.debug_manager.save_debug_html(page, "slots_found", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "slots_found", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 3: FORM PAGE - ALWAYS HAS CAPTCHA
                    # ═══════════════════════════════════════════════════════════════
                    
                    # Click first available slot
                    slot_href = slot_links[0].get_attribute("href")
                    if not slot_href:
                        continue
                    
                    slot_url = f"{base_domain}/{slot_href}" if not slot_href.startswith("http") else slot_href
                    
                    worker_logger.info(f"[FORM] Navigating to booking form...")
                    
                    # ENHANCED: Use smart navigation
                    success = self.smart_goto(page, slot_url, "FORM_PAGE", worker_id)
                    if not success:
                        worker_logger.error("[FORM] Navigation failed")
                        continue
                    
                    session.touch()
                    
                    # Save form page evidence
                    self.debug_manager.save_debug_html(page, "form_page", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "form_page", worker_id)
                    
                    # ═══════════════════════════════════════════════════════════════
                    # CRITICAL FIX: FILL FORM FIRST (FAST), THEN CAPTCHA + SUBMIT
                    # This prevents DOUBLE_CAPTCHA by minimizing time between captcha & submit
                    # ═══════════════════════════════════════════════════════════════
                    
                    # STEP 1: Fill form fields FIRST (fast - uses JavaScript injection)
                    worker_logger.info("[FORM] Step 1: Filling form fields FIRST...")
                    if not self.fill_booking_form(page, session):
                        worker_logger.warning("[FORM] Form fill failed")
                        self.debug_manager.save_debug_html(page, "fill_failed", worker_id)
                        continue
                    
                    worker_logger.info("[FORM] Step 1 DONE - Form filled (fast)")
                    
                    # Forensic logging for filled form
                    self.debug_manager.save_forensic_state(page, "form_filled", worker_id)
                    
                    # STEP 2: Now solve captcha (if present) 
                    has_captcha, _ = self.solver.safe_captcha_check(page, "FORM")
                    
                    if has_captcha:
                        worker_logger.info("[FORM] Step 2: Solving captcha...")
                        
                        # Calculate session age
                        session_age = int(time.time() - session.created_at)
                        
                        # Solve with retry logic - reload button if needed
                        success, code, captcha_status = self.solver.solve_form_captcha_with_retry(
                            page, 
                            "FORM_SUBMIT",
                            max_attempts=5,
                            session_age=session_age
                        )
                        
                        if captcha_status in ["BLACK_IMAGE", "BLACK_DETECTED"]:
                            worker_logger.critical("[BLACK CAPTCHA] Session poisoned!")
                            try:
                                context.close()
                            except:
                                pass
                            context, page, session = self.create_context(browser, worker_id, proxy)
                            break
                        
                        if not success or not code:
                            worker_logger.warning(f"[CAPTCHA] Form captcha failed: {captcha_status}")
                            self.global_stats.captchas_failed += 1
                            continue
                        
                        worker_logger.info(f"[FORM] Step 2 DONE - Captcha solved: '{code}'")
                        self.global_stats.captchas_solved += 1
                        session.mark_captcha_solved()
                    
                    # STEP 3: Submit IMMEDIATELY (no delay!)
                    worker_logger.info("[FORM] Step 3: SUBMITTING NOW!")
                    
                    # Save evidence before submit
                    self.debug_manager.save_debug_html(page, "form_ready", worker_id)
                    self.debug_manager.save_critical_screenshot(page, "form_ready", worker_id)
                    
                    # Submit form immediately
                    if self.submit_form(page, session):
                        worker_logger.critical("=" * 60)
                        worker_logger.critical("[SUCCESS] APPOINTMENT BOOKED!")
                        worker_logger.critical("=" * 60)
                        
                        # Save success evidence
                        self.debug_manager.save_debug_html(page, "success", worker_id)
                        self.debug_manager.save_critical_screenshot(page, "success", worker_id)
                        
                        # Mark success
                        with self.lock:
                            self.global_stats.success = True
                        self.stop_event.set()
                        
                        return  # EXIT: Success!
                    else:
                        worker_logger.warning("[SUBMIT] Form submission failed")
                        self.debug_manager.save_debug_html(page, "submit_failed", worker_id)
                
                # Sleep based on mode - ENHANCED with health consideration
                sleep_time = self.get_sleep_interval()
                
                # تعديل وقت النوم بناءً على صحة النظام - NEW
                health_score = self.health_monitor.get_health_report()['health_score']
                if health_score < 50:
                    sleep_time *= 2  # مضاعفة وقت النوم إذا كانت الصحة ضعيفة
                    worker_logger.info(f"[SLEEP] Extended sleep to {sleep_time:.1f}s due to poor health")
                
                worker_logger.info(f"[SLEEP] {sleep_time:.1f}s")
                time.sleep(sleep_time)
                
                # Recreate session if too old - ORIGINAL
                if session.age() > Config.SESSION_MAX_AGE:
                    worker_logger.info("[REBIRTH] Session too old, recreating...")
                    try:
                        context.close()
                    except:
                        pass
                    context, page, session = self.create_context(browser, worker_id, proxy)
                    self.global_stats.rebirths += 1
            
            worker_logger.info("[END] Max cycles reached")
            
        except Exception as e:
            worker_logger.error(f"[FATAL] Single session error: {e}", exc_info=True)
        
        finally:
            try:
                context.close()
            except:
                pass
            
            # تقرير الصحة النهائي - NEW
            final_health = self.health_monitor.get_health_report()
            worker_logger.info(
                f"[END] Final health: {final_health['health_score']:.1f}% | "
                f"Success Rate: {final_health['success_rate']} | "
                f"Total Attempts: {final_health['total_attempts']}"
            )
            
            worker_logger.info("[END] Session closed")
    
    # ==================== MAIN ENTRY POINT - ENHANCED ====================
    
    def run(self) -> bool:
        """
        Main execution entry point - ORIGINAL PRESERVED WITH ENHANCEMENTS
        
        Returns:
            True if booking successful, False otherwise
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER {self.VERSION}] - STARTING EXECUTION")
        logger.info("[MODE] Single Session with Enhanced Resilience")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        logger.info(f"[CURRENT TIME] Aden: {self.get_current_time_aden().strftime('%H:%M:%S')}")
        logger.info("=" * 70)
        
        # تقرير الصحة الأولي - NEW
        initial_health = self.health_monitor.get_health_report()
        logger.info(f"[HEALTH] Initial health score: {initial_health['health_score']:.1f}%")
        
        try:
            # Send startup notification - ENHANCED with health info
            send_alert(
                f"[Elite Sniper {self.VERSION} Started - Enhanced]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Session with Network Resilience\n"
                f"Attack: {Config.ATTACK_HOUR}:00 AM Aden\n"
                f"NTP Offset: {self.ntp_sync.offset:.4f}s\n"
                f"Initial Health: {initial_health['health_score']:.1f}%"
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
                # Architecture preserved for 3 sessions later
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
                
                # Save final stats - ENHANCED with health data
                final_stats = self.global_stats.to_dict()
                final_health = self.health_monitor.get_health_report()
                
                # دمج إحصائيات الصحة مع الإحصائيات العامة - NEW
                final_stats['network_health'] = final_health
                
                self.debug_manager.save_stats(final_stats, "final_stats_enhanced.json")
                self.debug_manager.create_session_report(final_stats)
                
                if self.global_stats.success:
                    self._handle_success_enhanced(final_health)
                    return True
                else:
                    self._handle_completion_enhanced(final_health)
                    return False
                
        except KeyboardInterrupt:
            logger.info("\n[STOP] Manual stop requested")
            final_health = self.health_monitor.get_health_report()
            self.stop_event.set()
            self.ntp_sync.stop_background_sync()
            
            send_alert(
                f"⏸️ Elite Sniper stopped manually\n"
                f"Final Health: {final_health['health_score']:.1f}%\n"
                f"Success Rate: {final_health['success_rate']}"
            )
            return False
            
        except Exception as e:
            logger.error(f"💀 Critical error: {e}", exc_info=True)
            
            final_health = self.health_monitor.get_health_report()
            send_alert(
                f"🚨 Critical error: {str(e)[:200]}\n"
                f"Health at failure: {final_health['health_score']:.1f}%"
            )
            return False
    
    def _handle_success_enhanced(self, health_report: Dict):
        """Handle successful booking - ENHANCED"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] MISSION ACCOMPLISHED WITH ENHANCED RESILIENCE!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"🎉 ELITE SNIPER {self.VERSION} - SUCCESS!\n"
            f"[+] Appointment booked successfully with enhanced resilience!\n"
            f"Session: {self.session_id}\n"
            f"Runtime: {runtime:.0f}s\n"
            f"Final Health: {health_report['health_score']:.1f}%\n"
            f"Success Rate: {health_report['success_rate']}\n"
            f"Stats: {self.global_stats.get_summary()}"
        )
    
    def _handle_completion_enhanced(self, health_report: Dict):
        """Handle completion without success - ENHANCED"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Session completed - Enhanced Analysis")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        # تحليل أسباب الفشل - NEW
        failure_analysis = self._analyze_failures(health_report)
        
        logger.info(f"[TIME] Runtime: {runtime:.0f}s")
        logger.info(f"[HEALTH] Final health score: {health_report['health_score']:.1f}%")
        logger.info(f"[ANALYSIS] {failure_analysis}")
        logger.info(f"[STATS] Final stats: {self.global_stats.get_summary()}")
        
        # إرسال تحليل مفصل - NEW
        try:
            send_alert(
                f"📊 Elite Sniper Session Completed - Enhanced Report\n"
                f"Session: {self.session_id}\n"
                f"Runtime: {runtime:.0f}s\n"
                f"Final Health: {health_report['health_score']:.1f}%\n"
                f"Success Rate: {health_report['success_rate']}\n"
                f"Circuit State: {health_report['circuit_state']}\n"
                f"Total Attempts: {health_report['total_attempts']}\n"
                f"Failure Analysis: {failure_analysis}"
            )
        except:
            pass
    
    def _analyze_failures(self, health_report: Dict) -> str:
        """تحليل أسباب الفشل - NEW METHOD"""
        stats = health_report.get('stats', {})
        total_failures = stats.get('timeouts', 0) + stats.get('connection_errors', 0) + stats.get('other_errors', 0)
        
        if total_failures == 0:
            return "No network failures detected"
        
        analysis_parts = []
        
        if stats.get('timeouts', 0) > 0:
            timeout_percent = (stats['timeouts'] / total_failures) * 100
            analysis_parts.append(f"Timeouts: {stats['timeouts']} ({timeout_percent:.1f}%)")
        
        if stats.get('connection_errors', 0) > 0:
            conn_percent = (stats['connection_errors'] / total_failures) * 100
            analysis_parts.append(f"Connection errors: {stats['connection_errors']} ({conn_percent:.1f}%)")
        
        if stats.get('other_errors', 0) > 0:
            other_percent = (stats['other_errors'] / total_failures) * 100
            analysis_parts.append(f"Other errors: {stats['other_errors']} ({other_percent:.1f}%)")
        
        # توصيات بناءً على النمط
        if stats.get('timeouts', 0) > stats.get('connection_errors', 0) * 2:
            analysis_parts.append("RECOMMENDATION: Increase timeout settings or check server load")
        elif stats.get('connection_errors', 0) > stats.get('timeouts', 0) * 2:
            analysis_parts.append("RECOMMENDATION: Check network connectivity or DNS settings")
        
        return " | ".join(analysis_parts)


# Entry point with fallback - ENHANCED
if __name__ == "__main__":
    sniper = EliteSniperV2()
    success = sniper.run()
    sys.exit(0 if success else 1)