"""
Elite Sniper v2.0 - Configuration Module
Enhanced with proxy support, timing thresholds, and category mappings
"""

import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv("config.env")


class Config:
    """Centralized configuration for Elite Sniper v2.0"""
    
    # ==================== Telegram ====================
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    # ==================== Manual Captcha Settings ====================
    # When OCR fails, send captcha to Telegram for manual solving
    MANUAL_CAPTCHA_ENABLED = os.getenv("MANUAL_CAPTCHA", "true").lower() == "true"
    MANUAL_CAPTCHA_TIMEOUT = int(os.getenv("MANUAL_CAPTCHA_TIMEOUT", "60"))  # seconds
    
    # ==================== User Data ====================
    LAST_NAME = os.getenv("LAST_NAME")
    FIRST_NAME = os.getenv("FIRST_NAME")
    EMAIL = os.getenv("EMAIL")
    PASSPORT = os.getenv("PASSPORT")
    PHONE = os.getenv("PHONE")
    
    # ==================== Target ====================
    TARGET_URL = os.getenv("TARGET_URL")
    TIMEZONE = "Asia/Aden"  # GMT+3
    
    # ==================== Proxies (3 sessions) ====================
    # Format: "http://user:pass@host:port" or "socks5://host:port"
    PROXIES = [
        os.getenv("PROXY_1"),  # Scout proxy
        os.getenv("PROXY_2"),  # Attacker 1 proxy
        os.getenv("PROXY_3"),  # Attacker 2 proxy
    ]
    
    # ==================== Session Thresholds ====================
    SESSION_MAX_AGE = 45          # Maximum session age in seconds (REDUCED from 60 - server times out faster!)
    SESSION_MAX_IDLE = 12         # Maximum idle time before refresh (REDUCED from 15)
    HEARTBEAT_INTERVAL = 8        # Keep-alive interval in seconds (REDUCED from 10)
    MAX_CAPTCHA_ATTEMPTS = 5      # Per session before rebirth
    MAX_CONSECUTIVE_ERRORS = 3    # Before forced rebirth
    
    # ==================== Booking Purpose ====================
    # Valid values: study, student, work, family, tourism, other
    PURPOSE = os.getenv("PURPOSE", "study")
    
    # ==================== Timing Configuration ====================
    ATTACK_HOUR = 2               # Attack hour in Aden time (2:00 AM)
    PRE_ATTACK_MINUTE = 59        # Pre-attack minute (1:59 AM)
    PRE_ATTACK_SECOND = 30        # Pre-attack second (1:59:30 AM)
    ATTACK_WINDOW_MINUTES = 2     # Duration of attack window
    
    # ==================== Sleep Intervals ====================
    PATROL_SLEEP_MIN = 10.0       # Normal patrol minimum sleep
    PATROL_SLEEP_MAX = 20.0       # Normal patrol maximum sleep
    WARMUP_SLEEP = 5.0            # Warmup mode sleep
    ATTACK_SLEEP_MIN = 0.5        # Attack mode minimum sleep
    ATTACK_SLEEP_MAX = 1.5        # Attack mode maximum sleep
    PRE_ATTACK_SLEEP = 0.5        # Pre-attack ready state
    
    # ==================== Purpose/Category Values ====================
    # IMPORTANT: Website uses FULL TEXT values, NOT numeric IDs!
    # These are the exact option values from the form's select element
    PURPOSE_VALUES = {
        "voluntary": "Freiwilligendienst/Voluntary Service",
        "aupair": "Au-Pair",
        "language": "Sprachkurs/Language Course",
        "selfemployment": "Selbstständige Erwerbstätigkeit/Self Employment",
        "internship": "Praktikum/Internship",
        "school": "Schulbesuch/School Visit",
        # Aliases for convenience
        "study": "Sprachkurs/Language Course",
        "work": "Praktikum/Internship",
    }
    DEFAULT_PURPOSE = "Au-Pair"  # Default if not matched
    
    # Legacy CATEGORY_IDS kept for backward compatibility (deprecated)
    CATEGORY_IDS = PURPOSE_VALUES  # Alias
    
    # ==================== NTP Servers ====================
    NTP_SERVERS = [
        "pool.ntp.org",
        "time.google.com",
        "time.windows.com",
        "time.nist.gov"
    ]
    NTP_SYNC_INTERVAL = 300  # Re-sync every 5 minutes
    
    # ==================== Browser Configuration ====================
    HEADLESS = True
    BROWSER_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions"
    ]
    
    # ==================== Evidence Configuration ====================
    EVIDENCE_DIR = "evidence"
    MAX_EVIDENCE_AGE_HOURS = 48  # Auto-cleanup after 48 hours
