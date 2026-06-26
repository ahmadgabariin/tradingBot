"""
Extra high-win-rate strategies to test alongside fast_backtest results.
Appends to mega_results.json and mega_results.txt.
"""
import json, time
from datetime import datetime
from fast_backtest import fetch, precompute, backtest, PAIRS, TFS, SL_TP, wlog as _wlog

OUT = "mega_results.txt"
OUTJ = "mega_results.json"

def wlog(msg):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg+"\n")
    print(msg)

# ── EXTRA STRATEGIES ──────────────────────────────────────────────────────────

def s_inside_bar_break(p, i):
    """Inside bar breakout — price breaks above mother bar after consolidation."""
    if i < 10: return False
    mother = p["h"][i-2]; mother_lo = p["l"][i-2]
    # Inside bar: previous candle completely inside mother
    inside = p["h"][i-1] < mother and p["l"][i-1] > mother_lo
    # Current candle breaks above mother bar high
    if not inside or p["c"][i] <= mother: return False
    return p["green"][i] and p["rsi"][p["rsi"].__class__ and "rsi" or "rsi"][i] < 72

def s_inside_bar_break_v2(p, i):
    """Inside bar: simpler version."""
    if i < 15: return False
    # Inside bar: candle[-2] range contains candle[-1] range
    m_hi = p["h"][i-2]; m_lo = p["l"][i-2]
    in_hi = p["h"][i-1]; in_lo = p["l"][i-1]
    if not (in_hi <= m_hi and in_lo >= m_lo): return False
    # Current breaks above and closes green
    if p["c"][i] <= m_hi: return False
    if not p["green"][i]: return False
    avg_vol = p["vol_avg"][i]
    if avg_vol > 0 and p["v"][i] < avg_vol * 0.8: return False
    rsi = p["rsi"][i]
    return 30 < rsi < 72

def s_two_bar_reversal(p, i):
    """Two-bar bullish reversal: strong red + strong green (engulfing + volume)."""
    if i < 20: return False
    prev = i-1
    # Previous: strong red candle (body > 60% of range)
    prev_rng = p["h"][prev] - p["l"][prev]
    if prev_rng == 0: return False
    prev_body = p["o"][prev] - p["c"][prev]  # red candle
    if prev_body < prev_rng * 0.5: return False
    if not (not p["green"][prev]): return False
    # Current: green engulfing
    if not p["green"][i]: return False
    if not (p["o"][i] <= p["c"][prev] and p["c"][i] >= p["o"][prev]): return False
    # Volume increasing
    if p["v"][i] < p["v"][prev] * 0.9: return False
    rsi = p["rsi"][i]
    return 25 < rsi < 65 and p["c"][i] > p["e50"][i] * 0.96

def s_ema_ribbon_align(p, i):
    """All EMAs (9,21,50,200) pointing up AND price above all of them."""
    if i < 205: return False
    # All stacked
    if not (p["c"][i] > p["e9"][i] > p["e21"][i] > p["e50"][i] > p["e200"][i]): return False
    # All EMAs pointing up (current > prev)
    if not (p["e9"][i] > p["e9"][i-1] and p["e21"][i] > p["e21"][i-1]
            and p["e50"][i] > p["e50"][i-1]): return False
    rsi = p["rsi"][i]
    return 40 < rsi < 72 and p["green"][i] and p["macd_hist"][i] > 0

def s_pullback_to_50(p, i):
    """Price pulls back to EMA50 in uptrend and bounces — classic retest."""
    if i < 55: return False
    if not (p["e9"][i] > p["e21"][i] > p["e50"][i]): return False
    # Price touched EMA50 zone in last 3 candles
    touched_50 = any(p["l"][i-k] <= p["e50"][i-k]*1.005 and p["c"][i-k] > p["e50"][i-k]*0.995
                     for k in range(0,3))
    if not touched_50: return False
    if not p["green"][i]: return False
    rsi = p["rsi"][i]
    return 30 < rsi < 65 and p["macd_hist"][i] > p["macd_hist"][i-1]

