"""
Comp11Engine — 4 exit modes per agent:
  atr_trail    — current: SL follows price via ATR distance (comp9 behaviour)
  chandelier   — SL anchored to highest-high/lowest-low since entry, then ATR below that peak
  parabolic    — Parabolic SAR (acceleration factor grows as trend extends)
  supertrend   — Supertrend band as SL (recalculated each candle)
  keltner_exit — EMA-based Keltner lower/upper band as SL (counter-trend safe)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from datetime import datetime, timezone
from paper_shared.base_engine import CompEngine, POS_SIZE, LEVERAGE, _fetch_prices
from paper11.comp11_agents import calc_supertrend, ORIGINAL_5_IN_11
from fast_backtest import STRATS

from paper_shared.base_engine import (
    _short_orb, _short_donchian,
)
_ORIG5_SHORT = {
    "The Hound": _short_donchian,
    "The Comet": _short_orb,
}

CAPITAL = 1_000.0


def _ema_arr(arr, n):
    out = np.zeros(len(arr))
    if len(arr) < n: return out
    out[n-1] = np.mean(arr[:n])
    k = 2/(n+1)
    for i in range(n, len(arr)):
        out[i] = arr[i]*k + out[i-1]*(1-k)
    return out


class Comp11Engine(CompEngine):

    def _open_trade(self, name, pair, price, side="LONG", p=None):
        cfg = self.AGENTS[name]

        atr = None
        if p and "atr" in p and p["n"] > 2:
            atr = p["atr"][p["n"] - 2]

        if atr and atr > 0 and "atr_sl_mult" in cfg:
            sl_dist = cfg["atr_sl_mult"] * atr
            tp_dist = cfg["atr_tp_mult"] * atr
        else:
            sl_dist = price * cfg["sl"]
            tp_dist = price * cfg["tp"]

        sl_p = price - sl_dist if side == "LONG" else price + sl_dist
        tp_p = price + tp_dist if side == "LONG" else price - tp_dist

        exit_mode = cfg.get("exit_mode", "atr_trail")

        # Supertrend: override initial SL with band
        if exit_mode == "supertrend" and p:
            period = cfg.get("st_period", 10)
            mult   = cfg.get("st_mult", 3.0)
            trend, fu, fl = calc_supertrend(p, period=period, multiplier=mult)
            idx = p["n"] - 2
            band = fl[idx] if side == "LONG" else fu[idx]
            if band and band > 0:
                sl_p = band

        # Keltner exit: override initial SL with Keltner band
        if exit_mode == "keltner_exit" and p:
            period = cfg.get("keltner_period", 20)
            mult   = cfg.get("keltner_mult", 1.5)
            closes = np.array(p["closes"][:p["n"]])
            atrs   = np.array(p["atr"][:p["n"]]) if "atr" in p else np.zeros(p["n"])
            ema    = _ema_arr(closes, period)
            idx    = p["n"] - 2
            if ema[idx] > 0:
                kl = ema[idx] - mult * atrs[idx]
                ku = ema[idx] + mult * atrs[idx]
                sl_p = kl if side == "LONG" else ku

        # Chandelier / Parabolic: initial SL is still ATR-based; extra state stored in trade
        trade = {
            "id":        f"{name[:4].upper()}-{pair[:3]}-{side[0]}-{int(time.time()*1000)%100000}",
            "agent":     name, "agent_id": cfg["id"], "color": cfg["color"],
            "emoji":     cfg["emoji"],
            "pair":      pair, "side": side, "entry": price,
            "sl":        round(sl_p, 6), "tp": round(tp_p, 6),
            "size":      POS_SIZE, "qty": (POS_SIZE * LEVERAGE) / price,
            "open_at":   datetime.now(timezone.utc).isoformat(),
            "open_ts":   time.time(), "status": "OPEN", "pnl": 0.0, "result": None,
            "trailing":  cfg.get("trailing", False),
            "exit_mode": exit_mode,
            "atr_sl_mult": cfg.get("atr_sl_mult"),
            # Chandelier state
            "peak_price": price,   # highest high (LONG) or lowest low (SHORT) since entry
            # Parabolic SAR state
            "sar":        sl_p,
            "sar_ep":     price,   # extreme point
            "sar_af":     cfg.get("sar_af_start", 0.02),
            "sar_af_step":cfg.get("sar_af_step",  0.02),
            "sar_af_max": cfg.get("sar_af_max",   0.2),
            # Supertrend state
            "st_period":  cfg.get("st_period", 10),
            "st_mult":    cfg.get("st_mult",   3.0),
            # Keltner state
            "keltner_period": cfg.get("keltner_period", 20),
            "keltner_mult":   cfg.get("keltner_mult",   1.5),
        }
        return trade

    def _update_trailing_stops(self):
        for name, cfg in self.AGENTS.items():
            for trade in self.agent_open[name]:
                if not trade.get("trailing"):
                    continue
                price = self.live_prices.get(trade["pair"])
                if not price:
                    continue

                p = self._get_candles(trade["pair"], cfg["timeframe"])
                if not p or p["n"] < 15:
                    continue
                idx  = p["n"] - 2
                side = trade.get("side", "LONG")
                mode = trade.get("exit_mode", "atr_trail")

                # ── ATR Trailing (original) ────────────────────────────────
                if mode == "atr_trail":
                    atr_mult = trade.get("atr_sl_mult") or cfg.get("atr_sl_mult", 2.0)
                    if "atr" not in p: continue
                    atr = p["atr"][idx]
                    if not atr or atr <= 0: continue
                    if side == "LONG":
                        new_sl = price - atr_mult * atr
                        if new_sl > trade["sl"]: trade["sl"] = round(new_sl, 6)
                    else:
                        new_sl = price + atr_mult * atr
                        if new_sl < trade["sl"]: trade["sl"] = round(new_sl, 6)

                # ── Chandelier Exit ────────────────────────────────────────
                elif mode == "chandelier":
                    atr_mult = trade.get("atr_sl_mult") or cfg.get("atr_sl_mult", 2.0)
                    if "atr" not in p: continue
                    atr = p["atr"][idx]
                    if not atr or atr <= 0: continue

                    if side == "LONG":
                        # Track highest high since entry
                        if price > trade.get("peak_price", price):
                            trade["peak_price"] = price
                        new_sl = trade["peak_price"] - atr_mult * atr
                        if new_sl > trade["sl"] and new_sl < price:
                            trade["sl"] = round(new_sl, 6)
                    else:
                        # Track lowest low since entry
                        if price < trade.get("peak_price", price):
                            trade["peak_price"] = price
                        new_sl = trade["peak_price"] + atr_mult * atr
                        if new_sl < trade["sl"] and new_sl > price:
                            trade["sl"] = round(new_sl, 6)

                # ── Parabolic SAR ──────────────────────────────────────────
                elif mode == "parabolic":
                    af      = trade.get("sar_af", 0.02)
                    af_step = trade.get("sar_af_step", 0.02)
                    af_max  = trade.get("sar_af_max", 0.2)
                    sar     = trade.get("sar", trade["sl"])
                    ep      = trade.get("sar_ep", trade["entry"])

                    if side == "LONG":
                        if price > ep:
                            ep = price
                            af = min(af + af_step, af_max)
                        new_sar = sar + af * (ep - sar)
                        new_sar = min(new_sar, price * 0.998)  # never above price
                        if new_sar > trade["sl"]:
                            trade["sl"] = round(new_sar, 6)
                    else:
                        if price < ep:
                            ep = price
                            af = min(af + af_step, af_max)
                        new_sar = sar - af * (sar - ep)
                        new_sar = max(new_sar, price * 1.002)  # never below price
                        if new_sar < trade["sl"]:
                            trade["sl"] = round(new_sar, 6)

                    trade["sar"]    = trade["sl"]
                    trade["sar_ep"] = ep
                    trade["sar_af"] = af

                # ── Supertrend ─────────────────────────────────────────────
                elif mode == "supertrend":
                    period = trade.get("st_period", 10)
                    mult   = trade.get("st_mult", 3.0)
                    st_trend, fu, fl = calc_supertrend(p, period=period, multiplier=mult)
                    if side == "LONG":
                        new_sl = fl[idx]
                        if new_sl and new_sl > trade["sl"] and new_sl < price:
                            trade["sl"] = round(new_sl, 6)
                    else:
                        new_sl = fu[idx]
                        if new_sl and new_sl < trade["sl"] and new_sl > price:
                            trade["sl"] = round(new_sl, 6)

                # ── Keltner Exit (Volatility Stop) ─────────────────────────
                elif mode == "keltner_exit":
                    period = trade.get("keltner_period", 20)
                    mult   = trade.get("keltner_mult", 1.5)
                    closes = np.array(p["closes"][:p["n"]])
                    atrs   = np.array(p["atr"][:p["n"]]) if "atr" in p else np.zeros(p["n"])
                    ema    = _ema_arr(closes, period)
                    if ema[idx] <= 0: continue
                    if side == "LONG":
                        new_sl = ema[idx] - mult * atrs[idx]
                        if new_sl > trade["sl"] and new_sl < price:
                            trade["sl"] = round(new_sl, 6)
                    else:
                        new_sl = ema[idx] + mult * atrs[idx]
                        if new_sl < trade["sl"] and new_sl > price:
                            trade["sl"] = round(new_sl, 6)

    def run_tick(self):
        try:
            prices = _fetch_prices()
            self.live_prices.update(prices)
        except Exception as e:
            print(f"  [{self.COMP_NAME}] price err: {e}")

        with self._lock:
            self._update_trailing_stops()

            for name, cfg in self.AGENTS.items():
                bal      = self.agent_balances[name]
                open_pos = self.agent_open[name]

                closed_tick = []
                for trade in open_pos:
                    price  = self.live_prices.get(trade["pair"], trade["entry"])
                    result = self._check_close(trade, price)
                    if result:
                        self._close_trade(trade, result)
                        bal += trade["pnl"]
                        self.agent_balances[name] = round(bal, 2)
                        self.agent_closed[name].append(trade)
                        self.all_trades.append(trade)
                        closed_tick.append(trade)
                self.agent_open[name] = [t for t in open_pos if t not in closed_tick]
                if closed_tick:
                    self._save_state()

                direction = self.agent_direction.get(name, "BOTH")
                if len(self.agent_open[name]) < self.MAX_OPEN and bal > POS_SIZE:
                    sfn_long  = self.LONG_SIGNALS.get(name)
                    sfn_short = self.SHORT_SIGNALS.get(name)
                    if name in ORIGINAL_5_IN_11:
                        sfn_long  = STRATS.get(cfg["strategy"])
                        sfn_short = _ORIG5_SHORT.get(name)

                    for pair in self.PAIRS_LIST:
                        if len(self.agent_open[name]) >= self.MAX_OPEN:
                            break
                        price = self.live_prices.get(pair)
                        if not price: continue
                        p = self._get_candles(pair, cfg["timeframe"])
                        if not p or p["n"] < 100: continue
                        idx = p["n"] - 2

                        already_long  = any(t["pair"]==pair and t.get("side","LONG")=="LONG"  for t in self.agent_open[name])
                        already_short = any(t["pair"]==pair and t.get("side","LONG")=="SHORT" for t in self.agent_open[name])

                        long_sig = short_sig = False
                        if direction in ("LONG","BOTH") and not already_long:
                            try: long_sig  = sfn_long(p, idx)  if sfn_long  else False
                            except: pass
                        if direction in ("SHORT","BOTH") and not already_short:
                            try: short_sig = sfn_short(p, idx) if sfn_short else False
                            except: pass

                        if long_sig:
                            self.agent_open[name].append(self._open_trade(name, pair, price, "LONG", p=p))
                            self._save_state()
                        if short_sig and len(self.agent_open[name]) < self.MAX_OPEN:
                            self.agent_open[name].append(self._open_trade(name, pair, price, "SHORT", p=p))
                            self._save_state()

                unrealized = sum(
                    t["qty"]*(self.live_prices.get(t["pair"], t["entry"])-t["entry"])
                    if t.get("side","LONG")=="LONG"
                    else t["qty"]*(t["entry"]-self.live_prices.get(t["pair"], t["entry"]))
                    for t in self.agent_open[name]
                )
                self.agent_equity[name].append(round(bal + unrealized, 2))

            self._save_state()
