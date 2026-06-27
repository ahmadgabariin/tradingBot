"""
Base competition engine — parameterized by MAX_OPEN.
Used by comp3-6. Fetches candles from candle_server (localhost:8200) with Binance fallback.
"""
import sys, os, time, threading, requests, json
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute, STRATS
from paper2.competition2_agents import AGENTS, PAIRS

CAPITAL  = 1_000.0
POS_SIZE = 50.0
LEVERAGE = 50

ORIGINAL_5 = {"The Surgeon","The Maniac","The Hound","The Oracle","The Comet"}

# ── CANDLE FETCH ───────────────────────────────────────────────────────────────

def _fetch_raw(pair, tf, n=200):
    """Fetch from candle_server; fallback to Binance direct."""
    try:
        r = requests.get(f"http://localhost:8200/candles?pair={pair}&tf={tf}", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        pass
    r = requests.get(
        f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={n}",
        timeout=10)
    r.raise_for_status()
    raw = r.json()
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
        "n":     len(raw),
    }

def _fetch_prices():
    r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
    r.raise_for_status()
    return {item["symbol"]: float(item["price"]) for item in r.json() if item["symbol"] in PAIRS}

# ── EXTRA INDICATORS ──────────────────────────────────────────────────────────

def _calc_vwap(raw):
    n = len(raw["close"])
    result, cum_tp, cum_v, prev_day = [0.0]*n, 0.0, 0.0, -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["high"][i]+raw["low"][i]+raw["close"][i])/3
        cum_tp += tp * raw["vol"][i]; cum_v += raw["vol"][i]
        result[i] = cum_tp/cum_v if cum_v > 0 else tp
    return result

def _calc_vol_delta(raw, period=10):
    n = len(raw["close"])
    delta = [raw["vol"][i] if raw["close"][i] >= raw["open"][i] else -raw["vol"][i] for i in range(n)]
    result = [0.0]*n
    for i in range(n):
        s = max(0, i-period+1)
        result[i] = sum(delta[s:i+1])
    return result

def _calc_swing(raw, lookback=10):
    n = len(raw["close"])
    s_hi = [0.0]*n; s_lo = [0.0]*n
    for i in range(lookback, n):
        s_hi[i] = max(raw["high"][i-lookback:i])
        s_lo[i] = min(raw["low"][i-lookback:i])
    return s_hi, s_lo

# ── SIGNAL FUNCTIONS ──────────────────────────────────────────────────────────

def _short_keltner(p,i):
    if i<25: return False
    return p["c"][i]<p["bb_mid"][i]-2*p["atr"][i] and p["v"][i]>p["vol_avg"][i]*1.2 and not p["green"][i]

def _short_adx(p,i):
    if i<60: return False
    down=p["e9"][i]<p["e21"][i]<p["e50"][i] and p["c"][i]<p["e9"][i]
    if not down or p["adx"][i]<30 or p["macd_hist"][i]>=0: return False
    if not (30<p["rsi"][i]<70): return False
    return max(p["h"][max(0,i-5):i])>=p["e9"][i]*0.99 and not p["green"][i]

def _short_macd_bb(p,i):
    if i<35: return False
    cross=p["macd_hist"][i]<0 and p["macd_hist"][i-1]>=0
    near=(p["bb_hi"][i]-p["c"][i])/p["c"][i]*100<2.0
    return cross and near and p["rsi"][i]>40 and not p["green"][i]

def _short_orb(p,i):
    if i<15: return False
    lo=min(p["l"][i-6:i]); hi=max(p["h"][i-6:i])
    rng=(hi-lo)/lo*100 if lo>0 else 99
    return rng<1.5 and p["c"][i]<lo and p["v"][i]>p["vol_avg"][i]*1.2 and not p["green"][i]

def _short_donchian(p,i):
    if i<25: return False
    return p["c"][i]<p["don_lo"][i] and p["v"][i]>p["vol_avg"][i]*1.3 and p["rsi"][i]>22 and not p["green"][i]

def _vwap_long(p,i):
    if i<10 or "vwap" not in p: return False
    cross=p["c"][i-1]<p["vwap"][i-1] and p["c"][i]>p["vwap"][i]
    vol=p["v"][i]>p["vol_avg"][i]*1.5
    bp=sum(1 for j in range(max(0,i-3),i) if p["green"][j])
    return cross and vol and p["green"][i] and 35<p["rsi"][i]<65 and bp>=2

