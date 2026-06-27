"""
Competition 2 Engine — 17 agents live paper trading
5 original + 12 new strategies
"""
import sys, os, time, math, threading, requests, json
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute, STRATS
from paper2.competition2_agents import AGENTS, PAIRS

SAVE_FILE    = os.path.join(os.path.dirname(__file__), "competition2_state.json")
CAPITAL      = 1_000.0
POS_SIZE     = 50.0
LEVERAGE     = 50
MAX_OPEN     = 3
CANDLE_REFRESH = 60

session_start    = None
session_start_ts = None
session_running  = False
restart_count    = 0
restart_log      = []
live_prices      = {}
candle_cache     = {}
candle_ts        = {}

agent_balances  = {name: CAPITAL for name in AGENTS}
agent_open      = {name: [] for name in AGENTS}
agent_closed    = {name: [] for name in AGENTS}
agent_equity    = {name: [CAPITAL] for name in AGENTS}
_ORIGINAL_5 = {"The Surgeon","The Maniac","The Hound","The Oracle","The Comet"}
agent_direction = {name: ("SHORT" if name in _ORIGINAL_5 else "BOTH") for name in AGENTS}

all_trades = []
lock       = threading.Lock()

# ── CANDLE FETCH ──────────────────────────────────────────────────────────────

def fetch_candles(pair, tf, n=200):
    # prefer shared candle server, fallback to Binance direct
    try:
        r = requests.get(f"http://localhost:8200/candles?pair={pair}&tf={tf}", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        pass
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={n}", timeout=10)
        r.raise_for_status()
        raw = r.json()
        return {
            "open":  [float(c[1]) for c in raw],
            "high":  [float(c[2]) for c in raw],
            "low":   [float(c[3]) for c in raw],
            "close": [float(c[4]) for c in raw],
            "vol":   [float(c[5]) for c in raw],
            "ts":    [int(c[0])   for c in raw],
        }
    except Exception as e:
        print(f"  candle err {pair} {tf}: {e}"); return None

def get_candles(pair, tf):
    key = (pair, tf)
    now = time.time()
    if key not in candle_cache or now - candle_ts.get(key, 0) > CANDLE_REFRESH:
        raw = fetch_candles(pair, tf)
        if raw:
            p = precompute(raw)
            # attach extra indicators needed by new strategies
            p["raw"]       = raw
            p["vwap"]      = _calc_vwap(raw)
            p["vol_delta"] = _calc_vol_delta(raw)
            p["s_hi"], p["s_lo"] = _calc_swing(raw)
            candle_cache[key] = p
            candle_ts[key]    = now
    return candle_cache.get(key)

# ── EXTRA INDICATORS ──────────────────────────────────────────────────────────

def _calc_vwap(raw):
    n = len(raw["close"])
    result = [0.0]*n
    cum_tp = cum_v = 0.0
    prev_day = -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["high"][i]+raw["low"][i]+raw["close"][i])/3
        cum_tp += tp * raw["vol"][i]
        cum_v  += raw["vol"][i]
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

# ── PRICE FETCH ───────────────────────────────────────────────────────────────

def fetch_prices():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
        r.raise_for_status()
        for item in r.json():
            if item["symbol"] in PAIRS:
                live_prices[item["symbol"]] = float(item["price"])
    except Exception as e:
        print(f"  price err: {e}")

# ── ORIGINAL 5 AGENT SHORT SIGNALS ────────────────────────────────────────────

def _short_keltner(p, i):
    if i < 25: return False
    kc_lower = p["bb_mid"][i] - 2*p["atr"][i]
    return p["c"][i] < kc_lower and p["v"][i] > p["vol_avg"][i]*1.2 and not p["green"][i]

def _short_adx(p, i):
    if i < 60: return False
    down = p["e9"][i] < p["e21"][i] < p["e50"][i] and p["c"][i] < p["e9"][i]
    if not down or p["adx"][i] < 30 or p["macd_hist"][i] >= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    return max(p["h"][max(0,i-5):i]) >= p["e9"][i]*0.99 and not p["green"][i]

