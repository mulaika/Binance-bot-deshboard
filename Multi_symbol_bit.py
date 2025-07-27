import os
import asyncio
import aiohttp
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tenacity import retry, stop_after_attempt, wait_exponential

# لاگنگ سیٹ اپ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# کنفیگریشن
BOT_TOKEN = "YOUR_BOT_TOKEN"  # ❌ اپنا ٹوکن ڈالیں
ADMIN_ID = "YOUR_ADMIN_ID"    # ❌ اپنا ٹیلیگرام آئی ڈی ڈالیں
CHANNEL_ID = "YOUR_CHANNEL_ID" # ❌ اپنا چینل آئی ڈی ڈالیں

# ٹائم فریمز اور کوائنز
ALL_TFs = ["5m", "15m", "30m", "1h", "4h", "1d"]
DEFAULT_TFs = ["5m", "15m", "30m", "1h"]
COINS = ["btcusdt", "ethusdt", "solusdt", "xrpusdt"]

# بوٹ انیشیالائزیشن
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
disp = Dispatcher(bot, storage=storage)
sched = AsyncIOScheduler()

# ڈیٹا بیس سیٹ اپ
DB_NAME = "crypto_bot.db"

def init_db():
    """ڈیٹا بیس کو شروع کرتا ہے"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, is_authorized INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
    logger.info("✅ ڈیٹا بیس تیار ہے")

init_db()

# =============================================================================
# بنیادی فنکشنز (Replit ورژن جیسے ہی)
# =============================================================================
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_binance_data(symbol, tf):
    """Binance API سے ڈیٹا وصول کرتا ہے"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": tf, "limit": 100}
    
    async with aiohttp.ClientSession() as sess:
        try:
            resp = await sess.get(url, params=params, timeout=15)
            data = await resp.json()
            
            if not data or not isinstance(data, list):
                logger.error(f"غلط ڈیٹا: {symbol}-{tf}")
                return None
                
            closes = [float(c[4]) for c in data]
            volumes = [float(c[5]) for c in data]
            
            return {"closes": closes, "volumes": volumes}
            
        except Exception as e:
            logger.error(f"ڈیٹا حاصل کرنے میں غلطی: {str(e)}")
            return None

async def fetch_crypto_signal(symbol, tf):
    """سگنل کیلکولیشن"""
    ohlc_data = await fetch_binance_data(symbol, tf)
    if not ohlc_data:
        return None
        
    # سادہ تجزیہ (پورا تجزیہ شامل کر سکتے ہیں)
    current_price = ohlc_data["closes"][-1]
    prev_price = ohlc_data["closes"][-2]
    change = ((current_price - prev_price) / prev_price) * 100
    
    signal = "🟢 BUY" if change > 0 else "🔴 SELL" if change < 0 else "🟡 NEUTRAL"
    
    return {
        "symbol": symbol.upper(),
        "tf": tf,
        "price": current_price,
        "change": round(change, 2),
        "signal": signal
    }

async def broadcast_signals():
    """سگنلز صارفین کو بھیجتا ہے"""
    try:
        msg = "📊 کریپٹو سگنلز:\n\n"
        for sym in COINS:
            for tf in DEFAULT_TFs:
                result = await fetch_crypto_signal(sym, tf)
                if result:
                    msg += f"{result['symbol']} ({tf}): {result['signal']} | {result['change']}%\n"
        
        # تمام اجازت یافتہ صارفین کو بھیجیں
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_authorized = 1")
        for user in c.fetchall():
            try:
                await bot.send_message(user[0], msg)
            except Exception as e:
                logger.error(f"صارف {user[0]} کو پیغام نہیں بھیج سکا: {str(e)}")
        conn.close()
        
    except Exception as e:
        logger.error(f"سگنل بھیجنے میں غلطی: {str(e)}")

@sched.scheduled_job("interval", minutes=5)
async def scheduled_job():
    logger.info("📡 سگنلز جمع کر رہا ہوں...")
    await broadcast_signals()

