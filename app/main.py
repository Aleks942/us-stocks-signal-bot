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
CACHE_TTL = 20 * 60
WARSAW_TZ = pytz.timezone("Europe/Warsaw")

TOP_N = 3

OPENING_START = dtime(15, 30)
OPENING_END   = dtime(17, 0)

TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","TSLA","META","GOOGL","AMD",
    "AVGO","NFLX","INTC","ORCL","CRM","ADBE","UBER","SHOP",
    "PLTR","COIN","SNOW"
]

# ================= STATE =================
price_cache = {}
market_cache = {}
last_signal_time = {}
signals_today = 0
current_day = None

earnings_block = set()
earnings_last_update = 0

# ================= TELEGRAM =================
def send(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}
    )

# ================= TIME =================
def is_trading_hours():
    now = datetime.now(WARSAW_TZ).time()
    return dtime(15, 30) <= now <= dtime(22, 0)

def is_opening_range():
    now = datetime.now(WARSAW_TZ).time()
    return OPENING_START <= now <= OPENING_END

# ================= SAFE DOWNLOAD =================
def safe_download(ticker, period, interval):
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        return df.dropna()
    except Exception:
        return None

# ================= EARNINGS GUARD =================
def update_earnings_block():
    global earnings_block, earnings_last_update
    if time.time() - earnings_last_update < 24*3600:
        return

    try:
        url = "https://api.nasdaq.com/api/calendar/earnings"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        symbols = set()
        for row in data["data"]["rows"]:
            symbols.add(row["symbol"])

        earnings_block = symbols
        earnings_last_update = time.time()
        print(f"[earnings] blocked {len(symbols)} tickers")

    except Exception as e:
        print("[earnings] failed, skipping:", e)

# ================= MARKET BIAS =================
def market_bias():
    now = time.time()
    for etf in ["SPY","QQQ"]:
        ts, df = market_cache.get(etf, (0,None))
        if now - ts > CACHE_TTL or df is None:
            new = safe_download(etf, "2d", "15m")
            if new is not None and len(new) >= 6:
                market_cache[etf] = (now, new)

    spy = market_cache.get("SPY",(0,None))[1]
    qqq = market_cache.get("QQQ",(0,None))[1]

    if not spy or not qqq:
        return "NEUTRAL"

    spy_up = spy["Close"].iloc[-1] > spy["Close"].iloc[-5]
    qqq_up = qqq["Close"].iloc[-1] > qqq["Close"].iloc[-5]

    if spy_up and qqq_up: return "BULL"
    if not spy_up and not qqq_up: return "BEAR"
    return "MIXED"

# ================= 60m TREND =================
def trend_60m(ticker):
    now = time.time()
    ts, df15, df60 = price_cache.get(ticker,(0,None,None))
    if now - ts > CACHE_TTL or df60 is None:
        df60n = safe_download(ticker,"7d","60m")
        if df60n is not None and len(df60n) >= 6:
            price_cache[ticker]=(now,df15,df60n)
            df60=df60n
    if not df60: return None
    return "UP" if df60["Close"].iloc[-1] > df60["Close"].iloc[-5] else "DOWN"

# ================= SCORE =================
def calc_score(df15, price, level):
    score = 0
    avg_vol = df15["Volume"].iloc[-21:-1].mean()
    last_vol = df15["Volume"].iloc[-1]
    rvol = last_vol / avg_vol if avg_vol > 0 else 0
    score += min(40, int(rvol * 15))

    rng = (df15["High"].iloc[-21:-1].max() - df15["Low"].iloc[-21:-1].min()) / price
    if rng < 0.02: score += 20
    elif rng < 0.03: score += 10

    dist = abs(price - level) / price
    score += min(20, int(dist * 500))

    if is_opening_range():
        score += 20

    return min(100, score)

# ================= STRATEGY =================
def scan_ticker(ticker, market_mode):
    if ticker in earnings_block:
        return None

    now = time.time()
    ts, df15, df60 = price_cache.get(ticker,(0,None,None))

    if now - ts > CACHE_TTL or df15 is None:
        df15n = safe_download(ticker,"5d","15m")
        if df15n is not None and len(df15n) >= 30:
            price_cache[ticker]=(now,df15n,df60)
            df15=df15n

    if not df15: return None

    price = df15["Close"].iloc[-1]
    if price < 5: return None

    base = df15.iloc[-21:-1]
    high = base["High"].max()
    low = base["Low"].min()

    t60 = trend_60m(ticker)
    if not t60: return None

    min_score = 55 if is_opening_range() else 60

    if price > high and t60=="UP" and (MODE!="SAFE" or market_mode!="BEAR"):
        score = calc_score(df15, price, high)
        if score >= min_score:
            return {"ticker":ticker,"side":"LONG","price":price,"level":high,"score":score}

    if price < low and t60=="DOWN" and (MODE!="SAFE" or market_mode!="BULL"):
        score = calc_score(df15, price, low)
        if score >= min_score:
            return {"ticker":ticker,"side":"SHORT","price":price,"level":low,"score":score}

    return None

# ================= MAIN =================
def main():
    global signals_today, current_day

    send(f"🚀 US Stocks PRO Bot STARTED\nРежим: {MODE}")

    while True:
        try:
            update_earnings_block()

            today = datetime.now(WARSAW_TZ).date()
            if today != current_day:
                current_day = today
                signals_today = 0

            if not is_trading_hours():
                time.sleep(300)
                continue

            if signals_today >= TOP_N:
                time.sleep(300)
                continue

            mkt = market_bias()
            candidates = []

            for t in TICKERS:
                if t in last_signal_time and time.time()-last_signal_time[t] < COOLDOWN_MINUTES*60:
                    continue
                res = scan_ticker(t, mkt)
                if res:
                    candidates.append(res)

            candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)[:TOP_N]

            for c in candidates:
                last_signal_time[c["ticker"]] = time.time()
                signals_today += 1

                tag = "OPENING RANGE" if is_opening_range() else "INTRADAY"

                send(
                    f"🇺🇸 {c['ticker']} | 15m {tag}\n"
                    f"Режим: {MODE}\n"
                    f"Score: {c['score']} / 100 ⭐\n\n"
                    f"СИГНАЛ: {c['side']}\n"
                    f"Цена: {c['price']:.2f}\n"
                    f"Уровень: {c['level']:.2f}"
                )

            time.sleep(CHECK_EVERY_SECONDS)

        except Exception as e:
            print("[MAIN ERROR]", e)
            time.sleep(60)

if __name__ == "__main__":
    main()