def _short_macd_bb(p, i):
    if i < 35: return False
    cross = p["macd_hist"][i] < 0 and p["macd_hist"][i-1] >= 0
    near  = (p["bb_hi"][i]-p["c"][i])/p["c"][i]*100 < 2.0
    return cross and near and p["rsi"][i] > 40 and not p["green"][i]

def _short_orb(p, i):
    if i < 15: return False
    lo = min(p["l"][i-6:i]); hi = max(p["h"][i-6:i])
    rng = (hi-lo)/lo*100 if lo > 0 else 99
    return rng < 1.5 and p["c"][i] < lo and p["v"][i] > p["vol_avg"][i]*1.2 and not p["green"][i]

def _short_donchian(p, i):
    if i < 25: return False
    return p["c"][i] < p["don_lo"][i] and p["v"][i] > p["vol_avg"][i]*1.3 and p["rsi"][i] > 22 and not p["green"][i]

# ── NEW 12 STRATEGY SIGNALS ───────────────────────────────────────────────────

def _vwap_long(p, i):
    if i < 10 or "vwap" not in p: return False
    cross = p["c"][i-1] < p["vwap"][i-1] and p["c"][i] > p["vwap"][i]
    vol   = p["v"][i] > p["vol_avg"][i]*1.5
    bp    = sum(1 for j in range(max(0,i-3),i) if p["green"][j])
    return cross and vol and p["green"][i] and 35 < p["rsi"][i] < 65 and bp >= 2

def _vwap_short(p, i):
    if i < 10 or "vwap" not in p: return False
    cross = p["c"][i-1] > p["vwap"][i-1] and p["c"][i] < p["vwap"][i]
    vol   = p["v"][i] > p["vol_avg"][i]*1.5
    sp    = sum(1 for j in range(max(0,i-3),i) if not p["green"][j])
    return cross and vol and not p["green"][i] and 35 < p["rsi"][i] < 65 and sp >= 2

def _meanrev_long(p, i):
    if i < 20: return False
    return (p["c"][i] < p["bb_lo"][i] and p["rsi"][i] < 28
            and p["v"][i] > p["vol_avg"][i]*1.3
            and (p["green"][i] or p["c"][i] > p["l"][i]*1.005))

def _meanrev_short(p, i):
    if i < 20: return False
    return (p["c"][i] > p["bb_hi"][i] and p["rsi"][i] > 72
            and p["v"][i] > p["vol_avg"][i]*1.3
            and (not p["green"][i] or p["c"][i] < p["h"][i]*0.995))

def _momentum_long(p, i):
    if i < 60: return False
    al  = p["e9"][i] > p["e21"][i] > p["e50"][i]
    ab  = p["c"][i] > p["e9"][i]
    mac = p["macd_hist"][i] > 0 and p["macd_hist"][i] > p["macd_hist"][i-1]
    acc = p["c"][i] > p["c"][i-1] > p["c"][i-2]
    return al and ab and mac and 45 < p["rsi"][i] < 70 and acc

def _momentum_short(p, i):
    if i < 60: return False
    al  = p["e9"][i] < p["e21"][i] < p["e50"][i]
    ab  = p["c"][i] < p["e9"][i]
    mac = p["macd_hist"][i] < 0 and p["macd_hist"][i] < p["macd_hist"][i-1]
    dec = p["c"][i] < p["c"][i-1] < p["c"][i-2]
    return al and ab and mac and 30 < p["rsi"][i] < 55 and dec

def _of_long(p, i):
    if i < 15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i] > 0 and p["c"][i] > p.get("vwap",[0]*200)[i]
            and p["v"][i] > p["vol_avg"][i]*1.2 and p["rsi"][i] < 65
            and p["vol_delta"][i] > p["vol_delta"][i-1] and p["green"][i])

