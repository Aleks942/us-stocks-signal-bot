import time
import os
import requests
import yfinance as yf
from datetime import datetime, time as dtime
import pytz

# ================= ENV =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MODE = os.getenv("MODE", "SAFE")
MAX_SIGNALS_PER_DAY = int(os.getenv("MAX_SIGNALS_PER_DAY", "6"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "90"))

# ================= SETTINGS =================
CHECK_EVERY_SECONDS = 900
CACHE_TTL = 20 * 60  # 20 минут
WARSAW_TZ = pytz.timezone("Europe/Warsaw")

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "META", "GOOGL", "AMD", "AVGO", "NFLX",
    "INTC", "ORCL", "CRM", "ADBE", "UBER",
    "SHOP", "PLTR", "COIN", "SNOW"
]

# ================= STATE =================
last_signal_time = {}
signals_today = 0
current_day = None

price_cache = {}   # ticker -> (timestamp, df15, df60)
market_cache = {}  # "SPY"/"QQQ" -> (timestamp, df)

# ================= TELEGRAM =================
def send(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}
    )

# ================= TIME FILTER =================
def is_trading_hours():
    now = datetime.now(WARSAW_TZ).time()
    return dtime(15, 30) <= now <= dtime(22, 0)

# ================= SAFE DOWNLOAD =================
def safe_download(ticker, period, interval):
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        return df.dropna()
    except Exception as e:
        print(f"[download fail] {ticker} {interval}: {e}")
        return None

# ================= MARKET BIAS (CACHED) =================
def market_bias():
    now = time.time()
    try:
        for etf in ["SPY", "QQQ"]:
            ts, df = market_cache.get(etf, (0, None))
            if now - ts > CACHE_TTL or df is None:
                df_new = safe_download(etf, "2d", "15m")
                if df_new is not None and len(df_new) >= 6:
                    market_cache[etf] = (now, df_new)

        spy = market_cache.get("SPY", (0, None))[1]
        qqq = market_cache.get("QQQ", (0, None))[1]

        if not spy or not qqq:
            return "NEUTRAL"

        spy_up = spy["Close"].iloc[-1] > spy["Close"].iloc[-5]
        qqq_up = qqq["Close"].iloc[-1] > qqq["Close"].iloc[-5]

        if spy_up and qqq_up:
            return "BULL"
        if not spy_up and not qqq_up:
            return "BEAR"
        return "MIXED"

    except Exception as e:
        print(f"[market_bias fallback] {e}")
        return "NEUTRAL"

# ================= TREND 60m (CACHED) =================
def trend_60m(ticker):
    now = time.time()
    ts, df15, df60 = price_cache.get(ticker, (0, None, None))

    if now - ts > CACHE_TTL or df60 is None:
        df60_new = safe_download(ticker, "7d", "60m")
        if df60_new is not None and len(df60_new) >= 6:
            price_cache[ticker] = (now, df15, df60_new)
            df60 = df60_new

    if not df60:
        return None

    return "UP" if df60["Close"].iloc[-1] > df60["Close"].iloc[-5] else "DOWN"

# ================= STRATEGY =================
def check_breakout(ticker, market_mode):
    now = time.time()
    ts, df15, df60 = price_cache.get(ticker, (0, None, None))

    if now - ts > CACHE_TTL or df15 is None:
        df15_new = safe_download(ticker, "5d", "15m")
        if df15_new is not None and len(df15_new) >= 30:
            price_cache[ticker] = (now, df15_new, df60)
            df15 = df15_new

    if not df15:
        return None

    price = df15["Close"].iloc[-1]
    if price < 5:
        return None

    avg_vol = df15["Volume"].iloc[-21:-1].mean()
    last_vol = df15["Volume"].iloc[-1]
    vol_mult = 2.0 if MODE == "SAFE" else 1.3

    if last_vol < avg_vol * vol_mult:
        return None

    base = df15.iloc[-21:-1]
    high = base["High"].max()
    low = base["Low"].min()

    t60 = trend_60m(ticker)
    if not t60:
        return None

    if price > high and t60 == "UP" and (MODE != "SAFE" or market_mode != "BEAR"):
        return "LONG", price, high

    if price < low and t60 == "DOWN" and (MODE != "SAFE" or market_mode != "BULL"):
        return "SHORT", price, low

    return None

# ================= MAIN =================
def main():
    global signals_today, current_day

    send(f"🚀 US Stocks PRO Bot STARTED\nРежим: {MODE}")

    while True:
        try:
            now = datetime.now(WARSAW_TZ)
            today = now.date()

            if today != current_day:
                current_day = today
                signals_today = 0

            if not is_trading_hours():
                time.sleep(300)
                continue

            if signals_today >= MAX_SIGNALS_PER_DAY:
                time.sleep(300)
                continue

            mkt = market_bias()

            for ticker in TICKERS:
                if ticker in last_signal_time:
                    if time.time() - last_signal_time[ticker] < COOLDOWN_MINUTES * 60:
                        continue

                result = check_breakout(ticker, mkt)
                if not result:
                    continue

                side, price, level = result
                last_signal_time[ticker] = time.time()
                signals_today += 1

                send(
                    f"🇺🇸 {ticker} | 15m INTRADAY\n"
                    f"Режим: {MODE}\n"
                    f"Рынок: {mkt}\n\n"
                    f"СИГНАЛ: {side}\n"
                    f"Цена: {price:.2f}\n"
                    f"Уровень: {level:.2f}\n\n"
                    f"📊 https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}"
                )

            time.sleep(CHECK_EVERY_SECONDS)

        except Exception as e:
            print(f"[MAIN LOOP ERROR] {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
