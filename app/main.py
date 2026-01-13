import time
import os
import requests
import yfinance as yf
from datetime import datetime, time as dtime
import pytz

# ================= ENV =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MODE = os.getenv("MODE", "SAFE")  # SAFE / AGGRESSIVE
MAX_SIGNALS_PER_DAY = int(os.getenv("MAX_SIGNALS_PER_DAY", "6"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "90"))

# ================= SETTINGS =================
CHECK_EVERY_SECONDS = 900  # 15m
WARSAW_TZ = pytz.timezone("Europe/Warsaw")

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "META", "GOOGL", "AMD", "AVGO", "NFLX",
    "INTC", "ORCL", "CRM", "ADBE", "UBER",
    "SHOP", "PLTR", "COIN", "SNOW"
]

last_signal_time = {}
signals_today = 0
current_day = None

# ================= TELEGRAM =================
def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    })

# ================= TIME FILTER =================
def is_trading_hours():
    now = datetime.now(WARSAW_TZ).time()
    return dtime(15, 30) <= now <= dtime(22, 0)

# ================= MARKET BIAS (SAFE) =================
def market_bias():
    try:
        spy = yf.download("SPY", period="2d", interval="15m", progress=False)
        qqq = yf.download("QQQ", period="2d", interval="15m", progress=False)

        if spy is None or qqq is None:
            return "NEUTRAL"

        spy = spy.dropna()
        qqq = qqq.dropna()

        if len(spy) < 6 or len(qqq) < 6:
            return "NEUTRAL"

        spy_up = spy["Close"].iloc[-1] > spy["Close"].iloc[-5]
        qqq_up = qqq["Close"].iloc[-1] > qqq["Close"].iloc[-5]

        if spy_up and qqq_up:
            return "BULL"
        if not spy_up and not qqq_up:
            return "BEAR"

        return "MIXED"

    except Exception as e:
        print(f"[market_bias] fallback NEUTRAL: {e}")
        return "NEUTRAL"

# ================= 60m TREND FILTER (KEY EDGE) =================
def trend_60m(ticker):
    try:
        df = yf.download(ticker, period="7d", interval="60m", progress=False)
        if df is None:
            return None

        df = df.dropna()
        if len(df) < 10:
            return None

        # простой и надёжный тренд
        return "UP" if df["Close"].iloc[-1] > df["Close"].iloc[-5] else "DOWN"

    except Exception as e:
        print(f"[trend_60m] {ticker} error: {e}")
        return None

# ================= STRATEGY =================
def check_breakout(ticker, market_mode):
    try:
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if df is None:
            return None

        df = df.dropna()
        if len(df) < 30:
            return None

        price = df["Close"].iloc[-1]
        if price < 5:
            return None

        # ----- volume filter -----
        avg_vol = df["Volume"].iloc[-21:-1].mean()
        last_vol = df["Volume"].iloc[-1]

        vol_mult = 2.0 if MODE == "SAFE" else 1.3
        if last_vol < avg_vol * vol_mult:
            return None

        base = df.iloc[-21:-1]
        high = base["High"].max()
        low = base["Low"].min()

        t60 = trend_60m(ticker)
        if t60 is None:
            return None

        # ----- LONG -----
        if price > high:
            if t60 != "UP":
                return None
            if MODE == "SAFE" and market_mode == "BEAR":
                return None
            return "LONG", price, high

        # ----- SHORT -----
        if price < low:
            if t60 != "DOWN":
                return None
            if MODE == "SAFE" and market_mode == "BULL":
                return None
            return "SHORT", price, low

        return None

    except Exception as e:
        print(f"[check_breakout] {ticker} error: {e}")
        return None

# ================= MAIN =================
def main():
    global signals_today, current_day

    send(f"🚀 US Stocks PRO Bot STARTED\nРежим: {MODE}")

    while True:
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

            tv = f"https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}"

            msg = (
                f"🇺🇸 {ticker} | 15m INTRADAY\n"
                f"Режим: {MODE}\n"
                f"Рынок: {mkt}\n\n"
                f"СИГНАЛ: {side}\n"
                f"Цена: {price:.2f}\n"
                f"Уровень: {level:.2f}\n\n"
                f"План:\n"
                f"• Вход: рынок / ретест\n"
                f"• Стоп: за уровень\n"
                f"• Цель: 1.5–2R\n\n"
                f"📊 TradingView:\n{tv}"
            )

            send(msg)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