def _of_short(p, i):
    if i < 15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i] < 0 and p["c"][i] < p.get("vwap",[0]*200)[i]
            and p["v"][i] > p["vol_avg"][i]*1.2 and p["rsi"][i] > 35
            and p["vol_delta"][i] < p["vol_delta"][i-1] and not p["green"][i])

def _liq_long(p, i):
    if i < 15 or "s_lo" not in p: return False
    swept = p["l"][i] < p["s_lo"][i]*0.999
    rev   = p["c"][i] > p["s_lo"][i]
    wick  = (p["c"][i]-p["l"][i]) > (p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i] > p["vol_avg"][i]*1.4

def _liq_short(p, i):
    if i < 15 or "s_hi" not in p: return False
    swept = p["h"][i] > p["s_hi"][i]*1.001
    rev   = p["c"][i] < p["s_hi"][i]
    wick  = (p["h"][i]-p["c"][i]) > (p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i] > p["vol_avg"][i]*1.4

def _vwap_mom_long(p, i):
    return _vwap_long(p,i) and p["e9"][i] > p["e21"][i] and p["macd_hist"][i] > 0

def _vwap_mom_short(p, i):
    return _vwap_short(p,i) and p["e9"][i] < p["e21"][i] and p["macd_hist"][i] < 0

def _vwap_of_long(p, i):
    return _vwap_long(p,i) and p.get("vol_delta",[0]*200)[i] > 0

def _vwap_of_short(p, i):
    return _vwap_short(p,i) and p.get("vol_delta",[0]*200)[i] < 0

def _mr_of_long(p, i):
    return _meanrev_long(p,i) and p.get("vol_delta",[0]*200)[i] > 0

def _mr_of_short(p, i):
    return _meanrev_short(p,i) and p.get("vol_delta",[0]*200)[i] < 0

def _liq_mom_long(p, i):
    return _liq_long(p,i) and p["e9"][i] > p["e21"][i]

def _liq_mom_short(p, i):
    return _liq_short(p,i) and p["e9"][i] < p["e21"][i]

def _vwap_liq_long(p, i):
    return _vwap_long(p,i) and _liq_long(p,i)

def _vwap_liq_short(p, i):
    return _vwap_short(p,i) and _liq_short(p,i)

def _vwap_of_bb_long(p, i):
    return _vwap_long(p,i) and _of_long(p,i) and p["c"][i] > p["bb_mid"][i]

def _vwap_of_bb_short(p, i):
    return _vwap_short(p,i) and _of_short(p,i) and p["c"][i] < p["bb_mid"][i]

def _all_long(p, i):
    return _vwap_long(p,i) and _of_long(p,i) and p["e9"][i] > p["e21"][i] and p["macd_hist"][i] > 0

def _all_short(p, i):
    return _vwap_short(p,i) and _of_short(p,i) and p["e9"][i] < p["e21"][i] and p["macd_hist"][i] < 0

# ── SIGNAL MAP ────────────────────────────────────────────────────────────────

LONG_SIGNALS = {
    # original 5 use STRATS from fast_backtest (set in check_signals)
    "The Surgeon":         None,
    "The Maniac":          None,
    "The Hound":           None,
    "The Oracle":          None,
    "The Comet":           None,
    # new 12
    "VWAP":                _vwap_long,
    "Mean Reversion":      _meanrev_long,
    "Momentum":            _momentum_long,
    "Order Flow":          _of_long,
    "Liquidity Hunt":      _liq_long,
    "VWAP + Momentum":     _vwap_mom_long,
    "VWAP + Order Flow":   _vwap_of_long,
    "MeanRev + Order Flow":_mr_of_long,
    "Liq + Momentum":      _liq_mom_long,
    "VWAP + Liq Hunt":     _vwap_liq_long,
    "VWAP + OF + BB":      _vwap_of_bb_long,
    "All Combined":        _all_long,
}

