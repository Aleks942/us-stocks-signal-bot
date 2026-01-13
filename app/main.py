import time
import os
import requests
import yfinance as yf
from datetime import datetime, time as dtime
import pytz

# ========= ENV =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========= SETTINGS =========
CHECK_EVERY_SECONDS = 900   # 15m
MODE = os.getenv("MODE", "SAFE")  # SAFE / AGGRESSIVE
MAX_SIGNALS_PER_DAY = 6
COOLDOWN_MINUTES = 90

WARSAW_TZ = pytz.timezone("Europe/Warsaw")

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "META", "GOOGL", "AMD", "AVGO", "NFLX",
    "INTC", "ORCL", "CRM", "ADBE", "UBER",
    "SHOP", "PLTR", "COIN", "SNOW", "META"
]

last_signal_time = {}
signals_today = 0
current_day = None

# ========= TELEGRAM =========
def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text})

# ========= TIME FILTER =========
def is_trading_hours():
    now = datetime.now(WARSAW_TZ).time()
    return dtime(15, 30) <= now <= dtime(22, 0)

# ========= MARKET BIAS =========
def market_bias():
    spy = yf.download("SPY", period="2d", interval="15m", progress=False)
    qqq = yf.download("QQQ", period="2d", interval="15m", progress=False)

    if spy is None or qqq is None:
        return "NEUTRAL"

    spy_up = spy["Close"].iloc[-1] > spy["Close"].iloc[-5]
    qqq_up = qqq["Close"].iloc[-1] > qqq["Close"].iloc[-5]

    if spy_up and qqq_up:
        return "BULL"
    if not spy_up and not qqq_up:
        return "BEAR"
    return "MIXED"

# ========= STRATEGY =========
def check_breakout(ticker, bias):
    df = yf.download(ticker, period="5d", interval="15m", progress=False)
    if df is None or len(df) < 30:
        return None

    price = df["Close"].iloc[-1]
    if price < 5:
        return None

    avg_vol = df["Volume"].iloc[-21:-1].mean()
    last_vol = df["Volume"].iloc[-1]

    vol_mult = 2.0 if MODE == "SAFE" else 1.3
    if last_vol < avg_vol * vol_mult:
        return None

    base = df.iloc[-21:-1]
    high = base["High"].max()
    low = base["Low"].min()

    if price > high and bias in ["BULL", "MIXED"]:
        return "LONG", price, high

    if price < low and bias in ["BEAR", "MIXED"]:
        return "SHORT", price, low

    return None

# ========= MAIN =========
def main():
    global signals_today, current_day

    send(f"🚀 US Stocks PRO Bot STARTED\nРежим: {MODE}")

    while True:
        now = datetime.now(WARSAW_TZ)
        day = now.date()

        if day != current_day:
            current_day = day
            signals_today = 0

        if not is_trading_hours():
            time.sleep(300)
            continue

        if signals_today >= MAX_SIGNALS_PER_DAY:
            time.sleep(300)
            continue

        bias = market_bias()

        for ticker in TICKERS:
            if ticker in last_signal_time:
                if time.time() - last_signal_time[ticker] < COOLDOWN_MINUTES * 60:
                    continue

            result = check_breakout(ticker, bias)
            if not result:
                continue

            side, price, level = result
            last_signal_time[ticker] = time.time()
            signals_today += 1

            tv = f"https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}"

            msg = (
                f"🇺🇸 {ticker} | 15m INTRADAY\n"
                f"Режим: {MODE}\n"
                f"Рынок: {bias}\n\n"
                f"СИГНАЛ: {side}\n"
                f"Цена: {price:.2f}\n"
                f"Уровень: {level:.2f}\n\n"
                f"План:\n"
                f"• Вход: рынок / ретест\n"
                f"• Стоп: за уровень\n"
                f"• Цель: 1.5–2R\n\n"
                f"📊 {tv}"
            )

            send(msg)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
