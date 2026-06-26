"""
MEGA BACKTEST — tests every strategy, every timeframe, every SL/TP combo.
Runs autonomously. Results written to mega_results.txt
"""
import requests, time, json, math
from datetime import datetime

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
RESULTS_FILE = "mega_results.txt"

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING — up to 3000 candles via pagination
# ─────────────────────────────────────────────────────────────────────────────

def fetch_candles_paged(pair, tf, n=3000):
    """Fetch up to n candles from Binance (paginated)."""
    all_candles = []
    end_time = None
    per_page = 1000
    pages = math.ceil(n / per_page)
    for _ in range(pages):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={per_page}"
        if end_time:
            url += f"&endTime={end_time}"
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            batch = [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
                     for c in r.json()]
            if not batch:
                break
            all_candles = batch + all_candles
            end_time = int(r.json()[0][0]) - 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  Fetch error {pair} {tf}: {e}")
            break
    return all_candles[-n:]

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

def ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def sma(values, period):
    if len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100.0
    return round(100 - 100 / (1 + ag / al), 2)

def compute_macd_full(closes):
    if len(closes) < 35:
        return 0, 0, 0
    macd_series = []
    for i in range(max(26, len(closes)-25), len(closes)+1):
        s = closes[:i]
        if len(s) < 26: continue
        macd_series.append(ema(s, 12) - ema(s, 26))
    if len(macd_series) < 9:
        return 0, 0, 0
    macd_line   = macd_series[-1]
    signal_line = ema(macd_series, 9)
    return macd_line, signal_line, macd_line - signal_line

def compute_atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][1], candles[i][2], candles[i-1][3]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(trs) < period: return sum(trs)/len(trs) if trs else 0
    return sum(trs[-period:])/period

def compute_adx(candles, period=14):
    if len(candles) < period+2: return 20
    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, len(candles)):
        h,l,ph,pl = candles[i][1],candles[i][2],candles[i-1][1],candles[i-1][2]
        pc = candles[i-1][3]
        plus_dms.append(max(h-ph,0) if (h-ph)>(pl-l) else 0)
        minus_dms.append(max(pl-l,0) if (pl-l)>(h-ph) else 0)
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr = sum(trs[-period:])/period
    if atr == 0: return 20
    pdi = sum(plus_dms[-period:])/period/atr*100
    mdi = sum(minus_dms[-period:])/period/atr*100
    dx = abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0
    return round(dx, 1)

def bollinger_bands(closes, period=20, std_dev=2.0):
    if len(closes) < period:
        m = closes[-1]; return m*0.98, m, m*1.02
    mid = sma(closes, period)
    variance = sum((c-mid)**2 for c in closes[-period:]) / period
    std = variance**0.5
    return mid - std_dev*std, mid, mid + std_dev*std

def compute_stoch_rsi(closes, period=14):
    if len(closes) < period*2:
        return 50.0
    rsi_series = [compute_rsi(closes[:i], period) for i in range(period+1, len(closes)+1)]
    if len(rsi_series) < period:
        return 50.0
    rsi_window = rsi_series[-period:]
    lo, hi = min(rsi_window), max(rsi_window)
    if hi == lo: return 50.0
    return (rsi_series[-1] - lo) / (hi - lo) * 100

def compute_williams_r(candles, period=14):
    if len(candles) < period:
        return -50.0
    w = candles[-period:]
    hi = max(c[1] for c in w)
    lo = min(c[2] for c in w)
    close = candles[-1][3]
    if hi == lo: return -50.0
    return (hi - close) / (hi - lo) * -100

def compute_cci(candles, period=20):
    if len(candles) < period:
        return 0
    tps = [(c[1]+c[2]+c[3])/3 for c in candles[-period:]]
    mean_tp = sum(tps)/period
    mean_dev = sum(abs(tp-mean_tp) for tp in tps)/period
    if mean_dev == 0: return 0
    return (tps[-1]-mean_tp)/(0.015*mean_dev)

def compute_vwap(candles):
    pv = sum(((c[1]+c[2]+c[3])/3)*c[4] for c in candles)
    vol = sum(c[4] for c in candles)
    return pv/vol if vol > 0 else candles[-1][3]

def donchian_high(candles, period=20):
    return max(c[1] for c in candles[-period:]) if len(candles) >= period else candles[-1][1]