def _vwap_short(p,i):
    if i<10 or "vwap" not in p: return False
    cross=p["c"][i-1]>p["vwap"][i-1] and p["c"][i]<p["vwap"][i]
    vol=p["v"][i]>p["vol_avg"][i]*1.5
    sp=sum(1 for j in range(max(0,i-3),i) if not p["green"][j])
    return cross and vol and not p["green"][i] and 35<p["rsi"][i]<65 and sp>=2

def _meanrev_long(p,i):
    if i<20: return False
    return (p["c"][i]<p["bb_lo"][i] and p["rsi"][i]<28 and p["v"][i]>p["vol_avg"][i]*1.3
            and (p["green"][i] or p["c"][i]>p["l"][i]*1.005))

def _meanrev_short(p,i):
    if i<20: return False
    return (p["c"][i]>p["bb_hi"][i] and p["rsi"][i]>72 and p["v"][i]>p["vol_avg"][i]*1.3
            and (not p["green"][i] or p["c"][i]<p["h"][i]*0.995))

def _momentum_long(p,i):
    if i<60: return False
    al=p["e9"][i]>p["e21"][i]>p["e50"][i]; ab=p["c"][i]>p["e9"][i]
    mac=p["macd_hist"][i]>0 and p["macd_hist"][i]>p["macd_hist"][i-1]
    return al and ab and mac and 45<p["rsi"][i]<70 and p["c"][i]>p["c"][i-1]>p["c"][i-2]

def _momentum_short(p,i):
    if i<60: return False
    al=p["e9"][i]<p["e21"][i]<p["e50"][i]; ab=p["c"][i]<p["e9"][i]
    mac=p["macd_hist"][i]<0 and p["macd_hist"][i]<p["macd_hist"][i-1]
    return al and ab and mac and 30<p["rsi"][i]<55 and p["c"][i]<p["c"][i-1]<p["c"][i-2]

def _of_long(p,i):
    if i<15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i]>0 and p["c"][i]>p.get("vwap",[0]*200)[i]
            and p["v"][i]>p["vol_avg"][i]*1.2 and p["rsi"][i]<65
            and p["vol_delta"][i]>p["vol_delta"][i-1] and p["green"][i])

def _of_short(p,i):
    if i<15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i]<0 and p["c"][i]<p.get("vwap",[0]*200)[i]
            and p["v"][i]>p["vol_avg"][i]*1.2 and p["rsi"][i]>35
            and p["vol_delta"][i]<p["vol_delta"][i-1] and not p["green"][i])

def _liq_long(p,i):
    if i<15 or "s_lo" not in p: return False
    swept=p["l"][i]<p["s_lo"][i]*0.999; rev=p["c"][i]>p["s_lo"][i]
    wick=(p["c"][i]-p["l"][i])>(p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i]>p["vol_avg"][i]*1.4

def _liq_short(p,i):
    if i<15 or "s_hi" not in p: return False
    swept=p["h"][i]>p["s_hi"][i]*1.001; rev=p["c"][i]<p["s_hi"][i]
    wick=(p["h"][i]-p["c"][i])>(p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i]>p["vol_avg"][i]*1.4

def _vwap_mom_long(p,i):  return _vwap_long(p,i) and p["e9"][i]>p["e21"][i] and p["macd_hist"][i]>0
def _vwap_mom_short(p,i): return _vwap_short(p,i) and p["e9"][i]<p["e21"][i] and p["macd_hist"][i]<0
def _vwap_of_long(p,i):   return _vwap_long(p,i) and p.get("vol_delta",[0]*200)[i]>0
def _vwap_of_short(p,i):  return _vwap_short(p,i) and p.get("vol_delta",[0]*200)[i]<0
def _mr_of_long(p,i):     return _meanrev_long(p,i) and p.get("vol_delta",[0]*200)[i]>0
def _mr_of_short(p,i):    return _meanrev_short(p,i) and p.get("vol_delta",[0]*200)[i]<0
def _liq_mom_long(p,i):   return _liq_long(p,i) and p["e9"][i]>p["e21"][i]
def _liq_mom_short(p,i):  return _liq_short(p,i) and p["e9"][i]<p["e21"][i]
def _vwap_liq_long(p,i):  return _vwap_long(p,i) and _liq_long(p,i)
def _vwap_liq_short(p,i): return _vwap_short(p,i) and _liq_short(p,i)
def _vwap_of_bb_long(p,i):  return _vwap_long(p,i) and _of_long(p,i) and p["c"][i]>p["bb_mid"][i]
def _vwap_of_bb_short(p,i): return _vwap_short(p,i) and _of_short(p,i) and p["c"][i]<p["bb_mid"][i]
def _all_long(p,i):  return _vwap_long(p,i) and _of_long(p,i) and p["e9"][i]>p["e21"][i] and p["macd_hist"][i]>0
def _all_short(p,i): return _vwap_short(p,i) and _of_short(p,i) and p["e9"][i]<p["e21"][i] and p["macd_hist"][i]<0

