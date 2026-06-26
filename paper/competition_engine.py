"""
Competition Engine — manages live paper trading for all 5 agents simultaneously
"""
import sys, os, time, math, threading, requests, json
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

SAVE_FILE = os.path.join(os.path.dirname(__file__), "competition_state.json")

CAPITAL  = 10_000.0
POS_SIZE = 500.0   # $500 margin per trade per agent
LEVERAGE = 50      # default — overridden by saved state if changed
MAX_OPEN = 3       # max concurrent open positions per agent
TF_CANDLES = {"15m": 200, "1h": 200, "4h": 200}
CANDLE_REFRESH = 60    # seconds between candle refresh

# ── State ──────────────────────────────────────────────────────────────────────
session_start   = None
session_running = False
live_prices     = {}   # pair -> price
candle_cache    = {}   # (pair, tf) -> precomputed dict
candle_ts       = {}   # (pair, tf) -> last fetch time

agent_balances  = {name: CAPITAL for name in AGENTS}
agent_open      = {name: [] for name in AGENTS}
agent_closed    = {name: [] for name in AGENTS}
agent_equity    = {name: [CAPITAL] for name in AGENTS}
agent_direction = {name: "LONG" for name in AGENTS}  # LONG | SHORT | BOTH

all_trades      = []
lock            = threading.Lock()

# ── Candle fetch ───────────────────────────────────────────────────────────────
def fetch_candles(pair, tf, n=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={n}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        raw = r.json()
        return {
            "open":  [float(c[1]) for c in raw],
            "high":  [float(c[2]) for c in raw],
            "low":   [float(c[3]) for c in raw],
            "close": [float(c[4]) for c in raw],
            "vol":   [float(c[5]) for c in raw],
        }
    except Exception as e:
        print(f"  candle err {pair} {tf}: {e}")
        return None

def get_candles(pair, tf):
    key = (pair, tf)
    now = time.time()
    if key not in candle_cache or now - candle_ts.get(key, 0) > CANDLE_REFRESH:
        raw = fetch_candles(pair, tf)
        if raw:
            candle_cache[key] = precompute(raw)
            candle_ts[key] = now
    return candle_cache.get(key)

# ── Price stream ───────────────────────────────────────────────────────────────
def fetch_prices():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
        r.raise_for_status()
        for item in r.json():
            if item["symbol"] in PAIRS:
                live_prices[item["symbol"]] = float(item["price"])
    except Exception as e:
        print(f"  price err: {e}")

# ── Signal check ───────────────────────────────────────────────────────────────
def check_signal(agent_name, pair):
    cfg = AGENTS[agent_name]
    tf  = cfg["timeframe"]
    sfn = STRATS.get(cfg["strategy"])
    if not sfn:
        return False
    p = get_candles(pair, tf)
    if not p or p["n"] < 100:
        return False
    i = p["n"] - 2   # last closed candle
    try:
        return sfn(p, i)
    except:
        return False

# ── Short signal mirrors ───────────────────────────────────────────────────────
def _short_keltner(p, i):
    if i < 25: return False
    kc_lower = p["bb_mid"][i] - 2 * p["atr"][i]
    return p["c"][i] < kc_lower and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i]

def _short_adx_trend(p, i):
    if i < 60: return False
    down = p["e9"][i] < p["e21"][i] < p["e50"][i] and p["c"][i] < p["e9"][i]
    if not down or p["adx"][i] < 30 or p["macd_hist"][i] >= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    return max(p["h"][max(0,i-5):i]) >= p["e9"][i] * 0.99 and not p["green"][i]

def _short_macd_bb(p, i):
    if i < 35: return False
    cross_down = p["macd_hist"][i] < 0 and p["macd_hist"][i-1] >= 0
    near_upper = (p["bb_hi"][i] - p["c"][i]) / p["c"][i] * 100 < 2.0
    return cross_down and near_upper and p["rsi"][i] > 40 and not p["green"][i]

def _short_orb(p, i):
    if i < 15: return False
    cons_lo = min(p["l"][i-6:i]); cons_hi = max(p["h"][i-6:i])
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    return rng_pct < 1.5 and p["c"][i] < cons_lo and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i]