def donchian_low(candles, period=20):
    return min(c[2] for c in candles[-period:]) if len(candles) >= period else candles[-1][2]

# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(candles, signal_fn, sl_pct, tp_pct, max_hold=50):
    wins, losses, timeouts = 0, 0, 0
    pnl_list = []
    min_lookback = 60

    for i in range(min_lookback, len(candles) - max_hold - 1):
        try:
            hist = candles[:i]
            signal = signal_fn(hist)
            if signal != "BUY":
                continue
            entry = candles[i][3]
            sl = entry * (1 - sl_pct)
            tp = entry * (1 + tp_pct)
            outcome = None
            for j in range(i+1, min(i+max_hold+1, len(candles))):
                if candles[j][2] <= sl:
                    outcome = "LOSS"
                    pnl_list.append(-sl_pct)
                    break
                if candles[j][1] >= tp:
                    outcome = "WIN"
                    pnl_list.append(tp_pct)
                    break
            if outcome == "WIN":   wins += 1
            elif outcome == "LOSS": losses += 1
            else: timeouts += 1
        except Exception:
            continue

    total = wins + losses
    wr = wins/total if total > 0 else 0
    ev = sum(pnl_list)/len(pnl_list) if pnl_list else 0
    return {"wins": wins, "losses": losses, "timeouts": timeouts,
            "total": total, "wr": wr, "ev": ev, "pnl_list": pnl_list}

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

def strat_ema_cross(candles):
    """EMA 9 crosses above EMA 21 — classic trend entry."""
    closes = [c[3] for c in candles]
    if len(closes) < 22: return "HOLD"
    e9 = ema(closes, 9); e9p = ema(closes[:-1], 9)
    e21 = ema(closes, 21); e21p = ema(closes[:-1], 21)
    price = closes[-1]
    if e9 > e21 and e9p <= e21p:
        rsi = compute_rsi(closes)
        if rsi < 70:
            return "BUY"
    return "HOLD"


def strat_ema_cross_filtered(candles):
    """EMA 9/21 cross + EMA 50 alignment + volume."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 52: return "HOLD"
    e9 = ema(closes, 9); e9p = ema(closes[:-1], 9)
    e21 = ema(closes, 21); e21p = ema(closes[:-1], 21)
    e50 = ema(closes, 50)
    price = closes[-1]
    if not (e9 > e21 and e9p <= e21p): return "HOLD"
    if price < e50: return "HOLD"
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 0.8: return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 72: return "HOLD"
    # Last candle must be green
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    return "BUY"


def strat_ema_stack_pullback(candles):
    """EMA 9>21>50 uptrend + price pulls back near EMA21 + green recovery."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 55: return "HOLD"
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    price = closes[-1]
    if not (e9 > e21 > e50): return "HOLD"
    # Price touched or came near EMA21
    dist = abs(price - e21) / e21 * 100
    if dist > 1.5: return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 68 or rsi < 25: return "HOLD"
    # Last candle green
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    if hist < 0 and macd < 0: return "HOLD"
    return "BUY"


def strat_rsi_oversold(candles):
    """RSI < 30 in uptrend — classic oversold bounce."""
    closes = [c[3] for c in candles]
    if len(closes) < 30: return "HOLD"
    rsi = compute_rsi(closes)
    rsi_prev = compute_rsi(closes[:-1])
    if rsi < 30 and rsi > rsi_prev:  # RSI was oversold and turning up
        e21 = ema(closes, 21); e50 = ema(closes, 50)
        price = closes[-1]
        if price > e50:  # still in general uptrend
            return "BUY"
    return "HOLD"


def strat_rsi_oversold_strict(candles):
    """RSI < 25 then turning up + MACD + green candle."""
    closes = [c[3] for c in candles]
    if len(closes) < 40: return "HOLD"
    rsi = compute_rsi(closes)
    rsi_prev = compute_rsi(closes[:-1])
    if rsi > 35 or rsi < rsi_prev: return "HOLD"
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    e50 = ema(closes, 50)
    if closes[-1] < e50: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    if hist < 0 and macd < 0: return "HOLD"
    return "BUY"


def strat_macd_cross(candles):
    """MACD line crosses above signal line."""
    closes = [c[3] for c in candles]
    if len(closes) < 40: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    # Histogram just turned positive (MACD crossed above signal)
    if hist > 0 and hist_prev <= 0:
        rsi = compute_rsi(closes)
        if rsi < 70:
            e50 = ema(closes, 50)
            if closes[-1] > e50:
                return "BUY"
    return "HOLD"