SHORT_SIGNALS = {
    "The Surgeon":         _short_macd_bb,
    "The Maniac":          _short_keltner,
    "The Hound":           _short_donchian,
    "The Oracle":          _short_adx,
    "The Comet":           _short_orb,
    "VWAP":                _vwap_short,
    "Mean Reversion":      _meanrev_short,
    "Momentum":            _momentum_short,
    "Order Flow":          _of_short,
    "Liquidity Hunt":      _liq_short,
    "VWAP + Momentum":     _vwap_mom_short,
    "VWAP + Order Flow":   _vwap_of_short,
    "MeanRev + Order Flow":_mr_of_short,
    "Liq + Momentum":      _liq_mom_short,
    "VWAP + Liq Hunt":     _vwap_liq_short,
    "VWAP + OF + BB":      _vwap_of_bb_short,
    "All Combined":        _all_short,
}

# ── STATE PERSISTENCE ─────────────────────────────────────────────────────────

def save_state():
    try:
        data = {
            "session_start":    session_start,
            "session_start_ts": session_start_ts,
            "session_running":  session_running,
            "leverage":         LEVERAGE,
            "agent_direction":  agent_direction,
            "agent_balances":   agent_balances,
            "agent_open":       {n: agent_open[n]   for n in agent_open},
            "agent_closed":     {n: agent_closed[n] for n in agent_closed},
            "agent_equity":     {n: agent_equity[n] for n in agent_equity},
            "all_trades":       all_trades,
            "restart_count":    restart_count,
            "restart_log":      restart_log,
            "saved_at":         time.time(),
        }
        tmp = SAVE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, SAVE_FILE)
    except Exception as e:
        print(f"[Save2 error] {e}")

def load_state():
    global session_start, session_start_ts, session_running, LEVERAGE
    if not os.path.exists(SAVE_FILE):
        return
    try:
        with open(SAVE_FILE) as f:
            data = json.load(f)
        session_start    = data.get("session_start")
        session_start_ts = data.get("session_start_ts")
        session_running  = False
        LEVERAGE         = data.get("leverage", LEVERAGE)
        for name in AGENTS:
            _default_dir = "SHORT" if name in _ORIGINAL_5 else "BOTH"
            agent_direction[name] = data.get("agent_direction", {}).get(name, _default_dir)
            agent_balances[name]  = data.get("agent_balances", {}).get(name, CAPITAL)
            agent_open[name]      = data.get("agent_open",    {}).get(name, [])
            agent_closed[name]    = data.get("agent_closed",  {}).get(name, [])
            agent_equity[name]    = data.get("agent_equity",  {}).get(name, [CAPITAL])
        all_trades.clear()
        all_trades.extend(data.get("all_trades", []))
        restart_log.clear()
        restart_log.extend(data.get("restart_log", []))
        global restart_count
        restart_count = data.get("restart_count", 0)
        print(f"[Competition2] State restored — {len(all_trades)} trades")
    except Exception as e:
        print(f"[Load2 error] {e}")

# ── TRADE LIFECYCLE ───────────────────────────────────────────────────────────

def open_trade(agent_name, pair, price, side="LONG"):
    cfg  = AGENTS[agent_name]
    sl_p = price*(1-cfg["sl"]) if side=="LONG" else price*(1+cfg["sl"])
    tp_p = price*(1+cfg["tp"]) if side=="LONG" else price*(1-cfg["tp"])
    return {
        "id":       f"{agent_name[:4].upper()}-{pair[:3]}-{side[0]}-{int(time.time()*1000)%100000}",
        "agent":    agent_name,
        "agent_id": cfg["id"],
        "color":    cfg["color"],
        "pair":     pair,
        "side":     side,
        "entry":    price,
        "sl":       round(sl_p, 6),
        "tp":       round(tp_p, 6),
        "size":     POS_SIZE,
        "qty":      (POS_SIZE * LEVERAGE) / price,
        "open_at":  datetime.now(timezone.utc).isoformat(),
        "open_ts":  time.time(),
        "status":   "OPEN",
        "pnl":      0.0,
        "result":   None,
    }