def _short_donchian(p, i):
    if i < 25: return False
    return p["c"][i] < p["don_lo"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["rsi"][i] > 22 and not p["green"][i]

SHORT_SIGNALS = {
    "The Maniac":  _short_keltner,
    "The Oracle":  _short_adx_trend,
    "The Surgeon": _short_macd_bb,
    "The Comet":   _short_orb,
    "The Hound":   _short_donchian,
}

# ── Persist state ─────────────────────────────────────────────────────────────
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
            "saved_at":         time.time(),
        }
        tmp = SAVE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, SAVE_FILE)
    except Exception as e:
        print(f"[Save error] {e}")

def load_state():
    global session_start, session_start_ts, session_running, LEVERAGE
    if not os.path.exists(SAVE_FILE):
        return
    try:
        with open(SAVE_FILE) as f:
            data = json.load(f)
        session_start    = data.get("session_start")
        session_start_ts = data.get("session_start_ts")
        session_running  = False  # always start paused after reload
        LEVERAGE         = data.get("leverage", LEVERAGE)
        for name in AGENTS:
            agent_direction[name] = data.get("agent_direction", {}).get(name, "LONG")
        for name in AGENTS:
            agent_balances[name] = data["agent_balances"].get(name, CAPITAL)
            agent_open[name]     = data["agent_open"].get(name, [])
            agent_closed[name]   = data["agent_closed"].get(name, [])
            agent_equity[name]   = data["agent_equity"].get(name, [CAPITAL])
        all_trades.clear()
        all_trades.extend(data.get("all_trades", []))
        print(f"[Competition] State restored — {len(all_trades)} trades loaded")
    except Exception as e:
        print(f"[Load error] {e}")