def strat_macd_cross_filtered(candles):
    """MACD cross + green candle + EMA alignment + volume."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 50: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    if not (hist > 0 and hist_prev <= 0): return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 68: return "HOLD"
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    if not (e9 > e21 > e50): return "HOLD"
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 0.7: return "HOLD"
    return "BUY"


def strat_bollinger_bounce(candles):
    """Price touches lower Bollinger Band — mean reversion buy."""
    closes = [c[3] for c in candles]
    if len(closes) < 25: return "HOLD"
    lower, mid, upper = bollinger_bands(closes)
    price = closes[-1]
    prev_price = closes[-2]
    # Previous candle touched or went below lower band, current is above
    lower_prev, _, _ = bollinger_bands(closes[:-1])
    if prev_price <= lower_prev and price > lower:
        rsi = compute_rsi(closes)
        if 20 < rsi < 55:
            e50 = ema(closes, 50)
            if price > e50 * 0.97:  # not too deep in bear market
                return "BUY"
    return "HOLD"


def strat_bollinger_bounce_strict(candles):
    """BB lower touch + RSI < 30 + MACD improving + green candle."""
    closes = [c[3] for c in candles]
    if len(closes) < 30: return "HOLD"
    lower, mid, upper = bollinger_bands(closes)
    price = closes[-1]
    # Candle low touched lower band
    if candles[-1][2] > lower * 1.005: return "HOLD"
    if price < candles[-1][0]: return "HOLD"  # must close green
    rsi = compute_rsi(closes)
    if rsi > 45: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    if hist < hist_prev: return "HOLD"  # MACD must be improving
    return "BUY"


def strat_donchian_breakout(candles):
    """Price breaks above 20-candle Donchian high with volume."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 25: return "HOLD"
    prev_high = donchian_high(candles[:-1], 20)
    price = closes[-1]
    if price <= prev_high: return "HOLD"
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 1.3: return "HOLD"  # need volume confirmation
    rsi = compute_rsi(closes)
    if rsi > 78: return "HOLD"  # not overbought
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    return "BUY"