LONG_SIGNALS = {
    "The Surgeon":None,"The Maniac":None,"The Hound":None,"The Oracle":None,"The Comet":None,
    "VWAP":_vwap_long,"Mean Reversion":_meanrev_long,"Momentum":_momentum_long,
    "Order Flow":_of_long,"Liquidity Hunt":_liq_long,"VWAP + Momentum":_vwap_mom_long,
    "VWAP + Order Flow":_vwap_of_long,"MeanRev + Order Flow":_mr_of_long,
    "Liq + Momentum":_liq_mom_long,"VWAP + Liq Hunt":_vwap_liq_long,
    "VWAP + OF + BB":_vwap_of_bb_long,"All Combined":_all_long,
}
SHORT_SIGNALS = {
    "The Surgeon":_short_macd_bb,"The Maniac":_short_keltner,"The Hound":_short_donchian,
    "The Oracle":_short_adx,"The Comet":_short_orb,"VWAP":_vwap_short,
    "Mean Reversion":_meanrev_short,"Momentum":_momentum_short,"Order Flow":_of_short,
    "Liquidity Hunt":_liq_short,"VWAP + Momentum":_vwap_mom_short,
    "VWAP + Order Flow":_vwap_of_short,"MeanRev + Order Flow":_mr_of_short,
    "Liq + Momentum":_liq_mom_short,"VWAP + Liq Hunt":_vwap_liq_short,
    "VWAP + OF + BB":_vwap_of_bb_short,"All Combined":_all_short,
}

# ── ENGINE CLASS ───────────────────────────────────────────────────────────────