def check_close(trade, price):
    side = trade.get("side", "LONG")
    if side == "LONG":
        if price >= trade["tp"]: return "TP"
        if price <= trade["sl"]: return "SL"
    else:
        if price <= trade["tp"]: return "TP"
        if price >= trade["sl"]: return "SL"
    return None

def close_trade(trade, price, result):
    trade["exit"]     = price
    trade["result"]   = result
    trade["status"]   = "CLOSED"
    trade["close_at"] = datetime.now(timezone.utc).isoformat()
    trade["close_ts"] = time.time()
    side = trade.get("side", "LONG")
    if side == "LONG":
        trade["pnl"] = round(trade["qty"]*(trade["tp"]-trade["entry"]),4) if result=="TP" else round(trade["qty"]*(trade["sl"]-trade["entry"]),4)
    else:
        trade["pnl"] = round(trade["qty"]*(trade["entry"]-trade["tp"]),4) if result=="TP" else round(trade["qty"]*(trade["entry"]-trade["sl"]),4)
    return trade

# ── MAIN TICK ─────────────────────────────────────────────────────────────────

def run_tick():
    fetch_prices()
    with lock:
        for agent_name, cfg in AGENTS.items():
            bal      = agent_balances[agent_name]
            open_pos = agent_open[agent_name]

            # close positions
            closed_tick = []
            for trade in open_pos:
                price = live_prices.get(trade["pair"], trade["entry"])
                result = check_close(trade, price)
                if result:
                    close_trade(trade, trade["tp"] if result=="TP" else trade["sl"], result)
                    bal += trade["pnl"]
                    agent_balances[agent_name] = round(bal, 2)
                    agent_closed[agent_name].append(trade)
                    all_trades.append(trade)
                    closed_tick.append(trade)
            agent_open[agent_name] = [t for t in open_pos if t not in closed_tick]
            if closed_tick: save_state()

            # new signals
            direction = agent_direction.get(agent_name, "BOTH")
            if len(agent_open[agent_name]) < MAX_OPEN and bal > POS_SIZE:
                sfn_long  = LONG_SIGNALS.get(agent_name)
                sfn_short = SHORT_SIGNALS.get(agent_name)
                # original 5 use STRATS
                if agent_name in ("The Surgeon","The Maniac","The Hound","The Oracle","The Comet"):
                    sfn_long = STRATS.get(cfg["strategy"])

                for pair in PAIRS:
                    if len(agent_open[agent_name]) >= MAX_OPEN: break
                    price = live_prices.get(pair)
                    if not price: continue
                    p = get_candles(pair, cfg["timeframe"])
                    if not p or p["n"] < 100: continue
                    idx = p["n"] - 2

                    already_long  = any(t["pair"]==pair and t.get("side","LONG")=="LONG"  for t in agent_open[agent_name])
                    already_short = any(t["pair"]==pair and t.get("side","LONG")=="SHORT" for t in agent_open[agent_name])

                    long_sig = short_sig = False
                    if direction in ("LONG","BOTH") and not already_long:
                        try: long_sig  = sfn_long(p, idx)  if sfn_long  else False
                        except: pass
                    if direction in ("SHORT","BOTH") and not already_short:
                        try: short_sig = sfn_short(p, idx) if sfn_short else False
                        except: pass

                    if long_sig:
                        agent_open[agent_name].append(open_trade(agent_name, pair, price, "LONG"))
                        save_state()
                    if short_sig and len(agent_open[agent_name]) < MAX_OPEN:
                        agent_open[agent_name].append(open_trade(agent_name, pair, price, "SHORT"))
                        save_state()

            # equity snapshot
            unrealized = sum(
                t["qty"]*(live_prices.get(t["pair"],t["entry"])-t["entry"])
                if t.get("side","LONG")=="LONG"
                else t["qty"]*(t["entry"]-live_prices.get(t["pair"],t["entry"]))
                for t in agent_open[agent_name]
            )
            agent_equity[agent_name].append(round(bal+unrealized, 2))

        save_state()