def strat_donchian_breakout_strict(candles):
    """Donchian breakout + EMA stack + ADX trend + volume spike."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 55: return "HOLD"
    prev_high = donchian_high(candles[:-1], 20)
    price = closes[-1]
    if price <= prev_high: return "HOLD"
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    if not (e9 > e21 > e50): return "HOLD"
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 1.5: return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 75: return "HOLD"
    adx = compute_adx(candles)
    if adx < 20: return "HOLD"
    return "BUY"


def strat_stochrsi_oversold(candles):
    """Stochastic RSI < 20 turning up in uptrend."""
    closes = [c[3] for c in candles]
    if len(closes) < 60: return "HOLD"
    srsi = compute_stoch_rsi(closes)
    srsi_prev = compute_stoch_rsi(closes[:-1])
    if srsi > 25 or srsi < srsi_prev: return "HOLD"  # need to be oversold and turning
    e21 = ema(closes, 21); e50 = ema(closes, 50)
    price = closes[-1]
    if not (price > e50): return "HOLD"
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    if macd < 0 and hist < 0: return "HOLD"
    return "BUY"


def strat_williams_r_bounce(candles):
    """Williams %R oversold (-80 to -100) turning up."""
    closes = [c[3] for c in candles]
    if len(closes) < 20: return "HOLD"
    wr = compute_williams_r(candles)
    wr_prev = compute_williams_r(candles[:-1])
    if wr < -80 and wr > wr_prev:  # was oversold, now recovering
        e50 = ema(closes, 50)
        if closes[-1] > e50 * 0.97:
            rsi = compute_rsi(closes)
            if rsi < 50:
                return "BUY"
    return "HOLD"


def strat_cci_oversold(candles):
    """CCI below -100 turning up — oversold in downward push."""
    closes = [c[3] for c in candles]
    if len(closes) < 25: return "HOLD"
    cci_val = compute_cci(candles)
    cci_prev = compute_cci(candles[:-1])
    if cci_val < -100 and cci_val > cci_prev:
        e50 = ema(closes, 50)
        if closes[-1] > e50 * 0.96:
            if candles[-1][3] > candles[-1][0]:  # green candle
                return "BUY"
    return "HOLD"


def strat_vwap_bounce(candles):
    """Price dips below VWAP then recovers above it — intraday support."""
    closes = [c[3] for c in candles]
    if len(closes) < 30: return "HOLD"
    # Use last 24 candles as "session"
    session = candles[-24:]
    vwap = compute_vwap(session)
    price = closes[-1]
    prev_price = closes[-2]
    if prev_price < vwap and price > vwap:  # crossed above VWAP
        rsi = compute_rsi(closes)
        if 30 < rsi < 65:
            e21 = ema(closes, 21)
            if price > e21:
                return "BUY"
    return "HOLD"


def strat_triple_ema(candles):
    """Triple EMA system: EMA4, EMA9, EMA18 alignment with crossover."""
    closes = [c[3] for c in candles]
    if len(closes) < 22: return "HOLD"
    e4 = ema(closes, 4); e4p = ema(closes[:-1], 4)
    e9 = ema(closes, 9); e9p = ema(closes[:-1], 9)
    e18 = ema(closes, 18)
    price = closes[-1]
    # EMA4 crossed above EMA9 and EMA9 > EMA18
    if e4 > e9 and e4p <= e9p and e9 > e18:
        rsi = compute_rsi(closes)
        if rsi < 70:
            if candles[-1][3] > candles[-1][0]:
                return "BUY"
    return "HOLD"


def strat_golden_cross(candles):
    """EMA50 crosses above EMA200 — major trend signal."""
    closes = [c[3] for c in candles]
    if len(closes) < 205: return "HOLD"
    e50 = ema(closes, 50); e50p = ema(closes[:-1], 50)
    e200 = ema(closes, 200); e200p = ema(closes[:-1], 200)
    if e50 > e200 and e50p <= e200p:
        return "BUY"
    return "HOLD"


def strat_volume_spike_green(candles):
    """Massive volume spike on a green candle — institutional buying."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 25: return "HOLD"
    avg_vol = sum(vols[-21:-1])/20
    if vols[-1] < avg_vol * 2.5: return "HOLD"  # need 2.5x volume
    if candles[-1][3] < candles[-1][0]: return "HOLD"  # must be green
    body = candles[-1][3] - candles[-1][0]
    c_range = candles[-1][1] - candles[-1][2]
    if c_range > 0 and body/c_range < 0.5: return "HOLD"  # need solid body
    rsi = compute_rsi(closes)
    if rsi > 75: return "HOLD"
    e21 = ema(closes, 21)
    if closes[-1] < e21 * 0.95: return "HOLD"
    return "BUY"


def strat_three_green_candles(candles):
    """Three consecutive green candles with rising volume — momentum."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 30: return "HOLD"
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not (c1[3] > c1[0] and c2[3] > c2[0] and c3[3] > c3[0]): return "HOLD"
    if not (c2[3] > c1[3] and c3[3] > c2[3]): return "HOLD"  # each higher close
    if not (vols[-2] > vols[-3] and vols[-1] >= vols[-2] * 0.7): return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 72: return "HOLD"
    e50 = ema(closes, 50)
    if closes[-1] < e50: return "HOLD"
    return "BUY"


def strat_hammer_at_support(candles):
    """Hammer candle at swing low — strong reversal signal."""
    closes = [c[3] for c in candles]
    if len(closes) < 30: return "HOLD"
    c = candles[-1]
    body = abs(c[3] - c[0])
    c_range = c[1] - c[2]
    if c_range == 0: return "HOLD"
    lower_wick = min(c[3], c[0]) - c[2]
    upper_wick = c[1] - max(c[3], c[0])
    # Hammer: lower wick > 2x body, small upper wick, green candle
    if not (lower_wick > body * 2 and upper_wick < body * 0.5 and c[3] > c[0]):
        return "HOLD"
    # Must be near recent swing low
    recent_lows = [candles[j][2] for j in range(-10, 0)]
    swing_low = min(recent_lows)
    if c[2] > swing_low * 1.005:  # hammer low should be near recent low
        return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 55: return "HOLD"
    e50 = ema(closes, 50)
    if closes[-1] < e50 * 0.96: return "HOLD"
    return "BUY"


def strat_engulfing_bullish(candles):
    """Bullish engulfing candle — strong reversal."""
    closes = [c[3] for c in candles]
    if len(closes) < 25: return "HOLD"
    prev, curr = candles[-2], candles[-1]
    # Previous candle red, current candle green and engulfs previous
    if not (prev[3] < prev[0]): return "HOLD"
    if not (curr[3] > curr[0]): return "HOLD"
    if not (curr[0] <= prev[3] and curr[3] >= prev[0]): return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 68: return "HOLD"
    e21 = ema(closes, 21); e50 = ema(closes, 50)
    if closes[-1] < e50 * 0.97: return "HOLD"
    return "BUY"


def strat_adx_trend_entry(candles):
    """Strong ADX trend + EMA stack + MACD positive."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 60: return "HOLD"
    adx = compute_adx(candles)
    if adx < 30: return "HOLD"  # only in strong trends
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    price = closes[-1]
    if not (e9 > e21 > e50 and price > e9): return "HOLD"
    macd, sig, hist = compute_macd_full(closes)
    if hist <= 0: return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 70 or rsi < 30: return "HOLD"
    # Pullback: price came near EMA9 recently
    recent_lows = [candles[j][2] for j in range(-5, -1)]
    if min(recent_lows) > e9 * 1.01: return "HOLD"  # no recent touch of EMA9
    if candles[-1][3] < candles[-1][0]: return "HOLD"
    return "BUY"