class CompEngine:
    def __init__(self, save_file, max_open=3, comp_name="Competition"):
        self.SAVE_FILE  = save_file
        self.MAX_OPEN   = max_open
        self.COMP_NAME  = comp_name
        self.LEVERAGE   = LEVERAGE
        self.CAPITAL    = CAPITAL

        self.session_start    = None
        self.session_start_ts = None
        self.session_running  = False
        self.restart_count    = 0
        self.restart_log      = []
        self.live_prices      = {}

        self.agent_balances = {n: CAPITAL for n in AGENTS}
        self.agent_open     = {n: []      for n in AGENTS}
        self.agent_closed   = {n: []      for n in AGENTS}
        self.agent_equity   = {n: [CAPITAL] for n in AGENTS}
        self.agent_direction= {n: ("SHORT" if n in ORIGINAL_5 else "BOTH") for n in AGENTS}
        self.all_trades     = []

        self._candle_cache  = {}
        self._candle_ts     = {}
        self._lock          = threading.Lock()

        self._load_state()
        if self.session_start:
            self.resume_session()

    # ── CANDLES ───────────────────────────────────────────────────────────────

    def _get_candles(self, pair, tf):
        key = (pair, tf)
        now = time.time()
        if key not in self._candle_cache or now - self._candle_ts.get(key, 0) > 60:
            try:
                raw = _fetch_raw(pair, tf)
                if raw and raw.get("n", 0) > 0:
                    p = precompute(raw)
                    p["raw"]       = raw
                    p["vwap"]      = _calc_vwap(raw)
                    p["vol_delta"] = _calc_vol_delta(raw)
                    p["s_hi"], p["s_lo"] = _calc_swing(raw)
                    self._candle_cache[key] = p
                    self._candle_ts[key]    = now
            except Exception as e:
                print(f"  [{self.COMP_NAME}] candle err {pair} {tf}: {e}")
        return self._candle_cache.get(key)

    # ── PERSISTENCE ───────────────────────────────────────────────────────────

    def _save_state(self):
        try:
            data = {
                "session_start":    self.session_start,
                "session_start_ts": self.session_start_ts,
                "session_running":  self.session_running,
                "leverage":         self.LEVERAGE,
                "agent_direction":  self.agent_direction,
                "agent_balances":   self.agent_balances,
                "agent_open":       {n: self.agent_open[n]   for n in AGENTS},
                "agent_closed":     {n: self.agent_closed[n] for n in AGENTS},
                "agent_equity":     {n: self.agent_equity[n] for n in AGENTS},
                "all_trades":       self.all_trades,
                "restart_count":    self.restart_count,
                "restart_log":      self.restart_log,
                "saved_at":         time.time(),
            }
            tmp = self.SAVE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.SAVE_FILE)
        except Exception as e:
            print(f"  [{self.COMP_NAME}] save error: {e}")

    def _load_state(self):
        if not os.path.exists(self.SAVE_FILE):
            return
        try:
            with open(self.SAVE_FILE) as f:
                data = json.load(f)
            self.session_start    = data.get("session_start")
            self.session_start_ts = data.get("session_start_ts")
            self.session_running  = False
            self.LEVERAGE         = data.get("leverage", LEVERAGE)
            for name in AGENTS:
                _def = "SHORT" if name in ORIGINAL_5 else "BOTH"
                self.agent_direction[name] = data.get("agent_direction", {}).get(name, _def)
                self.agent_balances[name]  = data.get("agent_balances",  {}).get(name, CAPITAL)
                self.agent_open[name]      = data.get("agent_open",      {}).get(name, [])
                self.agent_closed[name]    = data.get("agent_closed",    {}).get(name, [])
                self.agent_equity[name]    = data.get("agent_equity",    {}).get(name, [CAPITAL])
            self.all_trades.clear()
            self.all_trades.extend(data.get("all_trades", []))
            self.restart_log.clear()
            self.restart_log.extend(data.get("restart_log", []))
            self.restart_count = data.get("restart_count", 0)
            print(f"[{self.COMP_NAME}] State restored — {len(self.all_trades)} trades")
        except Exception as e:
            print(f"  [{self.COMP_NAME}] load error: {e}")

    # ── TRADE LIFECYCLE ───────────────────────────────────────────────────────

    def _open_trade(self, name, pair, price, side="LONG"):
        cfg  = AGENTS[name]
        sl_p = price*(1-cfg["sl"]) if side=="LONG" else price*(1+cfg["sl"])
        tp_p = price*(1+cfg["tp"]) if side=="LONG" else price*(1-cfg["tp"])
        return {
            "id":       f"{name[:4].upper()}-{pair[:3]}-{side[0]}-{int(time.time()*1000)%100000}",
            "agent":    name, "agent_id": cfg["id"], "color": cfg["color"],
            "emoji":    cfg["emoji"],
            "pair":     pair, "side": side, "entry": price,
            "sl":       round(sl_p, 6), "tp": round(tp_p, 6),
            "size":     POS_SIZE, "qty": (POS_SIZE * LEVERAGE) / price,
            "open_at":  datetime.now(timezone.utc).isoformat(),
            "open_ts":  time.time(), "status": "OPEN", "pnl": 0.0, "result": None,
        }

    def _check_close(self, trade, price):
        side = trade.get("side", "LONG")
        if side=="LONG":
            if price >= trade["tp"]: return "TP"
            if price <= trade["sl"]: return "SL"
        else:
            if price <= trade["tp"]: return "TP"
            if price >= trade["sl"]: return "SL"
        return None

    def _close_trade(self, trade, result):
        price = trade["tp"] if result=="TP" else trade["sl"]
        side  = trade.get("side","LONG")
        trade["exit"]     = price
        trade["result"]   = result
        trade["status"]   = "CLOSED"
        trade["close_at"] = datetime.now(timezone.utc).isoformat()
        trade["close_ts"] = time.time()
        if side=="LONG":
            trade["pnl"] = round(trade["qty"]*(trade["tp"]-trade["entry"]),4) if result=="TP" else round(trade["qty"]*(trade["sl"]-trade["entry"]),4)
        else:
            trade["pnl"] = round(trade["qty"]*(trade["entry"]-trade["tp"]),4) if result=="TP" else round(trade["qty"]*(trade["entry"]-trade["sl"]),4)
        return trade

    # ── TICK ─────────────────────────────────────────────────────────────────

    def run_tick(self):
        try:
            prices = _fetch_prices()
            self.live_prices.update(prices)
        except Exception as e:
            print(f"  [{self.COMP_NAME}] price err: {e}")

        with self._lock:
            for name, cfg in AGENTS.items():
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
                    sfn_long  = LONG_SIGNALS.get(name)
                    sfn_short = SHORT_SIGNALS.get(name)
                    if name in ORIGINAL_5:
                        sfn_long = STRATS.get(cfg["strategy"])

                    for pair in PAIRS:
                        if len(self.agent_open[name]) >= self.MAX_OPEN: break
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
                            self.agent_open[name].append(self._open_trade(name, pair, price, "LONG"))
                            self._save_state()
                        if short_sig and len(self.agent_open[name]) < self.MAX_OPEN:
                            self.agent_open[name].append(self._open_trade(name, pair, price, "SHORT"))
                            self._save_state()

                # equity snapshot
                unrealized = sum(
                    t["qty"]*(self.live_prices.get(t["pair"],t["entry"])-t["entry"])
                    if t.get("side","LONG")=="LONG"
                    else t["qty"]*(t["entry"]-self.live_prices.get(t["pair"],t["entry"]))
                    for t in self.agent_open[name]
                )
                self.agent_equity[name].append(round(bal+unrealized, 2))

            self._save_state()

    # ── SESSION CONTROLS ──────────────────────────────────────────────────────

    def start_session(self):
        self.session_start    = datetime.now(timezone.utc).isoformat()
        self.session_start_ts = time.time()
        self.session_running  = True
        for name in AGENTS:
            self.agent_balances[name]  = CAPITAL
            self.agent_open[name]      = []
            self.agent_closed[name]    = []
            self.agent_equity[name]    = [CAPITAL]
            self.agent_direction[name] = "SHORT" if name in ORIGINAL_5 else "BOTH"
        self.all_trades.clear()
        self.restart_count = 0
        self.restart_log.clear()
        print(f"[{self.COMP_NAME}] Session started")

    def stop_session(self):
        self.session_running = False
        print(f"[{self.COMP_NAME}] Session stopped")

    def resume_session(self):
        self.session_running = True
        if not self.session_start_ts:
            self.session_start_ts = time.time()
        self.restart_count += 1
        self.restart_log.append(datetime.now(timezone.utc).isoformat())
        self._save_state()
        open_count = sum(len(self.agent_open[n]) for n in AGENTS)
        print(f"[{self.COMP_NAME}] Resumed (restart #{self.restart_count}) — {open_count} open positions")

    def set_agent_direction(self, name, direction):
        if name in self.agent_direction and direction in ("LONG","SHORT","BOTH"):
            self.agent_direction[name] = direction
            self._save_state()

    # ── STATS ─────────────────────────────────────────────────────────────────

    def get_agent_stats(self, name):
        closed = self.agent_closed[name]
        open_p = self.agent_open[name]
        wins   = [t for t in closed if t["result"]=="TP"]
        losses = [t for t in closed if t["result"]=="SL"]
        total  = len(closed)
        pnl    = sum(t["pnl"] for t in closed)
        bal    = self.agent_balances[name]

        unrealized = sum(
            t["qty"]*(self.live_prices.get(t["pair"],t["entry"])-t["entry"])
            if t.get("side","LONG")=="LONG"
            else t["qty"]*(t["entry"]-self.live_prices.get(t["pair"],t["entry"]))
            for t in open_p
        )
        equity = round(bal+unrealized, 2)

        open_detail = []
        for t in open_p:
            cur  = self.live_prices.get(t["pair"], t["entry"])
            upnl = t["qty"]*(cur-t["entry"]) if t.get("side","LONG")=="LONG" else t["qty"]*(t["entry"]-cur)
            open_detail.append({
                "pair": t["pair"], "side": t.get("side","LONG"), "entry": t["entry"],
                "tp": t["tp"], "sl": t["sl"], "qty": t["qty"], "open_at": t["open_at"],
                "cur_price": cur, "unrealized": round(upnl,2),
            })

        eq_hist = self.agent_equity[name]
        peak = CAPITAL; max_dd = 0.0; max_dd_pct = 0.0
        for eq in eq_hist:
            if eq > peak: peak = eq
            dd = peak - eq
            dd_pct = dd/peak*100 if peak>0 else 0
            if dd > max_dd: max_dd = dd; max_dd_pct = dd_pct

        durations = [t["close_ts"]-t["open_ts"] for t in closed if t.get("open_ts") and t.get("close_ts")]
        avg_dur = round(sum(durations)/len(durations)/60,1) if durations else 0

        cfg = AGENTS[name]
        return {
            "name": name, "id": cfg["id"], "emoji": cfg["emoji"], "color": cfg["color"],
            "strategy": cfg["strategy"], "timeframe": cfg["timeframe"],
            "sl_pct": cfg["sl"]*100, "tp_pct": cfg["tp"]*100,
            "description": cfg["description"],
            "balance": bal, "equity": equity,
            "return_pct": round((equity-CAPITAL)/CAPITAL*100,2),
            "trades": total, "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins)/total*100,1) if total>0 else 0,
            "pnl": round(pnl,2), "unrealized": round(unrealized,2),
            "avg_win":  round(sum(t["pnl"] for t in wins)/len(wins),2)   if wins   else 0,
            "avg_loss": round(sum(t["pnl"] for t in losses)/len(losses),2) if losses else 0,
            "open_count": len(open_p), "open_trades": open_detail,
            "direction": self.agent_direction.get(name,"BOTH"),
            "best_trade":  {"pair":max(closed,key=lambda t:t["pnl"])["pair"],"pnl":max(closed,key=lambda t:t["pnl"])["pnl"]} if closed else None,
            "worst_trade": {"pair":min(closed,key=lambda t:t["pnl"])["pair"],"pnl":min(closed,key=lambda t:t["pnl"])["pnl"]} if closed else None,
            "max_drawdown": round(max_dd,2), "max_drawdown_pct": round(max_dd_pct,2),
            "avg_duration_min": avg_dur,
            "personality": cfg.get("personality",{}),
            "bias":        cfg.get("bias","BOTH"),
        }

    def get_agent_detail(self, name):
        closed  = self.agent_closed[name]
        eq_hist = self.agent_equity[name]
        daily   = {}
        for t in closed:
            day = (t.get("close_at") or "")[:10]
            if day: daily[day] = round(daily.get(day,0)+t["pnl"],2)
        return {
            "equity_history": eq_hist[-500:],
            "closed_trades":  closed,
            "daily_pnl":      [{"date":d,"pnl":v} for d,v in sorted(daily.items())],
        }

    def get_pair_heatmap(self):
        hm = defaultdict(float); pt = defaultdict(int)
        for t in self.all_trades:
            sym = t["pair"].replace("USDT","")
            hm[sym] += t["pnl"]; pt[sym] += 1
        return [{"pair":p,"pnl":round(v,2),"trades":pt[p]} for p,v in sorted(hm.items(),key=lambda x:-x[1])]

    def get_key_moments(self):
        if not self.all_trades: return {}
        best  = max(self.all_trades, key=lambda t: t["pnl"])
        worst = min(self.all_trades, key=lambda t: t["pnl"])

        best_streak  = {"agent":"—","count":0}
        worst_streak = {"agent":"—","count":0}
        for name in AGENTS:
            ws = wc = ls = lc = 0
            for t in self.agent_closed[name]:
                if t["result"]=="TP": wc+=1; ls=0
                else:                  lc+=1; wc=0
                if wc>ws: ws=wc
                if lc>ls: ls=lc  # fix: was wrong var
            # fix: separate loops
            wc2 = lc2 = 0; ws2 = ls2 = 0
            for t in self.agent_closed[name]:
                if t["result"]=="TP": wc2+=1; lc2=0
                else:                  lc2+=1; wc2=0
                if wc2>ws2: ws2=wc2
                if lc2>ls2: ls2=lc2
            if ws2 > best_streak["count"]:  best_streak  = {"agent":name,"count":ws2}
            if ls2 > worst_streak["count"]: worst_streak = {"agent":name,"count":ls2}

        most_active = max(AGENTS, key=lambda n: len(self.agent_closed[n]))
        return {
            "biggest_win":        {"agent":best["agent"],  "pair":best["pair"],  "pnl":best["pnl"]},
            "biggest_loss":       {"agent":worst["agent"], "pair":worst["pair"], "pnl":worst["pnl"]},
            "longest_win_streak": best_streak,
            "longest_loss_streak":worst_streak,
            "most_active":        {"agent":most_active,"trades":len(self.agent_closed[most_active])},
            "total_pnl":          round(sum(t["pnl"] for t in self.all_trades),2),
            "total_trades":       len(self.all_trades),
        }