# ── SESSION CONTROLS ──────────────────────────────────────────────────────────

def start_session():
    global session_start, session_start_ts, session_running
    session_start    = datetime.now(timezone.utc).isoformat()
    session_start_ts = time.time()
    session_running  = True
    for name in AGENTS:
        agent_balances[name]  = CAPITAL
        agent_open[name]      = []
        agent_closed[name]    = []
        agent_equity[name]    = [CAPITAL]
        agent_direction[name] = "SHORT" if name in _ORIGINAL_5 else "BOTH"
    all_trades.clear()
    print(f"[Competition2] Session started at {session_start}")

def stop_session():
    global session_running
    session_running = False
    print("[Competition2] Session stopped")

def resume_session():
    global session_running, session_start_ts, restart_count
    session_running = True
    if not session_start_ts:
        session_start_ts = time.time()
    restart_count += 1
    restart_log.append(datetime.now(timezone.utc).isoformat())
    save_state()
    print(f"[Competition2] Resumed (restart #{restart_count}) — {sum(len(agent_open[n]) for n in AGENTS)} open positions")

def set_agent_direction(agent_name, direction):
    if agent_name in agent_direction and direction in ("LONG","SHORT","BOTH"):
        agent_direction[agent_name] = direction
        save_state()

# ── STATS ─────────────────────────────────────────────────────────────────────

def get_agent_stats(agent_name):
    closed = agent_closed[agent_name]
    open_p = agent_open[agent_name]
    wins   = [t for t in closed if t["result"]=="TP"]
    losses = [t for t in closed if t["result"]=="SL"]
    total  = len(closed)
    wr     = round(len(wins)/total*100,1) if total > 0 else 0
    pnl    = sum(t["pnl"] for t in closed)
    bal    = agent_balances[agent_name]

    unrealized = sum(
        t["qty"]*(live_prices.get(t["pair"],t["entry"])-t["entry"])
        if t.get("side","LONG")=="LONG"
        else t["qty"]*(t["entry"]-live_prices.get(t["pair"],t["entry"]))
        for t in open_p
    )
    equity = round(bal+unrealized, 2)
    ret    = round((equity-CAPITAL)/CAPITAL*100, 2)
    avg_win  = round(sum(t["pnl"] for t in wins)/len(wins),2)   if wins   else 0
    avg_loss = round(sum(t["pnl"] for t in losses)/len(losses),2) if losses else 0
    best  = max(closed, key=lambda t: t["pnl"], default=None)
    worst = min(closed, key=lambda t: t["pnl"], default=None)

    open_detail = []
    for t in open_p:
        cur  = live_prices.get(t["pair"], t["entry"])
        upnl = t["qty"]*(cur-t["entry"]) if t.get("side","LONG")=="LONG" else t["qty"]*(t["entry"]-cur)
        open_detail.append({
            "pair": t["pair"], "side": t.get("side","LONG"),
            "entry": t["entry"], "tp": t["tp"], "sl": t["sl"],
            "qty": t["qty"], "open_at": t["open_at"],
            "cur_price": cur, "unrealized": round(upnl,2),
        })

    # ── Drawdown ──
    eq_hist = agent_equity[agent_name]
    peak = CAPITAL
    max_dd = 0.0
    max_dd_pct = 0.0
    for eq in eq_hist:
        if eq > peak: peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    # ── Daily PnL ──
    daily_pnl = {}
    for t in closed:
        day = (t.get("close_at") or "")[:10]
        if day:
            daily_pnl[day] = round(daily_pnl.get(day, 0) + t["pnl"], 2)
    daily_pnl_list = [{"date": d, "pnl": v} for d, v in sorted(daily_pnl.items())]

    # ── Avg trade duration ──
    durations = []
    for t in closed:
        if t.get("open_ts") and t.get("close_ts"):
            durations.append(t["close_ts"] - t["open_ts"])
    avg_duration_min = round(sum(durations) / len(durations) / 60, 1) if durations else 0

    cfg = AGENTS[agent_name]
    return {
        "name":        agent_name,
        "id":          cfg["id"],
        "emoji":       cfg["emoji"],
        "color":       cfg["color"],
        "strategy":    cfg["strategy"],
        "timeframe":   cfg["timeframe"],
        "sl_pct":      cfg["sl"]*100,
        "tp_pct":      cfg["tp"]*100,
        "description": cfg["description"],
        "balance":     bal,
        "equity":      equity,
        "return_pct":  ret,
        "trades":      total,
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    wr,
        "pnl":         round(pnl,2),
        "unrealized":  round(unrealized,2),
        "avg_win":     avg_win,
        "avg_loss":    avg_loss,
        "open_count":  len(open_p),
        "open_trades": open_detail,
        "direction":   agent_direction.get(agent_name,"BOTH"),
        "best_trade":  {"pair":best["pair"],"pnl":best["pnl"]}  if best  else None,
        "worst_trade": {"pair":worst["pair"],"pnl":worst["pnl"]} if worst else None,
        "max_drawdown":     round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_duration_min": avg_duration_min,
        "personality":  cfg.get("personality", {}),
        "bias":         cfg.get("bias", "BOTH"),
    }