def strat_multi_confluence(candles):
    """Requires 4+ conditions to all agree — high selectivity."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 60: return "HOLD"
    conditions = 0

    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    price = closes[-1]

    if e9 > e21 > e50 and price > e9: conditions += 1
    rsi = compute_rsi(closes)
    if 35 < rsi < 60: conditions += 1
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    if hist > 0 and hist > hist_prev: conditions += 1
    avg_vol = sum(vols[-20:])/20
    if vols[-1] > avg_vol * 1.2: conditions += 1
    adx = compute_adx(candles)
    if adx > 22: conditions += 1
    lower, mid, upper = bollinger_bands(closes)
    dist_to_lower = (price - lower) / price * 100
    if dist_to_lower < 1.5: conditions += 1  # near lower band
    if candles[-1][3] > candles[-1][0]: conditions += 1
    # Hammer or engulfing
    c = candles[-1]; prev = candles[-2]
    body = abs(c[3]-c[0]); c_range = c[1]-c[2]
    if c_range > 0:
        lower_wick = min(c[3],c[0]) - c[2]
        if lower_wick > body * 2 and c[3] > c[0]: conditions += 1
        if prev[3] < prev[0] and c[3] > c[0] and c[0] <= prev[3] and c[3] >= prev[0]: conditions += 1

    if conditions >= 5:
        return "BUY"
    return "HOLD"


def strat_trend_momentum_hybrid(candles):
    """Hybrid: trend + momentum + oversold recovery + volume."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 60: return "HOLD"

    # 1. Must be in uptrend
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    price = closes[-1]
    if not (e9 > e21 > e50): return "HOLD"

    # 2. RSI pullback and recovering (35-58 range, turning up)
    rsi = compute_rsi(closes)
    rsi_prev = compute_rsi(closes[:-1])
    if not (35 <= rsi <= 60 and rsi > rsi_prev): return "HOLD"

    # 3. MACD histogram positive or just turned positive
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    if hist < 0 and hist < hist_prev: return "HOLD"

    # 4. Green candle
    if candles[-1][3] < candles[-1][0]: return "HOLD"

    # 5. Not at major resistance
    recent_highs = sorted([candles[j][1] for j in range(-20, -1)], reverse=True)
    nearest_res = next((h for h in recent_highs if h > price), None)
    if nearest_res and (nearest_res - price) / price < 0.004: return "HOLD"

    return "BUY"


