"""
Signal logic for LighterBot — ported 1:1 from paper9/comp9_agents.py's
_liq_long/_liq_short (Liquidity Hunt) and _surgeon2_long/_surgeon2_short
(Surgeon v2), plus paper11/comp11_agents.py's _long_momentum/_short_momentum
(Momentum), _long_structure/_short_structure (The Structure), and
_long_meanrev/_short_meanrev (Mean Reversion). These are the EXACT functions
comp10/comp11 use — data comes from lighterbot/data_feed.py, which precomputes
the same rsi/adx/vol_avg/green/s_hi/s_lo/atr fields as fast_backtest.precompute().

Momentum/The Structure/Mean Reversion additionally need calc_supertrend/_ema/
_macd/_bb, duplicated here (not imported from paper11) to keep LighterBot a
fully self-contained package that never touches the paper-trading comps.
"""
import numpy as np

# Same 10 pairs as paper9/paper11 (COMP9_PAIRS) — each agent scans all of them
# every tick, same as the paper-trading competitions.
PAIRS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "LINK", "DOT", "AVAX", "POL"]

# Paper-trading stats below are a SNAPSHOT taken 2026-08-04 from the live,
# continuously-running paper comps — they drift day to day since those
# simulators never stop trading. Treat as "last checked" reference data, not
# a live-synced feed.
AGENTS = {
    # "Liquidity Hunt" (comp9/comp10's ATR-trailing version) was removed —
    # it was losing in both of its own source comps (comp9: -31.1%, comp10:
    # -25.7%, snapshot 2026-08-04). "The Liquidity Hunt" below (comp2's
    # fixed-SL/TP version, the same entry signal) is the one that actually
    # tested profitable and is kept.
    "Surgeon v2": {
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "atr_trail",
        "description": "RSI reversal — ATR trailing stop. Signal logic identical to comp9/comp10. "
                        "Paper record (comp9, snapshot 2026-08-04): +140.3% (+$1,402.82), 605 trades, max 3 at once. "
                        "Paper record (comp10): +162.6% (+$1,625.68), 737 trades, max 8 at once.",
    },
    "Momentum": {
        "timeframe": "15m",
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
        "exit_mode": "parabolic",
        "sar_af_start": 0.02, "sar_af_step": 0.02, "sar_af_max": 0.2,
        "description": "Momentum — Parabolic SAR accelerates on long runs, exits fast on flip. Signal logic identical to comp11. "
                        "Paper record (comp11, snapshot 2026-08-04): +628.7% (+$6,286.68), 7,939 trades, max 15 at once. "
                        "Single biggest number in the whole dataset, but only tested well in comp11 specifically — "
                        "lost money in the (unlimited-cap) comp6 and comp10 runs of the same signal, so treat the "
                        "size of this result with some caution rather than assuming it repeats.",
    },
    "The Structure": {
        "timeframe": "1h",
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0,
        "exit_mode": "supertrend",
        "st_period": 10, "st_mult": 3.0,
        "description": "Break of Structure — Supertrend band follows the whole new trend leg. Signal logic identical to comp11. "
                        "Paper record (comp11, snapshot 2026-08-04): +62.6% (+$626.32), 282 trades, max 13 at once.",
    },
    "Mean Reversion": {
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "keltner_exit",
        "keltner_period": 20, "keltner_mult": 1.5,
        "description": "BB fade — Keltner exit: EMA band, softer and wider, counter-trend safe. Signal logic identical to comp11. "
                        "Paper record (comp11, snapshot 2026-08-04): +314.1% (+$3,140.51), 2,360 trades, max 17 at once.",
    },
    "The Surgeon v2": {
        # A DIFFERENT agent from "Surgeon v2" above, despite the similar name
        # — "Surgeon v2" is ported from comp9/comp10 (RSI+volume+ADX filter,
        # ATR-trail exit). This one is comp11's own version of the same
        # display name (comp11 itself calls it "The Surgeon v2"): a plain
        # RSI cross with a chandelier exit. Both are kept as separate,
        # independently tradeable agents rather than one replacing the other
        # — the dashboard shows a green "comp11" origin badge next to this
        # one to keep them visually distinct despite the near-identical name.
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "exit_mode": "chandelier",
        "description": "RSI cross reversal — Chandelier exit anchored to the post-reversal spike peak. Signal logic identical to comp11's own 'The Surgeon v2'. "
                        "Paper record (comp11, snapshot 2026-08-04): +193.4% (+$1,934.21), 1,622 trades, max 12 at once.",
    },
    "The Liquidity Hunt": {
        # Uses the shared long_liquidity_hunt/short_liquidity_hunt signal
        # (same stop-sweep-reversal entry that the removed "Liquidity Hunt"
        # ATR-trailing agent used), but matches comp2's ORIGINAL exit: fixed
        # 1.2%/2.4% SL/TP with no trailing at all — the version comp2's
        # backtest actually proved profitable. The ATR-trailing redesign
        # that comp2 never tested was removed since it was losing in its own
        # source comps (comp9: -31.1%, comp10: -25.7%).
        "timeframe": "1h",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,  # unused placeholders — fixed_pct overrides both sl/tp below
        "exit_mode": "fixed_pct",
        "sl_pct": 1.2, "tp_pct": 2.4,
        "description": "Stop sweep reversal — fixed 1.2%/2.4% SL/TP, no trailing. Signal logic and exit identical to comp2's original. "
                        "Paper record (comp2, snapshot 2026-08-04): +105.0% (+$1,050.01), 124 trades, max 3 at once.",
    },
    "The Mean Reversion": {
        # A DIFFERENT, stricter signal from "Mean Reversion" above — that one
        # is comp11's plain BB-fade cross; this one requires RSI at an
        # extreme (28/72) AND a volume surge AND candle-color confirmation on
        # top of the BB touch, matching comp2/3/4/5/6/9/10's shared
        # implementation (paper_shared/base_engine.py). Fixed 2.5%/2.5%
        # SL/TP, no trailing — comp6's exact config. Profitable in ALL 7
        # comps it was tested in (comp2 through comp10, excluding comp11
        # which never ran this stricter version), with a much lower trade
        # count than comp11's looser one (24-197 trades vs comp11's 2,360).
        "timeframe": "15m",
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,  # unused placeholders — fixed_pct overrides both sl/tp below
        "exit_mode": "fixed_pct",
        "sl_pct": 2.5, "tp_pct": 2.5,
        "description": "BB fade with RSI/volume/candle confirmation — fixed 2.5%/2.5% SL/TP, no trailing. Signal and exit identical to comp6's original. "
                        "Paper record (comp6, snapshot 2026-08-06, unlimited cap): +125.0% (+$1,250.05), 142 trades, max 10 at once. "
                        "Profitable in all 7 comps tested (comp2 +43.8%, comp3 +37.5%, comp4 +25.0%, comp5 +87.5%, "
                        "comp6 +125.0%, comp9 +75.9%, comp10 +72.4%) — the most consistent record of any agent here.",
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


# ── Shared indicator helpers — ported verbatim from paper11/comp11_agents.py ──
def _ema(arr, n):
    out = np.zeros(len(arr))
    out[n-1] = np.mean(arr[:n])
    k = 2/(n+1)
    for i in range(n, len(arr)):
        out[i] = arr[i]*k + out[i-1]*(1-k)
    return out


def _macd(closes, fast=12, slow=26, sig=9):
    e1 = _ema(closes, fast); e2 = _ema(closes, slow); m = e1-e2; s = _ema(m, sig)
    return m, s


def _bb(closes, n=20, k=2.0):
    mid = np.array([np.mean(closes[i-n:i]) if i >= n else np.nan for i in range(len(closes))])
    std = np.array([np.std(closes[i-n:i])  if i >= n else np.nan for i in range(len(closes))])
    return mid+k*std, mid, mid-k*std


def calc_supertrend(p, period=10, multiplier=3.0):
    highs  = np.array(p["h"][:p["n"]])
    lows   = np.array(p["l"][:p["n"]])
    closes = np.array(p["c"][:p["n"]])
    trs = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    atr = np.zeros(len(closes))
    atr[1] = trs[0]
    for i in range(2, len(closes)):
        atr[i] = (atr[i-1] * (period-1) + trs[i-1]) / period
    hl2 = (highs + lows) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    fu = upper.copy(); fl = lower.copy()
    trend = np.ones(len(closes), dtype=int)
    for i in range(1, len(closes)):
        fu[i] = min(upper[i], fu[i-1]) if closes[i-1] > fu[i-1] else upper[i]
        fl[i] = max(lower[i], fl[i-1]) if closes[i-1] < fl[i-1] else lower[i]
        if trend[i-1] == 1:
            trend[i] = -1 if closes[i] < fl[i] else 1
        else:
            trend[i] = 1 if closes[i] > fu[i] else -1
    return trend, fu, fl


# ── Momentum — ported verbatim from paper11/comp11_agents.py:_long_momentum/_short_momentum ──
def long_momentum(p, idx):
    c = np.array(p["c"][:p["n"]]); e20 = _ema(c, 20); macd, sig = _macd(c)
    return bool(c[idx] > e20[idx] and macd[idx] > sig[idx] and macd[idx] > macd[idx-1])


def short_momentum(p, idx):
    c = np.array(p["c"][:p["n"]]); e20 = _ema(c, 20); macd, sig = _macd(c)
    return bool(c[idx] < e20[idx] and macd[idx] < sig[idx] and macd[idx] < macd[idx-1])


# ── The Structure — ported verbatim from paper11/comp11_agents.py:_long_structure/_short_structure ──
def long_structure(p, idx):
    c = np.array(p["c"][:p["n"]]); h = np.array(p["h"][:p["n"]])
    if idx < 20:
        return False
    return bool(c[idx] > np.max(h[idx-20:idx-1]) and c[idx] > c[idx-1] > c[idx-2])


def short_structure(p, idx):
    c = np.array(p["c"][:p["n"]]); l = np.array(p["l"][:p["n"]])
    if idx < 20:
        return False
    return bool(c[idx] < np.min(l[idx-20:idx-1]) and c[idx] < c[idx-1] < c[idx-2])


# ── Mean Reversion — ported verbatim from paper11/comp11_agents.py:_long_meanrev/_short_meanrev ──
def long_meanrev(p, idx):
    c = np.array(p["c"][:p["n"]]); ub, mb, lb = _bb(c)
    if np.isnan(lb[idx]):
        return False
    return bool(c[idx-1] < lb[idx-1] and c[idx] > lb[idx])


def short_meanrev(p, idx):
    c = np.array(p["c"][:p["n"]]); ub, mb, lb = _bb(c)
    if np.isnan(ub[idx]):
        return False
    return bool(c[idx-1] > ub[idx-1] and c[idx] < ub[idx])


# ── Mean Reversion (strict) — ported verbatim from paper_shared/base_engine.py's
# _meanrev_long/_meanrev_short (comp2/3/4/5/6/9/10's shared implementation) —
# a DIFFERENT, much stricter signal than "Mean Reversion" above (comp11's
# plain BB-fade cross, no RSI/volume/candle filter at all). This one requires
# price actually below/above the band AND RSI at an extreme (28/72, not just
# any crossing) AND a volume surge AND candle-color confirmation — profitable
# in all 7 comps it was tested in, with a much lower trade count than
# comp11's looser version.
def long_meanrev_strict(p, idx):
    if idx < 20:
        return False
    c = np.array(p["c"][:p["n"]]); ub, mb, lb = _bb(c)
    if np.isnan(lb[idx]):
        return False
    return bool(c[idx] < lb[idx] and p["rsi"][idx] < 28 and p["v"][idx] > p["vol_avg"][idx] * 1.3
                and (p["green"][idx] or c[idx] > p["l"][idx] * 1.005))


def short_meanrev_strict(p, idx):
    if idx < 20:
        return False
    c = np.array(p["c"][:p["n"]]); ub, mb, lb = _bb(c)
    if np.isnan(ub[idx]):
        return False
    return bool(c[idx] > ub[idx] and p["rsi"][idx] > 72 and p["v"][idx] > p["vol_avg"][idx] * 1.3
                and (not p["green"][idx] or c[idx] < p["h"][idx] * 0.995))


# ── Surgeon v2 (C11) — ported verbatim from paper11/comp11_agents.py:_long_rsi_oversold/_short_rsi_oversold ──
def long_surgeon_v2_c11(p, idx):
    if idx < 50:
        return False
    rsi = p["rsi"]
    return bool(rsi[idx-1] < 30 and rsi[idx] > 30)


def short_surgeon_v2_c11(p, idx):
    if idx < 50:
        return False
    rsi = p["rsi"]
    return bool(rsi[idx-1] > 70 and rsi[idx] < 70)


LONG_SIGNALS = {
    "Surgeon v2":     long_surgeon_v2,
    "Momentum":       long_momentum,
    "The Structure":  long_structure,
    "Mean Reversion": long_meanrev,
    "The Surgeon v2":    long_surgeon_v2_c11,
    "The Liquidity Hunt": long_liquidity_hunt,
    "The Mean Reversion": long_meanrev_strict,
}
SHORT_SIGNALS = {
    "Surgeon v2":     short_surgeon_v2,
    "Momentum":       short_momentum,
    "The Structure":  short_structure,
    "Mean Reversion": short_meanrev,
    "The Surgeon v2":    short_surgeon_v2_c11,
    "The Liquidity Hunt": short_liquidity_hunt,
    "The Mean Reversion": short_meanrev_strict,
}
