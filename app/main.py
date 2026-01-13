import time
import os
import requests
import yfinance as yf
import pandas as pd

# ========= ENV =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========= SETTINGS =========
CHECK_EVERY_SECONDS = 900  # 15 минут
COOLDOWN_MINUTES = 60

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "META", "GOOGL", "AMD", "INTC", "AVGO"
]

last_signal_time = {}

# ========= TELEGRAM =========
def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text})

# ========= STRATEGY =========
def check_breakout(ticker):
    df = yf.download(
        ticker,
        period="5d",
        interval="15m",
        progress=False
    )

    if df is None or len(df) < 30:
        return None

    df = df.dropna()

    price = df["Close"].iloc[-1]
    if price < 5:
        return None

    base = df.iloc[-21:-1]
    high = base["High"].max()
    low = base["Low"].min()

    if price > high:
        return "LONG", price, high
    if price < low:
        return "SHORT", price, low

    return None

# ========= MAIN LOOP =========
def main():
    send("🚀 US Stocks Signal Bot — 15m intraday STARTED")

    while True:
        now = time.time()

        for ticker in TICKERS:
            # cooldown
            if ticker in last_signal_time:
                if now - last_signal_time[ticker] < COOLDOWN_MINUTES * 60:
                    continue

            result = check_breakout(ticker)
            if not result:
                continue

            side, price, level = result
            last_signal_time[ticker] = now

            msg = (
                f"🇺🇸 {ticker} | 15m INTRADAY\n\n"
                f"СИГНАЛ: {side}\n"
                f"Цена: {price:.2f}\n"
                f"Пробой уровня: {level:.2f}\n\n"
                f"План:\n"
                f"• Вход: по рынку / ретест\n"
                f"• Стоп: за уровень\n"
                f"• Цель: 1.5–2R"
            )

            send(msg)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