def strat_squeeze_breakout(candles):
    """BB squeeze then expansion — volatility breakout."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 30: return "HOLD"

    # Detect squeeze: current BB width < avg BB width of last 20 bars
    lower, mid, upper = bollinger_bands(closes)
    bb_width = (upper - lower) / mid

    bb_widths = []
    for k in range(20, 0, -1):
        lo, m, hi = bollinger_bands(closes[:-k] if k > 0 else closes)
        bb_widths.append((hi - lo) / m if m > 0 else 0)
    avg_bb_width = sum(bb_widths) / len(bb_widths) if bb_widths else bb_width

    # Squeeze: current width is narrow
    if bb_width > avg_bb_width * 0.75: return "HOLD"

    # Expansion: current candle breaks above upper band
    if candles[-1][3] <= upper: return "HOLD"
    if candles[-1][3] < candles[-1][0]: return "HOLD"  # green

    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 1.3: return "HOLD"

    rsi = compute_rsi(closes)
    if rsi > 78: return "HOLD"
    return "BUY"


def strat_rsi_divergence(candles):
    """Bullish RSI divergence: price makes lower low but RSI makes higher low."""
    closes = [c[3] for c in candles]
    if len(closes) < 30: return "HOLD"

    # Find two recent swing lows in price
    price_lows = []
    for i in range(-15, -2):
        if candles[i][2] < candles[i-1][2] and candles[i][2] < candles[i+1][2]:
            rsi_at_low = compute_rsi(closes[:len(closes)+i+1] if i < 0 else closes)
            price_lows.append((i, candles[i][2], rsi_at_low))

    if len(price_lows) < 2: return "HOLD"

    l1_idx, l1_price, l1_rsi = price_lows[-2]
    l2_idx, l2_price, l2_rsi = price_lows[-1]

    # Bullish divergence: price lower low, RSI higher low
    if l2_price < l1_price and l2_rsi > l1_rsi + 3:
        e50 = ema(closes, 50)
        if closes[-1] > e50 * 0.96:
            rsi_now = compute_rsi(closes)
            if rsi_now < 55:
                if candles[-1][3] > candles[-1][0]:
                    return "BUY"
    return "HOLD"


def strat_opening_range_breakout(candles):
    """Price consolidates for 5 candles then breaks up with volume."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 15: return "HOLD"

    # Measure range of last 5 candles
    consolidation = candles[-6:-1]
    hi = max(c[1] for c in consolidation)
    lo = min(c[2] for c in consolidation)
    range_pct = (hi - lo) / lo * 100

    # Range must be narrow (consolidation)
    if range_pct > 1.5: return "HOLD"

    # Current candle breaks above the consolidation high
    price = closes[-1]
    if price <= hi: return "HOLD"

    # With volume
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 1.2: return "HOLD"

    if candles[-1][3] < candles[-1][0]: return "HOLD"
    rsi = compute_rsi(closes)
    if rsi > 75: return "HOLD"
    return "BUY"


def strat_supertrend_like(candles):
    """Supertrend-like: ATR-based trend following."""
    closes = [c[3] for c in candles]
    if len(closes) < 20: return "HOLD"

    atr = compute_atr(candles)
    multiplier = 3.0
    price = closes[-1]

    # Basic supertrend: upper = (high+low)/2 + multiplier*ATR
    # If price > previous upper band → uptrend
    hl2 = (candles[-1][1] + candles[-1][2]) / 2
    upper_band = hl2 + multiplier * atr

    hl2_prev = (candles[-2][1] + candles[-2][2]) / 2
    atr_prev = compute_atr(candles[:-1])
    upper_prev = hl2_prev + multiplier * atr_prev

    prev_price = closes[-2]

    # Signal: price crosses above upper band (trend up)
    if price > upper_band and prev_price <= upper_prev:
        rsi = compute_rsi(closes)
        if 30 < rsi < 72:
            e50 = ema(closes, 50)
            if price > e50:
                return "BUY"
    return "HOLD"


def strat_combined_best(candles):
    """Best combination from optimization — strict multi-condition."""
    closes = [c[3] for c in candles]; vols = [c[4] for c in candles]
    if len(closes) < 65: return "HOLD"

    # HARD BLOCKS
    price = closes[-1]
    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50)
    if not (e9 > e21 > e50): return "HOLD"
    if price < e50: return "HOLD"

    # Green candle with meaningful body
    c = candles[-1]
    if c[3] < c[0]: return "HOLD"
    body_pct = (c[3] - c[0]) / c[0] * 100
    if body_pct < 0.05: return "HOLD"

    # RSI in sweet spot
    rsi = compute_rsi(closes); rsi_prev = compute_rsi(closes[:-1])
    if rsi > 68 or rsi < 28: return "HOLD"
    if rsi < rsi_prev - 5: return "HOLD"  # RSI shouldn't be crashing

    # MACD positive or improving
    macd, sig, hist = compute_macd_full(closes)
    _, _, hist_prev = compute_macd_full(closes[:-1])
    if hist < 0 and hist < hist_prev: return "HOLD"

    # Volume confirmation
    avg_vol = sum(vols[-20:])/20
    if vols[-1] < avg_vol * 0.6: return "HOLD"

    # ADX — some trend required
    adx = compute_adx(candles)
    if adx < 15: return "HOLD"

    # Not in crash mode
    high_30 = max(c[1] for c in candles[-30:])
    if (high_30 - price) / high_30 > 0.06: return "HOLD"

    # Not at resistance
    recent_highs = [candles[j][1] for j in range(-20, -1)]
    nearest_res = min((h for h in recent_highs if h > price), default=None)
    if nearest_res and (nearest_res - price) / price < 0.004: return "HOLD"

    # Recent RSI not overbought (distribution top filter)
    recent_rsi_max = max(compute_rsi(closes[:-k]) for k in range(1, min(6, len(closes)-15)))
    if recent_rsi_max > 76 and rsi > 58: return "HOLD"

    return "BUY"


