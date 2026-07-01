"""
Signal logic for LighterBot — ported 1:1 from paper9/comp9_agents.py's
_liq_long/_liq_short (Liquidity Hunt) and _surgeon2_long/_surgeon2_short
(Surgeon v2). These are the EXACT functions comp10 uses (comp10 imports
LONG_SIGNALS_9/SHORT_SIGNALS_9 straight from paper9 — there's no separate
comp10 signal code). Data comes from lighterbot/data_feed.py, which precomputes
the same rsi/adx/vol_avg/green/s_hi/s_lo/atr fields as fast_backtest.precompute().
"""

# Same 10 pairs as paper9/paper11 (COMP9_PAIRS) — each agent scans all of them
# every tick, same as the paper-trading competitions.
PAIRS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "LINK", "DOT", "AVAX", "POL"]

AGENTS = {
    "Liquidity Hunt": {
        "timeframe": "1h",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "atr_trail",
        "description": "Stop sweep reversal — ATR trailing stop. Signal logic identical to comp9/comp10.",
    },
    "Surgeon v2": {
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "atr_trail",
        "description": "RSI reversal — ATR trailing stop. Signal logic identical to comp9/comp10.",
    },
}


# ── Liquidity Hunt — ported verbatim from paper9/comp9_agents.py:_liq_long/_liq_short ──
def long_liquidity_hunt(p, i):
    if i < 15 or "s_lo" not in p:
        return False
    swept = p["l"][i] < p["s_lo"][i] * 0.999
    rev   = p["c"][i] > p["s_lo"][i]
    wick  = (p["c"][i] - p["l"][i]) > (p["h"][i] - p["l"][i]) * 0.5
    return bool(swept and rev and wick and p["v"][i] > p["vol_avg"][i] * 1.4)


def short_liquidity_hunt(p, i):
    if i < 15 or "s_hi" not in p:
        return False
    swept = p["h"][i] > p["s_hi"][i] * 1.001
    rev   = p["c"][i] < p["s_hi"][i]
    wick  = (p["h"][i] - p["c"][i]) > (p["h"][i] - p["l"][i]) * 0.5
    return bool(swept and rev and wick and p["v"][i] > p["vol_avg"][i] * 1.4)


# ── Surgeon v2 — ported verbatim from paper9/comp9_agents.py:_surgeon2_long/_surgeon2_short ──
def long_surgeon_v2(p, i):
    if i < 50:
        return False
    return bool(p["rsi"][i] < 35 and p["rsi"][i] > p["rsi"][i-1]
                and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 15)


def short_surgeon_v2(p, i):
    if i < 50:
        return False
    return bool(p["rsi"][i] > 65 and p["rsi"][i] < p["rsi"][i-1]
                and not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 15)


LONG_SIGNALS = {
    "Liquidity Hunt": long_liquidity_hunt,
    "Surgeon v2":     long_surgeon_v2,
}
SHORT_SIGNALS = {
    "Liquidity Hunt": short_liquidity_hunt,
    "Surgeon v2":     short_surgeon_v2,
}