# ── Trade lifecycle ────────────────────────────────────────────────────────────
def open_trade(agent_name, pair, price, side="LONG"):
    cfg = AGENTS[agent_name]
    sl_p = price * (1 - cfg["sl"]) if side == "LONG" else price * (1 + cfg["sl"])
    tp_p = price * (1 + cfg["tp"]) if side == "LONG" else price * (1 - cfg["tp"])
    trade = {
        "id":       f"{agent_name[:3].upper()}-{pair[:3]}-{side[0]}-{int(time.time()*1000)%100000}",
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
    return trade

def check_close(trade, price):
    side = trade.get("side", "LONG")
    if side == "LONG":
        if price >= trade["tp"]: return "TP"
        if price <= trade["sl"]: return "SL"
    else:  # SHORT
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
        trade["pnl"] = round(trade["qty"] * (trade["tp"] - trade["entry"]), 4) if result == "TP" else round(trade["qty"] * (trade["sl"] - trade["entry"]), 4)
    else:  # SHORT
        trade["pnl"] = round(trade["qty"] * (trade["entry"] - trade["tp"]), 4) if result == "TP" else round(trade["qty"] * (trade["entry"] - trade["sl"]), 4)
    return trade

# ── Main loop ──────────────────────────────────────────────────────────────────
def run_tick():
    global session_running
    fetch_prices()

    with lock:
        for agent_name, cfg in AGENTS.items():
            bal = agent_balances[agent_name]
            open_pos = agent_open[agent_name]

            # 1. Check existing open positions
            closed_this_tick = []
            for trade in open_pos:
                price = live_prices.get(trade["pair"], trade["entry"])
                result = check_close(trade, price)
                if result:
                    close_trade(trade, trade["tp"] if result=="TP" else trade["sl"], result)
                    bal += trade["pnl"]
                    agent_balances[agent_name] = round(bal, 2)
                    agent_closed[agent_name].append(trade)
                    all_trades.append(trade)
                    closed_this_tick.append(trade)
                    save_state()

            agent_open[agent_name] = [t for t in open_pos if t not in closed_this_tick]

            # 2. Check for new signals
            direction = agent_direction.get(agent_name, "LONG")
            if len(agent_open[agent_name]) < MAX_OPEN and bal > POS_SIZE:
                for pair in PAIRS:
                    if len(agent_open[agent_name]) >= MAX_OPEN: break
                    price = live_prices.get(pair)
                    if not price: continue
                    p = get_candles(pair, AGENTS[agent_name]["timeframe"])
                    if not p or p["n"] < 100: continue
                    idx = p["n"] - 2

                    long_sig  = False
                    short_sig = False
                    sfn_long  = STRATS.get(AGENTS[agent_name]["strategy"])
                    sfn_short = SHORT_SIGNALS.get(agent_name)

                    already_long  = any(t["pair"] == pair and t.get("side","LONG") == "LONG"  for t in agent_open[agent_name])
                    already_short = any(t["pair"] == pair and t.get("side","LONG") == "SHORT" for t in agent_open[agent_name])

                    if direction in ("LONG", "BOTH") and not already_long:
                        try: long_sig = sfn_long(p, idx) if sfn_long else False
                        except: pass
                    if direction in ("SHORT", "BOTH") and not already_short:
                        try: short_sig = sfn_short(p, idx) if sfn_short else False
                        except: pass

                    if long_sig:
                        trade = open_trade(agent_name, pair, price, "LONG")
                        agent_open[agent_name].append(trade)
                        save_state()
                    if short_sig and len(agent_open[agent_name]) < MAX_OPEN:
                        trade = open_trade(agent_name, pair, price, "SHORT")
                        agent_open[agent_name].append(trade)
                        save_state()

            # 3. Record equity
            unrealized = sum(
                t["qty"] * (live_prices.get(t["pair"], t["entry"]) - t["entry"])
                if t.get("side", "LONG") == "LONG"
                else t["qty"] * (t["entry"] - live_prices.get(t["pair"], t["entry"]))
                for t in agent_open[agent_name]
            )
            agent_equity[agent_name].append(round(bal + unrealized, 2))

        save_state()

def start_session():
    global session_start, session_running
    session_start   = datetime.now(timezone.utc).isoformat()
    session_running = True
    # Reset state
    for name in AGENTS:
        agent_balances[name] = CAPITAL
        agent_open[name]     = []
        agent_closed[name]   = []
        agent_equity[name]   = [CAPITAL]
    all_trades.clear()
    print(f"[Competition] Session started at {session_start}")

def stop_session():
    global session_running
    session_running = False
    print("[Competition] Session stopped")

# ── Stats helpers ──────────────────────────────────────────────────────────────
def get_agent_stats(agent_name):
    closed = agent_closed[agent_name]
    open_p = agent_open[agent_name]
    wins   = [t for t in closed if t["result"] == "TP"]
    losses = [t for t in closed if t["result"] == "SL"]
    total  = len(closed)
    wr     = round(len(wins)/total*100, 1) if total > 0 else 0
    pnl    = sum(t["pnl"] for t in closed)
    unrealized = sum(
        t["qty"] * (live_prices.get(t["pair"], t["entry"]) - t["entry"])
        if t.get("side", "LONG") == "LONG"
        else t["qty"] * (t["entry"] - live_prices.get(t["pair"], t["entry"]))
        for t in open_p
    )
    bal    = agent_balances[agent_name]
    equity = round(bal + unrealized, 2)
    ret    = round((equity - CAPITAL) / CAPITAL * 100, 2)
    avg_win  = round(sum(t["pnl"] for t in wins)/len(wins), 2)   if wins   else 0
    avg_loss = round(sum(t["pnl"] for t in losses)/len(losses), 2) if losses else 0

    best  = max(closed, key=lambda t: t["pnl"], default=None)
    worst = min(closed, key=lambda t: t["pnl"], default=None)

    open_trades_detail = []
    for t in open_p:
        cur = live_prices.get(t["pair"], t["entry"])
        if t.get("side", "LONG") == "LONG":
            upnl = t["qty"] * (cur - t["entry"])
        else:
            upnl = t["qty"] * (t["entry"] - cur)
        open_trades_detail.append({
            "pair":       t["pair"],
            "side":       t.get("side", "LONG"),
            "entry":      t["entry"],
            "tp":         t["tp"],
            "sl":         t["sl"],
            "qty":        t["qty"],
            "open_at":    t["open_at"],
            "cur_price":  cur,
            "unrealized": round(upnl, 2),
        })

    return {
        "name":      agent_name,
        "id":        AGENTS[agent_name]["id"],
        "emoji":     AGENTS[agent_name]["emoji"],
        "color":     AGENTS[agent_name]["color"],
        "bias":      AGENTS[agent_name]["bias"],
        "strategy":  AGENTS[agent_name]["strategy"],
        "timeframe": AGENTS[agent_name]["timeframe"],
        "sl_pct":    AGENTS[agent_name]["sl"]*100,
        "tp_pct":    AGENTS[agent_name]["tp"]*100,
        "personality": AGENTS[agent_name]["personality"],
        "description": AGENTS[agent_name]["description"],
        "balance":   bal,
        "equity":    equity,
        "return_pct": ret,
        "trades":    total,
        "wins":      len(wins),
        "losses":    len(losses),
        "win_rate":  wr,
        "pnl":       round(pnl, 2),
        "unrealized": round(unrealized, 2),
        "avg_win":   avg_win,
        "avg_loss":  avg_loss,
        "open_count": len(open_p),
        "open_trades": open_trades_detail,
        "direction":  agent_direction.get(agent_name, "LONG"),
        "best_trade":  {"pair": best["pair"],  "pnl": best["pnl"]}  if best  else None,
        "worst_trade": {"pair": worst["pair"], "pnl": worst["pnl"]} if worst else None,
        "equity_history": agent_equity[agent_name][-200:],
    }

def get_pair_heatmap():
    heatmap = defaultdict(float)
    pair_trades = defaultdict(int)
    for t in all_trades:
        sym = t["pair"].replace("USDT","")
        heatmap[sym] += t["pnl"]
        pair_trades[sym] += 1
    return [{"pair": p, "pnl": round(v,2), "trades": pair_trades[p]}
            for p, v in sorted(heatmap.items(), key=lambda x: -x[1])]

def get_key_moments():
    if not all_trades: return {}
    best  = max(all_trades, key=lambda t: t["pnl"])
    worst = min(all_trades, key=lambda t: t["pnl"])

    # longest win streak per agent
    best_streak = 0; streak_agent = ""
    for name in AGENTS:
        streak = cur = 0
        for t in agent_closed[name]:
            if t["result"] == "TP": cur += 1; streak = max(streak, cur)
            else: cur = 0
        if streak > best_streak:
            best_streak = streak; streak_agent = name

    total_trades = len(all_trades)
    elapsed = (time.time() - (session_start_ts or time.time())) / 60 if session_start_ts else 1
    velocity = round(total_trades / max(elapsed, 0.1), 1)

    all_wins  = [t for t in all_trades if t["result"]=="TP"]
    all_loss  = [t for t in all_trades if t["result"]=="SL"]
    avg_win   = round(sum(t["pnl"] for t in all_wins)/len(all_wins), 2)  if all_wins  else 0
    avg_loss  = round(sum(t["pnl"] for t in all_loss)/len(all_loss), 2) if all_loss else 0
    ratio     = round(abs(avg_win/avg_loss), 1) if avg_loss != 0 else 0

    return {
        "biggest_win":  {"agent": best["agent"],  "pair": best["pair"],  "pnl": best["pnl"]},
        "biggest_loss": {"agent": worst["agent"], "pair": worst["pair"], "pnl": worst["pnl"]},
        "win_streak":   {"agent": streak_agent, "streak": best_streak},
        "velocity":     velocity,
        "reward_ratio": ratio,
        "total_trades": total_trades,
    }

session_start_ts = None

# Load any previously saved state on startup
load_state()

def set_agent_direction(agent_name, direction):
    """Set direction for an agent: LONG | SHORT | BOTH"""
    if agent_name in agent_direction and direction in ("LONG", "SHORT", "BOTH"):
        agent_direction[agent_name] = direction
        save_state()

def start_session_with_ts():
    global session_start_ts
    session_start_ts = time.time()
    start_session()

def resume_session():
    """Resume without resetting — preserves all open trades and history."""
    global session_running, session_start_ts
    session_running = True
    if not session_start_ts:
        session_start_ts = time.time()
    print(f"[Competition] Session resumed — {sum(len(agent_open[n]) for n in AGENTS)} open positions restored")