# All strategies to test
STRATEGIES = {
    "EMA_Cross":                strat_ema_cross,
    "EMA_Cross_Filtered":       strat_ema_cross_filtered,
    "EMA_Stack_Pullback":       strat_ema_stack_pullback,
    "RSI_Oversold":             strat_rsi_oversold,
    "RSI_Oversold_Strict":      strat_rsi_oversold_strict,
    "MACD_Cross":               strat_macd_cross,
    "MACD_Cross_Filtered":      strat_macd_cross_filtered,
    "Bollinger_Bounce":         strat_bollinger_bounce,
    "Bollinger_Bounce_Strict":  strat_bollinger_bounce_strict,
    "Donchian_Breakout":        strat_donchian_breakout,
    "Donchian_Breakout_Strict": strat_donchian_breakout_strict,
    "StochRSI_Oversold":        strat_stochrsi_oversold,
    "Williams_R_Bounce":        strat_williams_r_bounce,
    "CCI_Oversold":             strat_cci_oversold,
    "VWAP_Bounce":              strat_vwap_bounce,
    "Triple_EMA":               strat_triple_ema,
    "Golden_Cross":             strat_golden_cross,
    "Volume_Spike_Green":       strat_volume_spike_green,
    "Three_Green_Candles":      strat_three_green_candles,
    "Hammer_At_Support":        strat_hammer_at_support,
    "Engulfing_Bullish":        strat_engulfing_bullish,
    "ADX_Trend_Entry":          strat_adx_trend_entry,
    "Multi_Confluence":         strat_multi_confluence,
    "Trend_Momentum_Hybrid":    strat_trend_momentum_hybrid,
    "Squeeze_Breakout":         strat_squeeze_breakout,
    "RSI_Divergence":           strat_rsi_divergence,
    "Opening_Range_Breakout":   strat_opening_range_breakout,
    "Supertrend_Like":          strat_supertrend_like,
    "Combined_Best":            strat_combined_best,
}

# SL/TP combos to test
SL_TP_COMBOS = [
    (0.003, 0.006),
    (0.004, 0.008),
    (0.005, 0.010),
    (0.006, 0.012),
    (0.008, 0.016),
    (0.010, 0.020),
    (0.012, 0.024),
    (0.015, 0.030),
    (0.005, 0.015),  # 1:3 ratio
    (0.008, 0.024),  # 1:3 ratio
    (0.010, 0.030),  # 1:3 ratio
    (0.003, 0.009),  # 1:3 tight
]

# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def log(msg, also_print=True):
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    if also_print:
        print(msg)

