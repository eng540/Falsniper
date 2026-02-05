#--- START OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: run.py ---
import os
import sys
import logging
from src.main import run_elite_sniper_v2

# إعداد السجلات
logging.basicConfig(level=logging.INFO, format='%(asctime)s [LAUNCHER] %(message)s')
logger = logging.getLogger("Launcher")

def check_environment():
    """التحقق من سلامة البيئة قبل التشغيل"""
    required_files = ['config.env', 'src/elite_sniper_v2.py']
    for f in required_files:
        if not os.path.exists(f):
            logger.error(f"❌ ملف مفقود وحرج: {f}")
            return False
    
    try:
        import playwright
        import ddddocr
    except ImportError as e:
        logger.error(f"❌ مكتبة مفقودة: {e.name}. يرجى تشغيل: pip install -r requirements.txt")
        return False

    return True

if __name__ == "__main__":
    logger.info("🛡️ CE-HUP v3.0 - جاري تحضير Elite Sniper V2...")
    
    if not check_environment():
        sys.exit(1)
        
    logger.info("✅ البيئة سليمة. جاري الإطلاق...")
    try:
        success = run_elite_sniper_v2()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("🛑 تم الإيقاف يدوياً.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"🔥 خطأ غير متوقع: {e}")
        sys.exit(1)
#--- END OF FULL, FINAL, AND CONFIRMED READY-TO-USE FILE: run.py ---