def get_agent_detail(agent_name):
    """Heavy data only fetched on-demand (modal open)."""
    closed = agent_closed[agent_name]
    eq_hist = agent_equity[agent_name]
    daily_pnl = {}
    for t in closed:
        day = (t.get("close_at") or "")[:10]
        if day:
            daily_pnl[day] = round(daily_pnl.get(day, 0) + t["pnl"], 2)
    return {
        "equity_history": eq_hist[-500:],
        "closed_trades":  closed,
        "daily_pnl":      [{"date": d, "pnl": v} for d, v in sorted(daily_pnl.items())],
    }

def get_pair_heatmap():
    heatmap = defaultdict(float)
    pair_trades = defaultdict(int)
    for t in all_trades:
        sym = t["pair"].replace("USDT","")
        heatmap[sym] += t["pnl"]
        pair_trades[sym] += 1
    return [{"pair":p,"pnl":round(v,2),"trades":pair_trades[p]} for p,v in sorted(heatmap.items(),key=lambda x:-x[1])]

def get_key_moments():
    if not all_trades:
        return {}
    best  = max(all_trades, key=lambda t: t["pnl"])
    worst = min(all_trades, key=lambda t: t["pnl"])

    # win streak per agent
    best_streak = {"agent": "—", "count": 0}
    for name in AGENTS:
        streak = cur = 0
        for t in agent_closed[name]:
            if t["result"] == "TP": cur += 1
            else: cur = 0
            if cur > streak: streak = cur
        if streak > best_streak["count"]:
            best_streak = {"agent": name, "count": streak}

    # loss streak
    worst_streak = {"agent": "—", "count": 0}
    for name in AGENTS:
        streak = cur = 0
        for t in agent_closed[name]:
            if t["result"] == "SL": cur += 1
            else: cur = 0
            if cur > streak: streak = cur
        if streak > worst_streak["count"]:
            worst_streak = {"agent": name, "count": streak}

    # most active agent
    most_active = max(AGENTS, key=lambda n: len(agent_closed[n]))

    return {
        "biggest_win":         {"agent": best["agent"],  "pair": best["pair"],  "pnl": best["pnl"]},
        "biggest_loss":        {"agent": worst["agent"], "pair": worst["pair"], "pnl": worst["pnl"]},
        "longest_win_streak":  best_streak,
        "longest_loss_streak": worst_streak,
        "most_active":         {"agent": most_active, "trades": len(agent_closed[most_active])},
        "total_pnl":           round(sum(t["pnl"] for t in all_trades), 2),
        "total_trades":        len(all_trades),
    }

load_state()
if session_start:
    resume_session()
