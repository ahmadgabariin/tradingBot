"""
Standalone signal logic for LighterBot — ported from paper9/paper11 (Liquidity
Hunt + Surgeon v2). Copied, not imported, so this bot never depends on the
existing paper-trading project.
"""
import numpy as np

# Same 10 pairs as paper9/paper11 (COMP9_PAIRS) — each agent scans all of them
# every tick, same as the paper-trading competitions.
PAIRS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "LINK", "DOT", "AVAX", "POL"]

AGENTS = {
    "Liquidity Hunt": {
        "timeframe": "1h",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "chandelier",
        "description": "Stop sweep reversal — Chandelier exit anchors SL to the post-sweep peak.",
    },
    "Surgeon v2": {
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "chandelier",
        "description": "RSI reversal — Chandelier exit anchors SL to the spike top.",
    },
}


def _ema(arr, n):
    out = np.zeros(len(arr))
    if len(arr) < n:
        return out
    out[n-1] = np.mean(arr[:n])
    k = 2/(n+1)
    for i in range(n, len(arr)):
        out[i] = arr[i]*k + out[i-1]*(1-k)
    return out


def _rsi(closes, n=14):
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    if len(g) < n:
        return np.full(len(closes), np.nan)
    ag = np.convolve(g, np.ones(n)/n, mode='valid')
    al = np.convolve(l, np.ones(n)/n, mode='valid')
    rs = np.where(al == 0, 100.0, ag / (al + 1e-9))
    rsi = 100 - 100/(1+rs)
    return np.concatenate([np.full(n, np.nan), rsi])


# ── Liquidity Hunt ─────────────────────────────────────────────────────────
def long_liquidity_hunt(p, idx):
    c, l = p["closes"], p["lows"]
    if idx < 5:
        return False
    recent_low = np.min(l[idx-5:idx])
    swept = l[idx] < recent_low
    return bool(swept and c[idx] > c[idx-1] and c[idx] > recent_low)


def short_liquidity_hunt(p, idx):
    c, h = p["closes"], p["highs"]
    if idx < 5:
        return False
    recent_high = np.max(h[idx-5:idx])
    swept = h[idx] > recent_high
    return bool(swept and c[idx] < c[idx-1] and c[idx] < recent_high)


# ── Surgeon v2 (RSI reversal) ────────────────────────────────────────────────
def long_surgeon_v2(p, idx):
    rsi = _rsi(p["closes"])
    if idx < 1 or np.isnan(rsi[idx-1]) or np.isnan(rsi[idx]):
        return False
    return bool(rsi[idx-1] < 30 and rsi[idx] > 30)


def short_surgeon_v2(p, idx):
    rsi = _rsi(p["closes"])
    if idx < 1 or np.isnan(rsi[idx-1]) or np.isnan(rsi[idx]):
        return False
    return bool(rsi[idx-1] > 70 and rsi[idx] < 70)


LONG_SIGNALS = {
    "Liquidity Hunt": long_liquidity_hunt,
    "Surgeon v2":     long_surgeon_v2,
}
SHORT_SIGNALS = {
    "Liquidity Hunt": short_liquidity_hunt,
    "Surgeon v2":     short_surgeon_v2,
}