# =============================================================================
# ٹرمکس کے لیے موافقت شدہ کمانڈز
# =============================================================================
@disp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    try:
        user_id = msg.from_user.id
        username = msg.from_user.username or ""
        
        # ڈیٹا بیس میں صارف شامل کریں
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()
        
        await msg.reply("🤖 بوٹ فعال ہے! /help کمانڈ استعمال کریں")
        
    except Exception as e:
        logger.error(f"شروع کمانڈ میں غلطی: {str(e)}")

@disp.message_handler(commands=["help"])
async def cmd_help(msg: types.Message):
    help_msg = """
🆘 ٹرمکس بوٹ مدد 🆘

🔍 دستیاب کمانڈز:
/start - بوٹ شروع کریں
/help - مدد دیکھیں
/signals - سگنلز حاصل کریں
/addme - رسائی کی درخواست کریں"""
    
    await msg.reply(help_msg)

@disp.message_handler(commands=["signals"])
async def cmd_signals(msg: types.Message):
    user_id = msg.from_user.id
    
    # چیک کریں کہ صارف اجازت یافتہ ہے
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT is_authorized FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if not result or result[0] != 1:
        await msg.reply("❌ آپ کو اجازت نہیں ہے! /addme کمانڈ استعمال کریں")
        conn.close()
        return
    
    await msg.reply("⏳ سگنلز جمع کر رہا ہوں...")
    await broadcast_signals()

@disp.message_handler(commands=["addme"])
async def cmd_addme(msg: types.Message):
    user_id = msg.from_user.id
    username = msg.from_user.username or ""
    
    try:
        # صارف کو ڈیٹا بیس میں شامل کریں
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()
        
        # منتظم کو اطلاع
        admin_msg = (
            f"#️⃣ نئی درخواست:\n\n"
            f"👤 صارف: @{username}\n"
            f"🆔 آئی ڈی: {user_id}\n\n"
            f"✅ منظور کرنے کیلئے:\n"
            f"/approve_{user_id}"
        )
        
        await bot.send_message(ADMIN_ID, admin_msg)
        await msg.reply("✅ درخواست بھیج دی گئی! منتظم جلد رابطہ کریں گے")
        
    except Exception as e:
        logger.error(f"درخواست میں غلطی: {str(e)}")
        await msg.reply("❌ غلطی! دوبارہ کوشش کریں")

@disp.message_handler(lambda message: message.text.startswith('/approve_'))
async def approve_user(msg: types.Message):
    try:
        # صرف منتظم استعمال کر سکتا ہے
        if str(msg.from_user.id) != ADMIN_ID:
            return
            
        # صارف آئی ڈی نکالیں
        user_id = int(msg.text.split('_')[1])
        
        # ڈیٹا بیس میں اپ ڈیٹ کریں
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE users SET is_authorized = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        # صارف کو اطلاع
        await bot.send_message(user_id, "🎉 آپ کی درخواست منظور ہو گئی! اب آپ /signals کمانڈ استعمال کر سکتے ہیں")
        await msg.reply(f"✅ صارف {user_id} کو اجازت دے دی گئی!")
        
    except Exception as e:
        logger.error(f"منظوری دینے میں غلطی: {str(e)}")
        await msg.reply("❌ غلطی! صحیح فارمیٹ: /approve_123456")

# =============================================================================
# مین فنکشن - Termux کے لیے موافقت شدہ
# =============================================================================
async def main():
    logger.info("🚀 بوٹ شروع ہو رہا ہے...")
    
    # شیڈولر شروع کریں
    sched.start()
    
    # بوٹ پولنگ شروع کریں
    await disp.start_polling()
    
    # شیڈولر بند کریں جب بوٹ بند ہو
    sched.shutdown()
    logger.info("❌ بوٹ بند ہو رہا ہے")

if __name__ == "__main__":
    # Termux پر asyncio پالیسی سیٹ کریں
    import asyncio
    import platform
    
    if platform.system() == "Linux" and "android" in platform.release().lower():
        from asyncio import set_event_loop_policy, LinuxSelectorEventLoopPolicy
        set_event_loop_policy(LinuxSelectorEventLoopPolicy())
    
    asyncio.run(main())
