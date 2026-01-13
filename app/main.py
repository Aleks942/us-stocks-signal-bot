import time
import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime

# ========= ENV =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========= SETTINGS =========
CHECK_EVERY_SECONDS = 900          # 15 минут
COOLDOWN_MINUTES = 60              # пауза по тикеру
DEBUG_EVERY_CYCLES = 8             # debug раз в N циклов

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "META", "GOOGL", "AMD", "INTC", "AVGO"
]

MARKET_ETFS = ["SPY", "QQQ"]

last_signal_time = {}
cycle_count = 0

# ========= TELEGRAM =========
def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    })

# ========= MARKET FILTER =========
def market_bias():
    bias = {}
    for etf in MARKET_ETFS:
        df = yf.download(etf, period="2d", interval="15m", progress=False)
        if df is None or len(df) < 10:
            continue
        df = df.dropna()
        bias[etf] = df["Close"].iloc[-1] > df["Close"].iloc[-5]
    return bias

# ========= STRATEGY =========
def check_breakout(ticker, mkt_bias):
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

    # --- volume filter ---
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    last_vol = df["Volume"].iloc[-1]
    if last_vol < avg_vol * 1.5:
        return None

    base = df.iloc[-21:-1]
    high = base["High"].max()
    low = base["Low"].min()

    # --- breakout logic ---
    if price > high and mkt_bias.get("SPY", True):
        return "LONG", price, high

    if price < low and not mkt_bias.get("SPY", False):
        return "SHORT", price, low

    return None

# ========= MAIN =========
def main():
    global cycle_count

    send("🚀 US Stocks Signal Bot — 15m intraday STARTED")

    while True:
        cycle_count += 1
        now = time.time()

        mkt_bias = market_bias()

        # --- DEBUG ---
        if cycle_count % DEBUG_EVERY_CYCLES == 0:
            send(
                f"📡 DEBUG\n"
                f"Цикл: {cycle_count}\n"
                f"SPY: {'UP' if mkt_bias.get('SPY') else 'DOWN'} | "
                f"QQQ: {'UP' if mkt_bias.get('QQQ') else 'DOWN'}\n"
                f"Время: {datetime.utcnow().strftime('%H:%M UTC')}"
            )

        for ticker in TICKERS:
            # cooldown
            if ticker in last_signal_time:
                if now - last_signal_time[ticker] < COOLDOWN_MINUTES * 60:
                    continue

            result = check_breakout(ticker, mkt_bias)
            if not result:
                continue

            side, price, level = result
            last_signal_time[ticker] = now

            tv_link = (
                f"https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}"
                if ticker not in ["AAPL", "MSFT", "AMZN"]
                else f"https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}"
            )

            msg = (
                f"🇺🇸 {ticker} | 15m INTRADAY\n\n"
                f"СИГНАЛ: {side}\n"
                f"Цена: {price:.2f}\n"
                f"Пробой уровня: {level:.2f}\n"
                f"Объём: x1.5+\n\n"
                f"Рынок:\n"
                f"• SPY: {'UP' if mkt_bias.get('SPY') else 'DOWN'}\n"
                f"• QQQ: {'UP' if mkt_bias.get('QQQ') else 'DOWN'}\n\n"
                f"План:\n"
                f"• Вход: по рынку / ретест\n"
                f"• Стоп: за уровень\n"
                f"• Цель: 1.5–2R\n\n"
                f"📊 TradingView:\n{tv_link}"
            )

            send(msg)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