def s_momentum_burst(p, i):
    """Single large momentum candle with volume — institutions stepping in."""
    if i < 25: return False
    if not p["green"][i]: return False
    # Large body relative to recent ATR
    atr = p["atr"][i]
    if atr == 0: return False
    body = p["body"][i]
    if body < atr * 1.5: return False  # candle body must be > 1.5x ATR
    # Volume spike
    avg_vol = p["vol_avg"][i]
    if avg_vol > 0 and p["v"][i] < avg_vol * 2.0: return False
    # Not overbought
    rsi = p["rsi"][i]
    if rsi > 72: return False
    return p["c"][i] > p["e21"][i]

def s_bb_squeeze_long(p, i):
    """BB squeeze (bandwidth < threshold) then price moves up."""
    if i < 30: return False
    bw = (p["bb_hi"][i] - p["bb_lo"][i]) / p["bb_mid"][i] if p["bb_mid"][i] > 0 else 1
    # Need narrow bands (squeeze)
    if bw > 0.04: return False  # 4% bandwidth threshold
    # Price rising above midline
    if not (p["c"][i] > p["bb_mid"][i] and p["c"][i-1] <= p["bb_mid"][i-1]): return False
    if not p["green"][i]: return False
    return p["rsi"][i] < 68

def s_higher_highs_lows(p, i):
    """Classic trend structure: each swing high and low is higher than last."""
    if i < 20: return False
    # Check last 3 candle lows and highs are rising
    lows = [p["l"][i-k] for k in range(3, 0, -1)]
    highs = [p["h"][i-k] for k in range(3, 0, -1)]
    hh = highs[1] > highs[0] and highs[2] > highs[1]
    hl = lows[1] > lows[0] and lows[2] > lows[1]
    if not (hh and hl): return False
    if not p["green"][i]: return False
    rsi = p["rsi"][i]
    if rsi > 70: return False
    return p["e9"][i] > p["e21"][i] and p["v"][i] > p["vol_avg"][i] * 0.8

def s_doji_reversal(p, i):
    """Doji at support followed by bullish candle."""
    if i < 25: return False
    # Previous candle was doji (tiny body, significant wicks)
    prev = i-1
    prev_rng = p["c_rng"][prev]
    if prev_rng == 0: return False
    if p["body"][prev] > prev_rng * 0.15: return False  # must be small body
    # Current is strong green candle
    if not p["green"][i]: return False
    curr_rng = p["c_rng"][i]
    if curr_rng > 0 and p["body"][i] / curr_rng < 0.5: return False
    # Near support
    rsi = p["rsi"][i]
    return rsi < 55 and p["c"][i] > p["e50"][i] * 0.97

def s_ema_fan(p, i):
    """All short EMAs fanning out upward — early trend signal."""
    if i < 22: return False
    # EMA9 slope > EMA21 slope > EMA50 slope (all trending up, 9 fastest)
    slope9  = p["e9"][i]  - p["e9"][i-3]
    slope21 = p["e21"][i] - p["e21"][i-3]
    slope50 = p["e50"][i] - p["e50"][i-3]
    if not (slope9 > slope21 > slope50 > 0): return False
    if not p["green"][i]: return False
    rsi = p["rsi"][i]
    return 40 < rsi < 68 and p["macd_hist"][i] > 0

def s_range_expansion(p, i):
    """Candle range > 2x average ATR going upward — expansion move."""
    if i < 20: return False
    atr = p["atr"][i]
    if atr == 0: return False
    curr_range = p["c_rng"][i]
    if curr_range < atr * 2.0: return False
    if not p["green"][i]: return False
    if p["v"][i] < p["vol_avg"][i] * 1.5: return False
    rsi = p["rsi"][i]
    return rsi < 72 and p["c"][i] > p["e21"][i]

