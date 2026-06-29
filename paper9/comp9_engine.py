"""
Comp9Engine — extends CompEngine with:
  1. ATR dynamic SL/TP: sl = entry ± atr_sl_mult * ATR, tp = entry ± atr_tp_mult * ATR
  2. Trailing stop: each tick moves SL in favour of open LONG/SHORT trades
  3. Supertrend trailing: SL tracks the Supertrend support/resistance line
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from paper_shared.base_engine import CompEngine, POS_SIZE, LEVERAGE, _fetch_prices
from paper9.comp9_agents import calc_supertrend, ORIGINAL_5
from fast_backtest import STRATS

# short signal functions for original 5 (same as base_engine.py)
from paper_shared.base_engine import (
    _short_keltner, _short_adx, _short_macd_bb, _short_orb, _short_donchian,
)
_ORIG5_SHORT = {
    "The Surgeon": _short_macd_bb,
    "The Maniac":  _short_keltner,
    "The Hound":   _short_donchian,
    "The Oracle":  _short_adx,
    "The Comet":   _short_orb,
}

CAPITAL = 1_000.0


class Comp9Engine(CompEngine):


    def _open_trade(self, name, pair, price, side="LONG", p=None):
        cfg = self.AGENTS[name]

        # ATR dynamic SL/TP
        atr = None
        if p and "atr" in p and p["n"] > 2:
            atr = p["atr"][p["n"] - 2]

        if atr and atr > 0 and "atr_sl_mult" in cfg:
            sl_dist = cfg["atr_sl_mult"] * atr
            tp_dist = cfg["atr_tp_mult"] * atr
        else:
            # fallback to fixed pct
            sl_dist = price * cfg["sl"]
            tp_dist = price * cfg["tp"]

        sl_p = price - sl_dist if side == "LONG" else price + sl_dist
        tp_p = price + tp_dist if side == "LONG" else price - tp_dist

        # For Supertrend: set SL to the current Supertrend band
        st_sl = None
        if cfg.get("supertrend") and p:
            period = cfg.get("st_period", 10)
            mult   = cfg.get("st_mult", 3.0)
            trend, fu, fl = calc_supertrend(p, period=period, multiplier=mult)
            idx = p["n"] - 2
            if side == "LONG":
                st_sl = fl[idx]
            else:
                st_sl = fu[idx]
            if st_sl and st_sl > 0:
                sl_p = st_sl

        return {
            "id":       f"{name[:4].upper()}-{pair[:3]}-{side[0]}-{int(time.time()*1000)%100000}",
            "agent":    name, "agent_id": cfg["id"], "color": cfg["color"],
            "emoji":    cfg["emoji"],
            "pair":     pair, "side": side, "entry": price,
            "sl":       round(sl_p, 6), "tp": round(tp_p, 6),
            "size":     POS_SIZE, "qty": (POS_SIZE * LEVERAGE) / price,
            "open_at":  datetime.now(timezone.utc).isoformat(),
            "open_ts":  time.time(), "status": "OPEN", "pnl": 0.0, "result": None,
            "trailing": cfg.get("trailing", False),
            "supertrend": cfg.get("supertrend", False),
            "atr_sl_mult": cfg.get("atr_sl_mult"),
            "st_period": cfg.get("st_period", 10),
            "st_mult":   cfg.get("st_mult", 3.0),
        }

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
                idx = p["n"] - 2

                side = trade.get("side", "LONG")

                if trade.get("supertrend"):
                    # SL tracks the Supertrend band
                    period = trade.get("st_period", 10)
                    mult   = trade.get("st_mult", 3.0)
                    st_trend, fu, fl = calc_supertrend(p, period=period, multiplier=mult)

                    # If trend flipped against us, the tick loop will close via SL anyway;
                    # here we just update the band level
                    if side == "LONG":
                        new_sl = fl[idx]
                        if new_sl > trade["sl"] and new_sl < price:
                            trade["sl"] = round(new_sl, 6)
                    else:
                        new_sl = fu[idx]
                        if new_sl < trade["sl"] and new_sl > price:
                            trade["sl"] = round(new_sl, 6)

                else:
                    # ATR-based trailing
                    atr_mult = trade.get("atr_sl_mult") or cfg.get("atr_sl_mult", 2.0)
                    if "atr" not in p:
                        continue
                    atr = p["atr"][idx]
                    if not atr or atr <= 0:
                        continue

                    if side == "LONG":
                        new_sl = price - atr_mult * atr
                        if new_sl > trade["sl"]:
                            trade["sl"] = round(new_sl, 6)
                    else:
                        new_sl = price + atr_mult * atr
                        if new_sl < trade["sl"]:
                            trade["sl"] = round(new_sl, 6)

    def run_tick(self):
        try:
            prices = _fetch_prices()
            self.live_prices.update(prices)
        except Exception as e:
            print(f"  [{self.COMP_NAME}] price err: {e}")

        with self._lock:
            # Move trailing stops before close-check so they reflect the latest price
            self._update_trailing_stops()

            for name, cfg in self.AGENTS.items():
                bal      = self.agent_balances[name]
                open_pos = self.agent_open[name]

                # close positions
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

                # new signals
                direction = self.agent_direction.get(name, "BOTH")
                if len(self.agent_open[name]) < self.MAX_OPEN and bal > POS_SIZE:
                    sfn_long  = self.LONG_SIGNALS.get(name)
                    sfn_short = self.SHORT_SIGNALS.get(name)
                    # original 5 use STRATS for long, dedicated short fns
                    if name in ORIGINAL_5:
                        sfn_long  = STRATS.get(cfg["strategy"])
                        sfn_short = _ORIG5_SHORT.get(name)

                    for pair in self.PAIRS_LIST:
                        if len(self.agent_open[name]) >= self.MAX_OPEN:
                            break
                        price = self.live_prices.get(pair)
                        if not price:
                            continue
                        p = self._get_candles(pair, cfg["timeframe"])
                        if not p or p["n"] < 100:
                            continue
                        idx = p["n"] - 2

                        already_long  = any(t["pair"] == pair and t.get("side", "LONG") == "LONG"  for t in self.agent_open[name])
                        already_short = any(t["pair"] == pair and t.get("side", "LONG") == "SHORT" for t in self.agent_open[name])

                        long_sig = short_sig = False
                        if direction in ("LONG", "BOTH") and not already_long:
                            try: long_sig  = sfn_long(p, idx)  if sfn_long  else False
                            except: pass
                        if direction in ("SHORT", "BOTH") and not already_short:
                            try: short_sig = sfn_short(p, idx) if sfn_short else False
                            except: pass

                        if long_sig:
                            self.agent_open[name].append(self._open_trade(name, pair, price, "LONG", p=p))
                            self._save_state()
                        if short_sig and len(self.agent_open[name]) < self.MAX_OPEN:
                            self.agent_open[name].append(self._open_trade(name, pair, price, "SHORT", p=p))
                            self._save_state()

                # equity snapshot
                unrealized = sum(
                    t["qty"] * (self.live_prices.get(t["pair"], t["entry"]) - t["entry"])
                    if t.get("side", "LONG") == "LONG"
                    else t["qty"] * (t["entry"] - self.live_prices.get(t["pair"], t["entry"]))
                    for t in self.agent_open[name]
                )
                self.agent_equity[name].append(round(bal + unrealized, 2))

            self._save_state()