def main():
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write(f"MEGA BACKTEST RESULTS — Started {started}\n")
        f.write("="*80 + "\n\n")

    log(f"Started: {started}")
    log(f"Strategies: {len(STRATEGIES)} | Timeframes: {len(TIMEFRAMES)} | SL/TP combos: {len(SL_TP_COMBOS)}")
    log(f"Pairs: {PAIRS}\n")

    # Fetch all candle data upfront
    log("Fetching historical data (3000 candles per pair/timeframe)...")
    all_data = {}
    for tf in TIMEFRAMES:
        all_data[tf] = {}
        for pair in PAIRS:
            log(f"  Fetching {pair} {tf}...")
            candles = fetch_candles_paged(pair, tf, n=3000)
            all_data[tf][pair] = candles
            log(f"    Got {len(candles)} candles")
            time.sleep(0.5)
    log("\nData fetched. Starting backtest...\n")

    # Store all results
    all_results = []

    # Test each strategy on each timeframe with each SL/TP combo
    total_combos = len(STRATEGIES) * len(TIMEFRAMES) * len(SL_TP_COMBOS) * len(PAIRS)
    done = 0

    for tf in TIMEFRAMES:
        log(f"\n{'='*70}")
        log(f"TIMEFRAME: {tf}")
        log(f"{'='*70}")

        best_per_tf = []

        for strat_name, strat_fn in STRATEGIES.items():
            for sl, tp in SL_TP_COMBOS:
                combined_wins, combined_losses, combined_timeouts = 0, 0, 0
                combined_pnl = []

                for pair in PAIRS:
                    candles = all_data[tf][pair]
                    if len(candles) < 70:
                        continue
                    res = run_backtest(candles, strat_fn, sl, tp)
                    combined_wins += res["wins"]
                    combined_losses += res["losses"]
                    combined_timeouts += res["timeouts"]
                    combined_pnl.extend(res["pnl_list"])
                    done += 1

                total = combined_wins + combined_losses
                if total < 5:  # need at least 5 trades to be meaningful
                    continue

                wr = combined_wins / total
                ev = sum(combined_pnl) / len(combined_pnl) if combined_pnl else 0

                result = {
                    "tf": tf, "strat": strat_name, "sl": sl, "tp": tp,
                    "wins": combined_wins, "losses": combined_losses,
                    "timeouts": combined_timeouts, "total": total,
                    "wr": wr, "ev": ev
                }
                all_results.append(result)
                best_per_tf.append(result)

        # Show top 10 for this timeframe
        best_per_tf.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
        log(f"\nTOP 10 for {tf}:")
        log(f"  {'Strategy':<28} {'SL%':>4} {'TP%':>4} | {'Trades':>6} {'WR%':>6} {'EV%':>7}")
        log(f"  {'-'*65}")
        for r in best_per_tf[:10]:
            log(f"  {r['strat']:<28} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                f"{r['total']:>6} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")

    # ── GLOBAL TOP 30 ─────────────────────────────────────────────────────────
    log("\n\n" + "="*80)
    log("GLOBAL TOP 30 — ALL TIMEFRAMES (ranked by win rate, min 10 trades)")
    log("="*80)
    filtered = [r for r in all_results if r["total"] >= 10]
    filtered.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    log(f"\n  {'TF':<5} {'Strategy':<28} {'SL%':>4} {'TP%':>4} | {'Trades':>6} {'WR%':>6} {'EV%':>7}")
    log(f"  {'-'*75}")
    for r in filtered[:30]:
        log(f"  {r['tf']:<5} {r['strat']:<28} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
            f"{r['total']:>6} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")

    # ── BEST PER TIMEFRAME SUMMARY ─────────────────────────────────────────────
    log("\n\n" + "="*80)
    log("BEST STRATEGY PER TIMEFRAME")
    log("="*80)
    for tf in TIMEFRAMES:
        tf_results = [r for r in all_results if r["tf"] == tf and r["total"] >= 10]
        if not tf_results:
            log(f"\n  {tf}: No results with ≥10 trades")
            continue
        tf_results.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
        best = tf_results[0]
        log(f"\n  [{tf}] BEST: {best['strat']}")
        log(f"         SL={best['sl']*100:.1f}% TP={best['tp']*100:.1f}%")
        log(f"         Trades={best['total']} | Wins={best['wins']} | Losses={best['losses']}")
        log(f"         WIN RATE = {best['wr']*100:.1f}%")
        log(f"         EV/trade = {best['ev']*100:+.3f}%")

        # Show top 5 for this TF
        log(f"         Top 5:")
        for i, r in enumerate(tf_results[:5]):
            log(f"           #{i+1} {r['strat']} | SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}% | "
                f"{r['total']} trades | WR={r['wr']*100:.1f}% | EV={r['ev']*100:+.3f}%")

    # ── SAVE FULL RESULTS AS JSON ──────────────────────────────────────────────
    with open("mega_results.json", "w") as f:
        json.dump(sorted(all_results, key=lambda x: x["wr"], reverse=True), f, indent=2)

    ended = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"\n\nCompleted: {ended}")
    log(f"Total combinations tested: {len(all_results)}")
    log(f"Results saved to mega_results.txt and mega_results.json")

if __name__ == "__main__":
    main()
