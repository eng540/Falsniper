"""
Elite Sniper v2.1 - Enhanced with Network Resilience
WITH SMART RETRY, HEALTH MONITORING, AND CIRCUIT BREAKER

Critical Fixes:
1. Network failure detection and recovery
2. Smart retry with exponential backoff
3. Real-time health monitoring
4. Circuit breaker pattern for critical failures

Version: 2.1.0 RESILIENT
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

# ==================== NEW RESILIENCE CLASSES ====================

class NetworkHealthMonitor:
    """
    مراقب صحة الشبكة مع Circuit Breaker pattern
    يحل مشكلة الفشل المتكرر في الاتصال كما ظهر في السجلات
    """
    
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
            
            return self._should_proceed()
    
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
    
    def _should_proceed(self) -> bool:
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
    
    def reset(self):
        """إعادة تعيين المراقب"""
        with self.lock:
            self.failures = 0
            self.consecutive_failures = 0
            self.circuit_state = "CLOSED"
            self.circuit_opened_at = None
            logger.info("🔄 Network monitor reset")


class SmartNavigationManager:
    """
    مدير تنقل ذكي مع مهلات متغيرة واستراتيجيات احتياطية
    """
    
    def __init__(self):
        self.base_timeout = 15  # مهلة أساسية أقل من 30 ثانية
        self.max_timeout = 60   # أقصى مهلة في الحالات القصوى
        self.current_timeout = self.base_timeout
        
        # استراتيجيات التنقل البديلة
        self.navigation_strategies = [
            self._strategy_direct,      # طريقة مباشرة
            self._strategy_with_retry,  # مع إعادة محاولة
            self._strategy_with_delay,  # مع تأخير
            self._strategy_minimal      # الحد الأدنى
        ]
        
        self.strategy_index = 0
    
    async def smart_navigate(self, page: Page, url: str, location: str = "UNKNOWN") -> bool:
        """
        تنقل ذكي مع استراتيجيات متعددة للتعامل مع فشل الشبكة
        """
        strategy = self.navigation_strategies[self.strategy_index]
        
        try:
            success = await strategy(page, url, location)
            
            if success:
                # نجاح - نرجع للاستراتيجية الأساسية
                self.strategy_index = 0
                self.current_timeout = self.base_timeout
                return True
            else:
                # فشل - نجرب استراتيجية أخرى
                self.strategy_index = (self.strategy_index + 1) % len(self.navigation_strategies)
                self.current_timeout = min(self.max_timeout, self.current_timeout * 1.5)
                logger.warning(f"🔄 Switching to navigation strategy {self.strategy_index}")
                return False
                
        except Exception as e:
            logger.error(f"Navigation error with strategy {self.strategy_index}: {e}")
            self.strategy_index = (self.strategy_index + 1) % len(self.navigation_strategies)
            return False
    
    async def _strategy_direct(self, page: Page, url: str, location: str) -> bool:
        """استراتيجية مباشرة - الطريقة العادية"""
        try:
            await page.goto(url, timeout=self.current_timeout*1000, wait_until="domcontentloaded")
            logger.debug(f"✓ Direct navigation succeeded to {location}")
            return True
        except Exception as e:
            logger.debug(f"Direct navigation failed: {e}")
            return False
    
    async def _strategy_with_retry(self, page: Page, url: str, location: str) -> bool:
        """استراتيجية مع إعادة محاولة سريعة"""
        for attempt in range(2):
            try:
                timeout = (self.current_timeout * 1000) // 2  # نصف المهلة
                await page.goto(url, timeout=timeout, wait_until="networkidle")
                logger.debug(f"✓ Retry navigation succeeded (attempt {attempt+1})")
                return True
            except:
                if attempt == 0:
                    time.sleep(1)  # انتظار قصير بين المحاولات
        return False
    
    async def _strategy_with_delay(self, page: Page, url: str, location: str) -> bool:
        """استراتيجية مع تأخير قبل المحاولة"""
        time.sleep(3)  # تأخير قبل المحاولة
        try:
            await page.goto(url, timeout=self.current_timeout*1000, wait_until="load")
            logger.debug(f"✓ Delayed navigation succeeded")
            return True
        except Exception as e:
            logger.debug(f"Delayed navigation failed: {e}")
            return False
    
    async def _strategy_minimal(self, page: Page, url: str, location: str) -> bool:
        """استراتيجية الحد الأدنى - مهلة قصيرة جداً فقط للتأكد من الفشل"""
        try:
            await page.goto(url, timeout=5000, wait_until="commit")  # 5 ثوان فقط
            logger.debug(f"✓ Minimal navigation succeeded")
            return True
        except:
            return False  # مقصود - نريد التأكد من الفشل


class PerformanceOptimizer:
    """
    محسن أداء مع تقليل الحمل على الخادم
    """
    
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


# ==================== MODIFIED EliteSniperV2 CLASS ====================

class EliteSniperV2Resilient:
    """
    Production-Grade Multi-Session Appointment Booking System
    RESILIENT VERSION WITH NETWORK FAILURE RECOVERY
    """
    
    VERSION = "2.1.0 RESILIENT"
    
    def __init__(self, run_mode: str = "AUTO"):
        """Initialize Elite Sniper v2.1 RESILIENT"""
        self.run_mode = run_mode
        
        logger.info("=" * 70)
        logger.info(f"[INIT] ELITE SNIPER {self.VERSION} - RESILIENT EDITION")
        logger.info(f"[MODE] Running Mode: {self.run_mode}")
        logger.info("[FEATURE] Network resilience: ✓ | Health monitoring: ✓ | Circuit breaker: ✓")
        logger.info("=" * 70)
        
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
        self.nav_manager = SmartNavigationManager()
        self.performance_opt = PerformanceOptimizer()
        
        # Existing components
        is_manual = (self.run_mode == "MANUAL")
        is_auto_full = (self.run_mode == "AUTO_FULL")
        self.solver = EnhancedCaptchaSolver(manual_only=is_manual)
        if is_auto_full:
            logger.info("[MODE] AUTO FULL ENABLED (No Manual Fallback)")
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
        
        logger.info(f"[ID] Session ID: {self.session_id}")
        logger.info(f"[URL] Base URL: {self.base_url[:60]}...")
        logger.info(f"[TZ] Timezone: {self.timezone}")
        logger.info(f"[NTP] NTP Offset: {self.ntp_sync.offset:.4f}s")
        logger.info(f"[DIR] Evidence Dir: {self.debug_manager.session_dir}")
        logger.info(f"[PROXY] Proxies: {len([p for p in self.proxies if p])} configured")
        logger.info(f"[RESILIENCE] Health monitor: ✓ | Smart navigation: ✓ | Rate control: ✓")
        logger.info(f"[OK] Initialization complete")
    
    # ==================== ENHANCED NAVIGATION METHOD ====================
    
    def smart_goto(self, page: Page, url: str, location: str = "UNKNOWN") -> bool:
        """
        تنقل ذكي مع مراقبة الصحة واستراتيجيات التعافي
        
        Returns:
            True إذا نجح الاتصال، False إذا فشل
        """
        worker_id = getattr(page, '_worker_id', 1)
        start_time = time.time()
        
        # التحقق من صحة الشبكة أولاً
        if not self.health_monitor.should_proceed():
            health = self.health_monitor.get_health_report()
            logger.warning(
                f"⏸️ [W{worker_id}][{location}] Circuit breaker {health['circuit_state']} - "
                f"Delaying request (Failures: {health['consecutive_failures']})"
            )
            
            # إرسال إنذار إذا كانت الحالة حرجة
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
            
            # انتظار ذكي قبل إعادة المحاولة
            delay = self.health_monitor.get_retry_delay()
            time.sleep(delay)
            return False
        
        # التحكم في معدل الطلبات
        if not self.performance_opt.should_make_request():
            logger.debug(f"⏳ [W{worker_id}][{location}] Rate limiting active")
            time.sleep(0.5)
        
        try:
            # المحاولة مع مهلة ذكية
            timeout = self.nav_manager.current_timeout * 1000
            
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            
            response_time = time.time() - start_time
            
            # تسجيل النجاح
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
            
            logger.warning(
                f"✗ [W{worker_id}][{location}] Navigation failed in {response_time:.2f}s: "
                f"{error_type.upper()} - Health: {health['health_score']:.1f}% "
                f"(Circuit: {health['circuit_state']})"
            )
            
            with self.lock:
                self.global_stats.navigation_errors += 1
            
            return False
    
    # ==================== ENHANCED SINGLE SESSION MODE ====================
    
    def _run_single_session_resilient(self, browser: Browser, worker_id: int):
        """
        وضع الجلسة المفردة مع المرونة المحسنة
        
        التحسينات:
        1. اكتشاف فشل الشبكة المبكر
        2. إستراتيجيات إعادة المحاولة الذكية
        3. مراقبة الصحة في الوقت الحقيقي
        4. تقارير تفصيلية للمستخدم
        """
        worker_logger = logging.getLogger(f"EliteSniperV2.Single.Resilient")
        worker_logger.info("[START] Resilient single session mode started")
        
        # Proxy configuration
        proxy = None  # Disabled for testing
        
        # Create context and page
        context, page, session = self.create_context(browser, worker_id, proxy)
        session.role = SessionRole.SCOUT
        page._worker_id = worker_id  # Mark page with worker ID
        
        worker_logger.info(f"[INIT] Session {session.session_id} created")
        
        # تقرير الصحة الأولي
        health_report = self.health_monitor.get_health_report()
        worker_logger.info(f"[HEALTH] Initial health: {health_report['health_score']:.1f}%")
        
        try:
            max_cycles = 100
            
            for cycle in range(max_cycles):
                if self.stop_event.is_set():
                    worker_logger.info("[STOP] Stop event received")
                    break
                
                mode = self.get_mode()
                
                # تقرير حالة النظام
                health = self.health_monitor.get_health_report()
                worker_logger.info(
                    f"[CYCLE {cycle+1}] Mode: {mode} | "
                    f"Health: {health['health_score']:.1f}% | "
                    f"Circuit: {health['circuit_state']} | "
                    f"Success Rate: {health['success_rate']}"
                )
                
                # إرسال تحديث الصحة كل 10 دورات
                if cycle % 10 == 0 and health['health_score'] < 70:
                    try:
                        send_alert(
                            f"📊 <b>SYSTEM HEALTH UPDATE</b>\n"
                            f"Cycle: {cycle+1}\n"
                            f"Health Score: {health['health_score']:.1f}%\n"
                            f"Circuit State: {health['circuit_state']}\n"
                            f"Success Rate: {health['success_rate']}\n"
                            f"Total Attempts: {health['total_attempts']}"
                        )
                    except:
                        pass
                
                # Get month URLs to scan
                month_urls = self.generate_month_urls()
                
                for i, url in enumerate(month_urls):
                    if self.stop_event.is_set():
                        break
                    
                    worker_logger.debug(f"[SCAN] Processing URL {i+1}/{len(month_urls)}")
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 1: SMART NAVIGATION WITH RESILIENCE
                    # ═══════════════════════════════════════════════════════════════
                    
                    success = self.smart_goto(page, url, f"MONTH_{i+1}")
                    
                    if not success:
                        # فشل الاتصال - تخطي هذا الرابط
                        health = self.health_monitor.get_health_report()
                        
                        # إذا كانت الصحة حرجة، توقف مؤقتاً
                        if health['health_score'] < 20:
                            worker_logger.critical(
                                f"🚨 CRITICAL HEALTH ({health['health_score']:.1f}%) - "
                                f"Pausing for {health.get('retry_delay', 60):.1f}s"
                            )
                            time.sleep(health.get('retry_delay', 60))
                        
                        continue  # جرب الرابط التالي
                    
                    # ═══════════════════════════════════════════════════════════════
                    # STEP 2: CONTINUE WITH NORMAL FLOW (إذا نجح الاتصال)
                    # ═══════════════════════════════════════════════════════════════
                    
                    # ... باقي الكود الأصلي ...
                    # (تم حذفه للإيجاز، ولكن يجب أن يتضمن التحقق من الكابتشا، البحث عن المواعيد، إلخ)
                    
                    # لمزيد من التفاصيل، راجع الكود الأصلي
                
                # تأخير ذكي بين الدورات
                sleep_time = self.get_sleep_interval()
                
                # تعديل وقت النوم بناءً على صحة النظام
                health_score = self.health_monitor.get_health_report()['health_score']
                if health_score < 50:
                    sleep_time *= 2  # مضاعفة وقت النوم إذا كانت الصحة ضعيفة
                    worker_logger.info(f"[SLEEP] Extended sleep to {sleep_time:.1f}s due to poor health")
                
                worker_logger.info(f"[SLEEP] {sleep_time:.1f}s")
                time.sleep(sleep_time)
            
            worker_logger.info("[END] Max cycles reached")
            
        except Exception as e:
            worker_logger.error(f"[FATAL] Single session error: {e}", exc_info=True)
            
            # تسجيل الفشل في مراقب الصحة
            self.health_monitor.record_attempt(success=False, error_type="fatal")
        
        finally:
            try:
                context.close()
            except:
                pass
            
            # تقرير الصحة النهائي
            final_health = self.health_monitor.get_health_report()
            worker_logger.info(
                f"[END] Final health: {final_health['health_score']:.1f}% | "
                f"Success Rate: {final_health['success_rate']} | "
                f"Total Attempts: {final_health['total_attempts']}"
            )
            
            worker_logger.info("[END] Session closed")
    
    # ==================== ENHANCED MAIN ENTRY POINT ====================
    
    def run_resilient(self) -> bool:
        """
        نقطة الدخول الرئيسية المحسنة مع المرونة
        
        Returns:
            True إذا نجح الحجز، False خلاف ذلك
        """
        logger.info("=" * 70)
        logger.info(f"[ELITE SNIPER {self.VERSION}] - RESILIENT EXECUTION")
        logger.info("[MODE] Single Session with Enhanced Resilience")
        logger.info(f"[ATTACK TIME] {Config.ATTACK_HOUR}:00 AM {Config.TIMEZONE}")
        
        # تقرير الصحة الأولي
        initial_health = self.health_monitor.get_health_report()
        logger.info(f"[HEALTH] Initial health score: {initial_health['health_score']:.1f}%")
        
        try:
            # إرسال إشعار البدء مع معلومات المرونة
            send_alert(
                f"[Elite Sniper {self.VERSION} Started - Resilient Mode]\n"
                f"Session: {self.session_id}\n"
                f"Mode: Single Session with Network Resilience\n"
                f"Health Monitoring: Enabled\n"
                f"Circuit Breaker: Enabled\n"
                f"Initial Health: {initial_health['health_score']:.1f}%"
            )
            
            with sync_playwright() as p:
                # تشغيل المتصفح
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=Config.BROWSER_ARGS,
                    timeout=60000
                )
                
                logger.info("[BROWSER] Launched successfully")
                
                # تشغيل الجلسة المقاومة للفشل
                worker_id = 1
                
                try:
                    self._run_single_session_resilient(browser, worker_id)
                except Exception as e:
                    logger.error(f"[SESSION ERROR] {e}")
                
                # إيقاف مزامنة NTP
                self.ntp_sync.stop_background_sync()
                
                # تنظيف
                browser.close()
                
                # حفظ الإحصائيات النهائية
                final_stats = self.global_stats.to_dict()
                final_health = self.health_monitor.get_health_report()
                
                # دمج إحصائيات الصحة مع الإحصائيات العامة
                final_stats['network_health'] = final_health
                
                self.debug_manager.save_stats(final_stats, "final_stats_resilient.json")
                self.debug_manager.create_session_report(final_stats)
                
                # تقرير نهائي
                success = self.global_stats.success
                health_score = final_health['health_score']
                
                if success:
                    self._handle_success_resilient(final_health)
                    return True
                else:
                    self._handle_completion_resilient(final_health)
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
    
    def _handle_success_resilient(self, health_report: Dict):
        """معالجة النجاح مع معلومات المرونة"""
        logger.info("\n" + "=" * 70)
        logger.info("[SUCCESS] MISSION ACCOMPLISHED WITH RESILIENCE!")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        send_alert(
            f"🎉 ELITE SNIPER {self.VERSION} - SUCCESS WITH RESILIENCE!\n"
            f"[+] Appointment booked successfully!\n"
            f"Session: {self.session_id}\n"
            f"Runtime: {runtime:.0f}s\n"
            f"Final Health: {health_report['health_score']:.1f}%\n"
            f"Success Rate: {health_report['success_rate']}\n"
            f"Total Attempts: {health_report['total_attempts']}"
        )
    
    def _handle_completion_resilient(self, health_report: Dict):
        """معالجة الإكمال بدون نجاح مع تحليلات"""
        logger.info("\n" + "=" * 70)
        logger.info("[STOP] Session completed - Resilience Analysis")
        logger.info("=" * 70)
        
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        
        # تحليل أسباب الفشل
        failure_analysis = self._analyze_failures(health_report)
        
        logger.info(f"[TIME] Runtime: {runtime:.0f}s")
        logger.info(f"[HEALTH] Final health score: {health_report['health_score']:.1f}%")
        logger.info(f"[ANALYSIS] {failure_analysis}")
        logger.info(f"[STATS] Final stats: {self.global_stats.get_summary()}")
        
        # إرسال تحليل مفصل
        try:
            send_alert(
                f"📊 Elite Sniper Session Completed - Resilience Report\n"
                f"Session: {self.session_id}\n"
                f"Runtime: {runtime:.0f}s\n"
                f"Final Health: {health_report['health_score']:.1f}%\n"
                f"Success Rate: {health_report['success_rate']}\n"
                f"Total Attempts: {health_report['total_attempts']}\n"
                f"Circuit State: {health_report['circuit_state']}\n"
                f"Failure Analysis: {failure_analysis}"
            )
        except:
            pass
    
    def _analyze_failures(self, health_report: Dict) -> str:
        """تحليل أسباب الفشل"""
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


# ==================== ENTRY POINT WITH FALLBACK ====================

if __name__ == "__main__":
    # محاولة الوضع المقاوم أولاً
    try:
        logger.info("Attempting to start in Resilient mode...")
        sniper = EliteSniperV2Resilient(run_mode="AUTO")
        success = sniper.run_resilient()
    except Exception as e:
        logger.error(f"Resilient mode failed: {e}")
        
        # العودة للوضع الأصلي كحل احتياطي
        logger.info("Falling back to standard mode...")
        sniper = EliteSniperV2()
        success = sniper.run()
    
    sys.exit(0 if success else 1)