def s_double_bottom(p, i):
    """Simple double bottom: two similar lows with higher close between."""
    if i < 20: return False
    # Find two recent local lows
    recent_lo1 = None; recent_lo2 = None
    for k in range(3, 15):
        if i-k < 2: break
        if p["l"][i-k] < p["l"][i-k-1] and p["l"][i-k] < p["l"][i-k+1]:
            if recent_lo2 is None:
                recent_lo2 = (i-k, p["l"][i-k])
            elif recent_lo1 is None:
                recent_lo1 = (i-k, p["l"][i-k])
                break
    if not (recent_lo1 and recent_lo2): return False
    l1_price = recent_lo1[1]; l2_price = recent_lo2[1]
    # Two lows within 1.5% of each other
    if abs(l1_price - l2_price) / l1_price > 0.015: return False
    # Current price recovering above the lows
    if p["c"][i] <= l2_price * 1.005: return False
    if not p["green"][i]: return False
    rsi = p["rsi"][i]
    return rsi < 60 and p["c"][i] > p["e21"][i]

EXTRA_STRATS = {
    "Inside_Bar_Break":    s_inside_bar_break_v2,
    "Two_Bar_Reversal":    s_two_bar_reversal,
    "EMA_Ribbon_Align":    s_ema_ribbon_align,
    "Pullback_To_EMA50":   s_pullback_to_50,
    "Momentum_Burst":      s_momentum_burst,
    "BB_Squeeze_Long":     s_bb_squeeze_long,
    "Higher_Highs_Lows":   s_higher_highs_lows,
    "Doji_Reversal":       s_doji_reversal,
    "EMA_Fan":             s_ema_fan,
    "Range_Expansion":     s_range_expansion,
    "Double_Bottom":       s_double_bottom,
}

def main():
    wlog(f"\n\n{'='*80}")
    wlog(f"EXTRA STRATEGIES TEST — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    wlog(f"{'='*80}")
    wlog(f"Testing {len(EXTRA_STRATS)} extra strategies\n")

    # Load existing data or fetch
    wlog("Fetching data...")
    data = {}
    for tf in TFS:
        data[tf] = {}
        for pair in PAIRS:
            raw = fetch(pair, tf, 3000)
            data[tf][pair] = precompute(raw)
            time.sleep(0.2)
    wlog("Done.\n")

    # Load existing results
    try:
        with open(OUTJ) as f:
            existing = json.load(f)
    except: existing = []

    new_results = []
    for tf in TFS:
        for sname, sfn in EXTRA_STRATS.items():
            for sl, tp in SL_TP:
                wins = losses = 0; all_pnl = []; pair_res = {}
                for pair in PAIRS:
                    p = data[tf][pair]
                    w, l, tot, wr, ev = backtest(p, sfn, sl, tp)
                    wins += w; losses += l
                    all_pnl.extend([tp]*w + [-sl]*l)
                    pair_res[pair] = {"wins": w, "losses": l,
                                      "wr": w/(w+l) if (w+l)>0 else 0}
                total = wins + losses
                if total < 5: continue
                wr = wins/total
                ev = sum(all_pnl)/len(all_pnl) if all_pnl else 0
                r = {"tf": tf, "strat": sname, "sl": sl, "tp": tp,
                     "wins": wins, "losses": losses, "total": total,
                     "wr": wr, "ev": ev, "pair": pair_res}
                new_results.append(r)

    # Merge and re-rank
    all_results = existing + new_results
    all_results.sort(key=lambda x: (x["wr"], x.get("ev",0)), reverse=True)

    with open(OUTJ, "w") as f:
        json.dump(all_results, f, indent=2)

    wlog(f"\nExtra strategies added. Total results: {len(all_results)}")
    wlog("\nNEW TOP 20 (including extra strategies):")
    wlog(f"  {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
    wlog(f"  {'-'*70}")
    shown = set()
    count = 0
    for r in all_results:
        if r["total"] < 10: continue
        key = (r["tf"], r["strat"])
        if key in shown: continue
        shown.add(key)
        marker = " *" if r["wr"] >= 0.50 else ""
        wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
             f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%{marker}")
        count += 1
        if count >= 20: break

if __name__ == "__main__":
    main()
