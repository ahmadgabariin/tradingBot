"""
LighterBot engine — evaluates Liquidity Hunt / Surgeon v2 signals on live
Binance data, sizes positions against real Lighter balance, and places real
orders with attached SL/TP. Designed to fail loud-but-safe: any error is
logged and the tick is skipped, never silently retried into a bad state.
"""
import asyncio, json, os, time, traceback
from datetime import datetime, timezone

import numpy as np

from lighterbot import config as cfgmod
from lighterbot import data_feed
from lighterbot import trade_history
from lighterbot import db
from lighterbot.agents import AGENTS, LONG_SIGNALS, SHORT_SIGNALS, PAIRS, calc_supertrend, _ema
from lighterbot.lighter_client import LighterClient, signed_position_size
from lighterbot.binance_client import BinanceClient
# MARKET_INDEX/PRICE_DECIMALS are NOT imported as flat module constants here —
# each client instance (Lighter or Binance) exposes its own client.MARKET_INDEX/
# client.PRICE_DECIMALS, resolved dynamically per the active config["platform"],
# so the exact same engine code works against either exchange unmodified.
# signed_position_size IS shared/imported directly since both clients
# normalize their position objects into the identical shape it expects.

STATE_FILE = os.path.join(os.path.dirname(__file__), "lighterbot_state.json")
TICK_INTERVAL = 10  # seconds — matches comp11's polling interval so entries fire at the same cadence


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            data.setdefault("position_agent_map", {})
            data.setdefault("agent_open_log", [])
            data.setdefault("agent_realized_pnl", {})
            data.setdefault("counted_trade_keys", [])
            data.setdefault("realized_pnl_backfilled", False)
            data.setdefault("critical_errors", [])
            return data
    return {"trade_log": [], "position_agent_map": {}, "agent_open_log": [],
            "agent_realized_pnl": {}, "counted_trade_keys": [], "realized_pnl_backfilled": False,
            "critical_errors": []}


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


class LighterBotEngine:
    def __init__(self):
        self.client = None
        self.running = False
        self.state = _load_state()
        self.last_error = None
        self._task = None
        self.started_at = None
        # Serializes every position-opening/closing action (manual trades,
        # automated signals, closes) so a manual click and a tick can never
        # race and stack an unintended duplicate position on the same symbol.
        self._trade_lock = asyncio.Lock()

    def log(self, msg):
        line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
        print(line)
        self.state["trade_log"].append(line)
        self.state["trade_log"] = self.state["trade_log"][-300:]
        _save_state(self.state)

    def log_critical_error(self, category, **details):
        """Permanent record of anything that went wrong in a way that could
        affect real money — entry failures, leverage-set failures, and
        especially SL/TP attachment failures (the exact bug class that left
        POL sitting unprotected on 2026-07-05: attach_sl_tp silently reported
        success on a real failure). Unlike self.log()'s trade_log (rotated to
        the last 300 lines — the POL failure had already scrolled off by the
        time it was investigated), this list is capped much more generously
        and is meant to be checked after the fact, not just watched live."""
        entry = {
            "timestamp": time.time(),
            "time_iso": datetime.now(timezone.utc).isoformat(),
            "category": category,
            **details,
        }
        self.state.setdefault("critical_errors", []).append(entry)
        self.state["critical_errors"] = self.state["critical_errors"][-500:]
        self.log(f"CRITICAL ERROR [{category}]: {details}")
        _save_state(self.state)

    def _log_open(self, symbol, agent):
        """Persistent record of who opened what, when — survives after the
        position closes (unlike position_agent_map, which only tracks CURRENT
        open positions for the trailing-stop updater). Used to attribute
        Agent on the Trade History table."""
        self.state.setdefault("agent_open_log", []).append({
            "symbol": symbol, "agent": agent, "opened_at": time.time(),
        })
        self.state["agent_open_log"] = self.state["agent_open_log"][-200:]

    def clear_log(self):
        self.state["trade_log"] = []
        _save_state(self.state)

    def clear_critical_errors(self):
        self.state["critical_errors"] = []
        _save_state(self.state)

    def reset_agent_stats(self, agent_name):
        """Zeroes this agent's tracked realized PnL — Equity/Return/Total PnL
        etc. start fresh from its current start_balance. Does NOT touch
        start_balance itself (that's an allocation choice, not a stat) or any
        real exchange history/trades — purely resets the bookkeeping."""
        self.state.setdefault("agent_realized_pnl", {})[agent_name] = 0.0
        _save_state(self.state)

    async def ensure_client(self):
        """Instantiates whichever exchange client config["platform"] currently
        selects ('lighter' default, or 'binance'). If the platform setting
        changed since the client was last created (e.g. the user switched it
        on the dashboard), discards the old client and creates the new one —
        the bot should be stopped while switching, but this makes a stale
        client impossible to keep using by accident either way."""
        cfg = cfgmod.load_config()
        platform = cfg.get("platform", "lighter")
        if self.client is not None and getattr(self, "_client_platform", None) != platform:
            self.client = None
        if self.client is None:
            self.client = BinanceClient() if platform == "binance" else LighterClient()
            self._client_platform = platform
            ok, result = await self.client.refresh_max_leverage(force=True)
            if ok:
                self.log(f"Live max leverage fetched ({platform}): {result}")
            else:
                self.log(f"Max leverage live fetch failed ({platform}), using fallback defaults: {result}")
        return self.client

    async def maybe_init_agent_balances(self):
        """The first time the real account balance can be fetched, auto-split
        it evenly across agents still marked balance_initialized=False (never
        touches an agent once its flag is True, so a later manual edit —
        including setting it back to 0 — is never overwritten). Fixes
        hardcoded per-agent defaults silently overstating a small real
        account (e.g. defaulting to $50/$50 on an $11 account).

        Divides only among the PENDING agents (those actually being split this
        run) — not the total agent count. Agents deliberately added offline
        with balance_initialized already True (e.g. new agents seeded at $0
        until the user funds them) must never shrink everyone else's share;
        splitting by total count would silently reserve part of the real
        balance for agents that will never use it."""
        cfg = cfgmod.load_config()
        pending = [name for name, acfg in cfg["agents"].items() if not acfg.get("balance_initialized")]
        if not pending:
            return

        client = await self.ensure_client()
        bal, err = await client.get_balance_usd()
        if bal is None:
            self.log(f"Could not auto-init agent balances yet (balance fetch failed): {err}")
            return

        already_allocated = sum(
            a.get("start_balance", 0.0) for name, a in cfg["agents"].items() if name not in pending
        )
        remaining = max(0.0, bal - already_allocated)
        share = round(remaining / len(pending), 2)
        for name in pending:
            cfg["agents"][name]["start_balance"] = share
            cfg["agents"][name]["balance_initialized"] = True
        cfgmod.save_config(cfg)
        self.log(f"Auto-initialized start_balance for {pending} from remaining balance "
                  f"${remaining:.2f} ({len(pending)} pending agents) = ${share:.2f} each")

    async def selftest(self):
        """Verifies API credentials and prints the raw account shape so balance
        field names can be confirmed before trading logic depends on them."""
        client = await self.ensure_client()
        if client.client_check_error:
            self.log(f"SELFTEST FAILED: check_client() error — API key not properly "
                      f"registered for this account: {client.client_check_error}")
            return False, client.client_check_error
        ok, res = await client.get_account_raw()
        if not ok:
            self.log(f"SELFTEST FAILED: {res}")
            return False, res
        self.log(f"SELFTEST OK: account fields = {dir(res)}")
        return True, res

    async def start(self):
        if self.running:
            return
        self.running = True
        self.started_at = time.time()
        cfg = cfgmod.load_config()
        cfg["running"] = True
        cfgmod.save_config(cfg)
        self.log("Engine started.")
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        self.started_at = None
        cfg = cfgmod.load_config()
        cfg["running"] = False
        cfgmod.save_config(cfg)
        self.log("Engine stopped.")

    async def _loop(self):
        while self.running:
            try:
                await self.run_tick()
            except Exception as e:
                self.last_error = str(e)
                self.log(f"TICK ERROR: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(TICK_INTERVAL)

    async def sync_realized_pnl(self):
        """Incrementally folds newly-closed trades into a durable per-agent
        running total (self.state["agent_realized_pnl"]), instead of
        re-summing Lighter's trade history from scratch every time. Each
        trade is counted exactly ONCE (keyed by symbol+open+close timestamp,
        recorded in "counted_trade_keys") the first time it's ever visible,
        then persisted forever — so once a trade has been seen, it can never
        be lost again even as newer trades push it off the exchange API's
        single-page window.

        BUT that guarantee only covers trades seen from here on — it can't
        retroactively recover trades that had already scrolled past page 1
        before this ever ran once. So the very first time this runs (tracked
        via "realized_pnl_backfilled"), it does one deep multi-page fetch to
        catch up on all currently-reachable history; every run after that is
        the cheap 1-page check, since new trades always show up on page 1
        long before the next tick (~15s later) could miss them."""
        client = await self.ensure_client()
        backfilled = self.state.get("realized_pnl_backfilled", False)
        max_pages = 1 if backfilled else 10
        trades, err = await trade_history.get_closed_trades(client, self.state, client.PRICE_DECIMALS, max_pages=max_pages)
        if err:
            return
        if not backfilled:
            self.state["realized_pnl_backfilled"] = True
        counted = set(self.state.get("counted_trade_keys", []))
        realized = dict(self.state.get("agent_realized_pnl", {}))
        changed = not backfilled  # always persist the backfill flag flip, even if it found 0 new trades
        for t in trades:
            key = f"{t['symbol']}|{t['opened_at']}|{t['closed_at']}"
            if key in counted:
                continue
            counted.add(key)
            realized[t["agent"]] = round(realized.get(t["agent"], 0.0) + t["pnl"], 6)
            changed = True
            # This is the exact moment a real trade is confirmed closed for
            # the first time — attach real fee data (one Binance query, only
            # here, never per-tick) and persist to MongoDB, not on every
            # dashboard poll. Best-effort: neither must ever break the
            # realized-PnL tracking above, which is the money-critical part.
            try:
                await trade_history.attach_fee(client, t)
            except Exception as e:
                self.log(f"Could not attach fee for trade {key} (realized PnL tracking is unaffected): {e}")
            try:
                await db.save_trade(t, key)
            except Exception as e:
                self.log(f"Could not save trade {key} to MongoDB (realized PnL tracking is unaffected): {e}")
        if changed:
            # Cap growth generously — this only needs to remember enough keys
            # to outlast one polling cycle's worth of history overlap, not
            # every trade ever made.
            self.state["counted_trade_keys"] = list(counted)[-3000:]
            self.state["agent_realized_pnl"] = realized
            _save_state(self.state)

    async def get_agent_working_balance(self, agent_name, cfg=None):
        """The agent's current compounding balance: start_balance + that
        agent's own cumulative realized PnL (from the durable running total,
        never limited by the exchange's trade-history window — see
        sync_realized_pnl). Grows as the agent wins, shrinks as it loses — so
        a $50 start that grows to $70 sizes its NEXT trade off $70, not $50."""
        cfg = cfg or cfgmod.load_config()
        start_balance = cfg["agents"].get(agent_name, {}).get("start_balance", 0.0)
        await self.sync_realized_pnl()
        realized_pnl = self.state.get("agent_realized_pnl", {}).get(agent_name, 0.0)
        return start_balance + realized_pnl

    def _effective_agent_params(self, agent_name, cfg):
        """Merges the static agent definition (timeframe, exit_mode,
        description — never user-editable) with this agent's runtime-tunable
        trailing/SL-TP overrides from config (atr_sl_mult, atr_tp_mult, and
        whichever exit-mode-specific params apply — sar_af_* for parabolic,
        st_* for supertrend, keltner_* for keltner_exit), so a dashboard edit
        actually takes effect instead of the hardcoded agents.py defaults
        always winning. Falls back to the agents.py value for any field the
        user hasn't overridden."""
        base = AGENTS.get(agent_name)
        if not base:
            return None
        overrides = cfg.get("agents", {}).get(agent_name, {}).get("trailing", {})
        return {**base, **overrides}

    def _agent_open_count(self, agent_name, symbols_with_position):
        """How many of the given live-position symbols this SPECIFIC agent
        owns, per position_agent_map — matches comp11's per-agent MAX_OPEN
        (each agent has its own independent slot budget, not a shared
        account-wide count across every agent)."""
        pos_map = self.state.get("position_agent_map", {})
        return sum(1 for sym in symbols_with_position if pos_map.get(sym, {}).get("agent") == agent_name)

    def _initial_sl_tp(self, agent, side, price, p, idx):
        """Computes the initial SL/TP for a new position — ATR-based by
        default, but for supertrend/keltner_exit exit modes, overrides the SL
        with the live indicator band, exactly like paper11/comp11_engine.py's
        _open_trade(). Ported 1:1 including the wrong-side validation fix:
        calc_supertrend's "inactive" band (fl during a downtrend, fu during an
        uptrend) can hold a stale value on the WRONG side of price when the
        entry signal fires against the indicator's own internal trend state —
        an SL above entry (LONG) or below entry (SHORT) would trigger
        instantly and get mislabeled as a win. Only used if the band actually
        lands on the correct side; otherwise falls back to the ATR-based SL.
        Parabolic's initial SL stays ATR-based too (state kicks in via
        update_trailing_stops), same as comp11."""
        atr = p["atr"][idx]
        sl_dist = agent["atr_sl_mult"] * atr
        tp_dist = agent["atr_tp_mult"] * atr
        sl_price = price - sl_dist if side == "LONG" else price + sl_dist
        tp_price = price + tp_dist if side == "LONG" else price - tp_dist

        exit_mode = agent.get("exit_mode", "atr_trail")

        if exit_mode == "fixed_pct":
            # Comp2's original Liquidity Hunt exit — fixed percentage SL/TP,
            # no ATR involved at all, no trailing (this mode is deliberately
            # excluded from update_trailing_stops'/_trailing_new_sl's mode
            # set, so it stays static for the life of the position, exactly
            # like comp2's open_trade()).
            sl_pct = agent.get("sl_pct", 1.5)
            tp_pct = agent.get("tp_pct", 3.0)
            sl_dist = price * (sl_pct / 100.0)
            tp_dist = price * (tp_pct / 100.0)
            sl_price = price - sl_dist if side == "LONG" else price + sl_dist
            tp_price = price + tp_dist if side == "LONG" else price - tp_dist
            return sl_price, tp_price

        if exit_mode == "supertrend":
            period = agent.get("st_period", 10)
            mult = agent.get("st_mult", 3.0)
            trend, fu, fl = calc_supertrend(p, period=period, multiplier=mult)
            band = fl[idx] if side == "LONG" else fu[idx]
            valid = band and band > 0 and ((side == "LONG" and band < price) or (side == "SHORT" and band > price))
            if valid:
                sl_price = band

        elif exit_mode == "keltner_exit":
            period = agent.get("keltner_period", 20)
            mult = agent.get("keltner_mult", 1.5)
            closes = np.array(p["c"][:p["n"]])
            atrs = np.array(p["atr"][:p["n"]]) if "atr" in p else np.zeros(p["n"])
            ema = _ema(closes, period)
            if ema[idx] > 0:
                kl = ema[idx] - mult * atrs[idx]
                ku = ema[idx] + mult * atrs[idx]
                band = kl if side == "LONG" else ku
                valid = (side == "LONG" and band < price) or (side == "SHORT" and band > price)
                if valid:
                    sl_price = band

        return sl_price, tp_price

    async def _compute_size(self, symbol, leverage, ref_price, cfg, agent_name=None):
        """Returns base_amount in coin units, sized per config, bumped to the
        exchange minimum if below it (never silently below, never silently above
        what the user configured by more than the minimum requires).

        When agent_name is given, percent-mode sizing is a percentage of THAT
        agent's own current working balance (start_balance + its own realized
        PnL — compounds), not the account's total live balance — each agent
        trades against its own slice. Manual trades (agent_name=None) keep the
        old behavior: percent of the real live account balance, using the
        global cfg['sizing']."""
        client = await self.ensure_client()

        if agent_name:
            acfg = cfg["agents"].get(agent_name, {})
            sizing = acfg.get("sizing", {"mode": "fixed", "fixed_usd": 10.0, "percent": 5.0})
        else:
            sizing = cfg["sizing"]

        if sizing["mode"] == "fixed":
            margin_usd = sizing["fixed_usd"]
        elif agent_name:
            working_balance = await self.get_agent_working_balance(agent_name, cfg)
            margin_usd = working_balance * (sizing["percent"] / 100.0)
        else:
            bal, err = await client.get_balance_usd()
            if bal is None:
                self.log(f"Could not fetch balance for percent sizing: {err}")
                return None
            margin_usd = bal * (sizing["percent"] / 100.0)

        notional_usd = margin_usd * leverage
        min_notional = cfg.get("min_notional_usd", 10.0)
        if notional_usd < min_notional:
            # Target a bit ABOVE the exchange floor, not exactly on it — after
            # rounding base_amount to the symbol's lot-size precision, an
            # order sized to land exactly at $10.00 can come out a hair under
            # (e.g. $9.99998) and get rejected. A $0.10 buffer keeps the final
            # rounded order safely clear of the floor.
            notional_usd = min_notional + 0.10

        base_amount = notional_usd / ref_price
        return round(base_amount, 6)

    async def manual_trade(self, symbol, side, override_usd=None,
                            leverage_override=None, sl_pct=1.5, tp_pct=3.0,
                            sl_price_override=None, tp_price_override=None):
        """side: 'LONG' or 'SHORT'. Plain manual trade ticket — no agent involved.
        sl_pct/tp_pct are simple % distance from entry price (defaults: 1.5% / 3%),
        used unless sl_price_override/tp_price_override are given — those, when
        present, are used AS-IS (exact price, no percentage math at all), for
        cases like matching a specific ATR-based level from external analysis
        rather than a round percentage. Either can be set independently (e.g.
        exact SL with a percentage TP)."""
        async with self._trade_lock:
            cfg = cfgmod.load_config()
            client = await self.ensure_client()

            # Refuse to stack a second position on a symbol that already has
            # one open — a misclick shouldn't silently double exposure.
            existing, err = await client.get_open_positions()
            if err:
                return False, f"Could not verify existing positions: {err}"
            for p in existing:
                if getattr(p, "symbol", None) == symbol and float(getattr(p, "position", 0) or 0) != 0:
                    return False, f"{symbol} already has an open position — close it first"

            leverage = leverage_override or cfg["leverage"].get(symbol, cfg["default_leverage"])

            price = await data_feed.get_live_price(symbol)
            if not price:
                return False, "Could not fetch live price"

            ok, lev_res = await client.set_leverage(symbol, leverage)
            if not ok:
                self.log(f"Leverage set failed for {symbol} @ {leverage}x: {lev_res}")
                return False, f"Leverage rejected by exchange: {lev_res}"

            if override_usd:
                base_amount = round((override_usd * leverage) / price, 6)
            else:
                base_amount = await self._compute_size(symbol, leverage, price, cfg)
                if base_amount is None:
                    return False, "Sizing failed"

            is_ask = (side == "SHORT")
            if sl_price_override is not None:
                sl_price = sl_price_override
            else:
                sl_dist = price * (sl_pct / 100.0)
                sl_price = price - sl_dist if side == "LONG" else price + sl_dist
            if tp_price_override is not None:
                tp_price = tp_price_override
            else:
                tp_dist = price * (tp_pct / 100.0)
                tp_price = price + tp_dist if side == "LONG" else price - tp_dist

            # size_before_hint=0.0 is safe here (not just an assumption): the
            # duplicate-position check above already confirmed symbol has NO
            # open position, and the whole function runs under
            # self._trade_lock — no other code path can open one on this
            # symbol between that check and this call. Skips a redundant
            # get_open_positions() round-trip.
            ok, result = await client.place_market_order_with_sl_tp(
                symbol, is_ask, base_amount, price, sl_price, tp_price, size_before_hint=0.0
            )
            self.log(f"MANUAL {side} {symbol} amount={base_amount} leverage={leverage} "
                      f"price={price} sl={sl_price} tp={tp_price} -> ok={ok} result={result}")
            if ok:
                self._log_open(symbol, "Manual")
            else:
                self.log_critical_error("trade_open_failed", agent="Manual", symbol=symbol,
                                         side=side, amount=base_amount, price=price,
                                         sl_price=sl_price, tp_price=tp_price, error=str(result))
            return ok, result

    async def close_position(self, symbol: str):
        """Closes whatever position currently exists on this symbol, sized to
        the live position (not a guessed amount), so it always exactly flattens."""
        async with self._trade_lock:
            client = await self.ensure_client()
            positions, err = await client.get_open_positions()
            if err:
                return False, f"Could not fetch positions: {err}"

            target = None
            for p in positions:
                if getattr(p, "symbol", None) == symbol:
                    size = signed_position_size(p)
                    if size != 0:
                        target = (p, size)
                        break
            if not target:
                return False, f"No open position on {symbol}"

            p, size = target
            price = await data_feed.get_live_price(symbol)
            if not price:
                return False, "Could not fetch live price"

            # Cancel any resting SL/TP (or the interval_check catastrophic
            # backstop) BEFORE closing — a manual close bypasses the OCO/fill
            # mechanism that would otherwise clean these up, so without this
            # they'd sit orphaned on the book once the position is flat.
            orders, orders_err = await client.get_active_orders(client.MARKET_INDEX.get(symbol))
            if not orders_err:
                for o in orders:
                    if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit"):
                        await client.cancel_order(symbol, getattr(o, "order_index"))

            is_ask = size > 0  # closing a LONG needs a SELL; closing a SHORT needs a BUY
            ok, result = await client.close_position_market(symbol, is_ask=is_ask,
                                                              base_amount=abs(size), ref_price=price)
            self.log(f"CLOSE {symbol} size={size} -> ok={ok} result={result}")
            if ok:
                self.state.get("position_agent_map", {}).pop(symbol, None)
                _save_state(self.state)
            return ok, result

    async def close_all_positions(self):
        """Closes every open position one by one. Returns a per-symbol result
        dict so a failure on one symbol doesn't hide successes on others."""
        client = await self.ensure_client()
        positions, err = await client.get_open_positions()
        if err:
            return {}, f"Could not fetch positions: {err}"

        results = {}
        for p in positions:
            symbol = getattr(p, "symbol", None)
            size = float(getattr(p, "position", 0) or 0)
            if not symbol or size == 0:
                continue
            ok, result = await self.close_position(symbol)
            results[symbol] = {"ok": ok, "result": str(result)}
        return results, None

    def _trailing_new_sl(self, mode, agent, mapping, side, price, p, idx, current_sl):
        """Computes the candidate new SL for one trailing-stop mode, ported
        1:1 from paper11/comp11_engine.py's _update_trailing_stops(). Returns
        None if the mode doesn't apply or there's nothing better to move to
        yet — caller still applies its own favorable-direction + not-past-price
        checks before actually modifying the resting order, same as before.
        parabolic is the only mode needing state across ticks (extreme point +
        acceleration factor), read from/written back into `mapping` (which is
        `self.state["position_agent_map"][symbol]`, persisted by the caller)."""
        if mode == "atr_trail":
            atr_mult = agent["atr_sl_mult"]
            atr = p["atr"][idx]
            if not atr or atr <= 0:
                return None
            return price - atr_mult * atr if side == "LONG" else price + atr_mult * atr

        if mode == "supertrend":
            period = agent.get("st_period", 10)
            mult = agent.get("st_mult", 3.0)
            _, fu, fl = calc_supertrend(p, period=period, multiplier=mult)
            band = fl[idx] if side == "LONG" else fu[idx]
            # comp11 guards with `if new_sl and ...` before applying — skip a
            # falsy/zero band rather than let it flow into a real order.
            return band if band else None

        if mode == "keltner_exit":
            period = agent.get("keltner_period", 20)
            mult = agent.get("keltner_mult", 1.5)
            closes = np.array(p["c"][:p["n"]])
            atrs = np.array(p["atr"][:p["n"]]) if "atr" in p else np.zeros(p["n"])
            ema = _ema(closes, period)
            if ema[idx] <= 0:
                return None
            return ema[idx] - mult * atrs[idx] if side == "LONG" else ema[idx] + mult * atrs[idx]

        if mode == "parabolic":
            af = mapping.get("sar_af", agent.get("sar_af_start", 0.02))
            af_step = agent.get("sar_af_step", 0.02)
            af_max = agent.get("sar_af_max", 0.2)
            sar = current_sl
            ep = mapping.get("sar_ep", price)

            if side == "LONG":
                if price > ep:
                    ep = price
                    af = min(af + af_step, af_max)
                new_sar = sar + af * (ep - sar)
                new_sar = min(new_sar, price * 0.998)  # never above price
            else:
                if price < ep:
                    ep = price
                    af = min(af + af_step, af_max)
                new_sar = sar - af * (sar - ep)
                new_sar = max(new_sar, price * 1.002)  # never below price

            mapping["sar_ep"] = ep
            mapping["sar_af"] = af
            return new_sar

        if mode == "chandelier":
            # Ported 1:1 from paper11/comp11_engine.py's chandelier branch:
            # SL anchors to the highest high (LONG) / lowest low (SHORT) seen
            # SINCE ENTRY, minus/plus atr_sl_mult*ATR from that peak — so it
            # only ratchets favorably as price makes new extremes, never
            # loosens. `chand_peak` is state carried in `mapping` across
            # ticks, same pattern as parabolic's sar_ep/sar_af.
            atr_mult = agent["atr_sl_mult"]
            atr = p["atr"][idx]
            if not atr or atr <= 0:
                return None
            peak = mapping.get("chand_peak", price)
            if side == "LONG":
                peak = max(peak, price)
                new_sl = peak - atr_mult * atr
            else:
                peak = min(peak, price)
                new_sl = peak + atr_mult * atr
            mapping["chand_peak"] = peak
            return new_sl

        return None

    async def update_trailing_stops(self, client, live_positions, cfg):
        """Live equivalent of comp9/comp10/comp11's _update_trailing_stops():
        moves the resting stop-loss to lock in profit as price moves
        favorably, using modify_order to update the trigger price in place —
        confirmed live to leave the paired take-profit order completely
        untouched. This is better than cancel+recreate: no window where the
        position is unprotected, and one tx instead of three. Supports all 4
        exit modes agents can use: atr_trail, supertrend, keltner_exit,
        parabolic (see _trailing_new_sl).

        Fetches active orders ONCE per tick for the whole account, then
        splits them locally by market — not once per open position. With
        max_open_positions effectively unlimited, doing this per-position
        would mean N separate API calls scaling with concurrent position
        count; this way the API cost stays flat (1 call) no matter how many
        positions are open at once."""
        pos_map = self.state.get("position_agent_map", {})
        state_changed = False

        all_orders, orders_err = await client.get_active_orders()
        if orders_err:
            self.log(f"Could not fetch active orders for trailing stops, skipping this tick: {orders_err}")
            return
        orders_by_market = {}
        for o in all_orders:
            orders_by_market.setdefault(getattr(o, "market_index", None), []).append(o)

        for p in live_positions:
            symbol = getattr(p, "symbol", None)
            size = signed_position_size(p)
            if not symbol or size == 0:
                continue

            mapping = pos_map.get(symbol)
            if not mapping:
                continue  # not opened by an agent we're tracking (e.g. a manual trade) — leave it alone

            acfg = cfg.get("agents", {}).get(mapping["agent"], {})
            if acfg.get("sl_tp_mode", "continuous") == "interval_check":
                continue  # ALL interval_check trailing (regardless of
                          # sl_on_exchange) is computed in check_interval_exits()
                          # on the agent's own check-interval cadence, matching
                          # comp11's own trailing update timing — never here.

            agent = self._effective_agent_params(mapping["agent"], cfg)
            mode = agent.get("exit_mode") if agent else None
            if mode not in ("atr_trail", "supertrend", "keltner_exit", "parabolic", "chandelier"):
                continue

            p_candles = await data_feed.get_candles(symbol, agent["timeframe"])
            if not p_candles or p_candles["n"] < 20 or "atr" not in p_candles:
                continue
            idx = p_candles["n"] - 2

            price = await data_feed.get_live_price(symbol)
            if not price:
                continue

            side = "LONG" if size > 0 else "SHORT"

            orders = orders_by_market.get(client.MARKET_INDEX.get(symbol), [])
            sl_order = next((o for o in orders if getattr(o, "type", "") == "stop-loss-limit"), None)
            if not sl_order:
                continue  # nothing resting to trail, or already closed
            current_sl = float(getattr(sl_order, "trigger_price", 0) or 0)

            new_sl = self._trailing_new_sl(mode, agent, mapping, side, price, p_candles, idx, current_sl)
            if new_sl is None:
                continue
            # parabolic writes sar_ep/sar_af into `mapping` as a side effect —
            # persist that regardless of whether this tick's SL move itself
            # goes through, so the acceleration factor doesn't reset next tick.
            if mode == "parabolic":
                state_changed = True

            favorable = (new_sl > current_sl) if side == "LONG" else (new_sl < current_sl)
            # comp11 only clamps against current price for supertrend/
            # keltner_exit/chandelier (`new_sl < price` / `new_sl > price`
            # guards — chandelier's own comp11 code has this exact clamp
            # alongside its favorable-direction check) — atr_trail has NEVER
            # had this clamp (matches its original behavior exactly,
            # unchanged for the live Liquidity Hunt/Surgeon v2 agents), and
            # parabolic clamps itself internally above.
            needs_price_clamp = mode in ("supertrend", "keltner_exit", "chandelier")
            past_price = (new_sl >= price) if side == "LONG" else (new_sl <= price)
            if not favorable or (needs_price_clamp and past_price):
                continue

            is_close_ask = (side == "LONG")  # closing a LONG is a SELL
            ok, result = await client.modify_stop_order(
                symbol, getattr(sl_order, "order_index"), new_sl, is_close_ask
            )
            if ok:
                self.log(f"Trailing stop {symbol} ({mode}): {current_sl} -> {new_sl} (price={price})")
            else:
                self.log_critical_error("trailing_modify_failed", agent=mapping["agent"], symbol=symbol,
                                         mode=mode, old_sl=current_sl, attempted_new_sl=new_sl,
                                         price=price, error=str(result),
                                         note="position remains protected by old SL, just not trailed this tick")

        if state_changed:
            _save_state(self.state)

    async def check_interval_exits(self, client, live_positions, cfg):
        """For agents in 'interval_check' sl_tp_mode: the tight SL/TP lives
        only in mapping (mem_sl/mem_tp) — tracked purely in the bot's own
        memory, like comp11's own trade dict — and is compared against a
        POLLED price on this same tick cadence, matching comp11's exit
        behavior exactly, instead of a resting order watched continuously by
        the exchange. Closes via a real market order the instant the polled
        price crosses it. A wide real stop-loss (placed at open, see
        run_tick's fresh-open block) is the only thing protecting the
        position between these checks — this function's only interaction
        with that order is cancelling it right before closing here."""
        pos_map = self.state.get("position_agent_map", {})
        state_changed = False
        now = time.time()

        for p in live_positions:
            symbol = getattr(p, "symbol", None)
            size = signed_position_size(p)
            if not symbol or size == 0:
                continue

            mapping = pos_map.get(symbol)
            if not mapping:
                continue

            acfg = cfg.get("agents", {}).get(mapping["agent"], {})
            if acfg.get("sl_tp_mode", "continuous") != "interval_check":
                continue

            interval = acfg.get("interval_check_seconds", 10)
            if now < mapping.get("next_check_ts", 0):
                continue  # not due yet — lets a per-agent interval exceed the global tick

            price = await data_feed.get_live_price(symbol)
            if not price:
                continue

            side = "LONG" if size > 0 else "SHORT"
            mem_sl = mapping.get("mem_sl")
            mem_tp = mapping.get("mem_tp")
            # If either side is a real resting order on the exchange, it
            # fires on its own and this function shouldn't also try to close
            # on that side's cross (attach failures fall back to in-memory
            # checking automatically since the flag stays False when attach
            # failed, see run_tick's fresh-open block).
            tp_is_in_memory = not mapping.get("tp_on_exchange", False)
            sl_is_in_memory = not mapping.get("sl_on_exchange", False)

            hit = None
            if side == "LONG":
                if tp_is_in_memory and mem_tp and price >= mem_tp: hit = "TP"
                elif sl_is_in_memory and mem_sl and price <= mem_sl: hit = "SL"
            else:
                if tp_is_in_memory and mem_tp and price <= mem_tp: hit = "TP"
                elif sl_is_in_memory and mem_sl and price >= mem_sl: hit = "SL"

            if hit:
                # Cancel any resting orders (the wide catastrophic backstop
                # and/or a real on-exchange TP) before closing — they're
                # reduce_only/BaseAmount=0, so they'd otherwise sit orphaned
                # once the position is flat.
                orders, orders_err = await client.get_active_orders(client.MARKET_INDEX.get(symbol))
                if not orders_err:
                    for o in orders:
                        if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit"):
                            await client.cancel_order(symbol, getattr(o, "order_index"))

                close_is_ask = size > 0  # closing a LONG needs a SELL
                ok, result = await client.close_position_market(symbol, is_ask=close_is_ask,
                                                                  base_amount=abs(size), ref_price=price)
                self.log(f"{mapping['agent']} INTERVAL-{hit} {symbol} size={size} price={price} "
                          f"mem_sl={mem_sl} mem_tp={mem_tp} -> ok={ok} result={result}")
                if not ok:
                    self.log_critical_error("interval_close_failed", agent=mapping["agent"], symbol=symbol,
                                             hit=hit, size=size, price=price, error=str(result))
                    continue  # leave mapping in place — will retry next due tick
                pos_map.pop(symbol, None)
                state_changed = True
                continue

            # Not hit — recompute the trailing SL the same way continuous
            # mode does (identical math), always on THIS function's own
            # check-interval cadence (matching comp11's own trailing update
            # timing) regardless of sl_on_exchange — trailing computation
            # never moves to update_trailing_stops()'s separate per-tick
            # cadence. If sl_on_exchange is set, the freshly-computed value
            # also gets pushed to the real resting order; otherwise it's
            # just written to memory, same as before.
            agent = self._effective_agent_params(mapping["agent"], cfg)
            mode = agent.get("exit_mode") if agent else None
            if mode in ("atr_trail", "supertrend", "keltner_exit", "parabolic"):
                p_candles = await data_feed.get_candles(symbol, agent["timeframe"])
                if p_candles and p_candles["n"] >= 20 and "atr" in p_candles:
                    idx = p_candles["n"] - 2
                    new_sl = self._trailing_new_sl(mode, agent, mapping, side, price, p_candles, idx, mem_sl)
                    if new_sl is not None:
                        favorable = (new_sl > mem_sl) if side == "LONG" else (new_sl < mem_sl)
                        needs_price_clamp = mode in ("supertrend", "keltner_exit")
                        past_price = (new_sl >= price) if side == "LONG" else (new_sl <= price)
                        if favorable and not (needs_price_clamp and past_price):
                            if sl_is_in_memory:
                                mapping["mem_sl"] = new_sl
                                state_changed = True
                            else:
                                # sl_on_exchange — push the new level to the
                                # real resting order instead of memory-only.
                                orders, orders_err = await client.get_active_orders(client.MARKET_INDEX.get(symbol))
                                sl_order = None
                                if not orders_err:
                                    sl_order = next((o for o in orders if getattr(o, "type", "") == "stop-loss-limit"), None)
                                if sl_order:
                                    is_close_ask = (side == "LONG")
                                    mok, mres = await client.modify_stop_order(
                                        symbol, getattr(sl_order, "order_index"), new_sl, is_close_ask
                                    )
                                    if mok:
                                        mapping["mem_sl"] = new_sl
                                        state_changed = True
                                    else:
                                        self.log_critical_error(
                                            "trailing_modify_failed", agent=mapping["agent"], symbol=symbol,
                                            mode=mode, old_sl=mem_sl, attempted_new_sl=new_sl, price=price,
                                            error=str(mres),
                                            note="interval_check sl_on_exchange trailing update failed — old real SL remains in place")

            mapping["next_check_ts"] = now + interval
            state_changed = True

        if state_changed:
            _save_state(self.state)

    async def check_for_unprotected_positions(self, client, live_positions):
        """Startup/every-tick safety net for a real, confirmed gap: if the
        bot process is killed/restarted at the exact moment between an
        order's real fill and its SL/TP being attached (e.g. mid-tick during
        a deploy restart), the position is real and on the exchange, but
        never made it into position_agent_map and has zero resting
        protection — invisible to every other check, since update_trailing_
        stops/check_interval_exits only ever look at symbols already in the
        map. Confirmed live: LINK and DOT sat fully unprotected for several
        minutes after a restart before being caught manually.

        This is NOT the same as a legitimate 'Manual' trade (opened outside
        the bot, e.g. via the dashboard's manual-trade ticket) — those always
        get real SL/TP attached at open time and so are NOT flagged here.
        Only a symbol that is BOTH untracked AND has zero resting
        stop-loss-limit/take-profit-limit orders is a genuine orphan —
        flattened immediately rather than left exposed until a human
        happens to notice."""
        pos_map = self.state.get("position_agent_map", {})
        untracked = [
            p for p in live_positions
            if getattr(p, "symbol", None) and signed_position_size(p) != 0
            and getattr(p, "symbol", None) not in pos_map
        ]
        if not untracked:
            return

        all_orders, orders_err = await client.get_active_orders()
        if orders_err:
            self.log(f"Could not fetch active orders for orphan-protection check, skipping this tick: {orders_err}")
            return
        protected_markets = {
            getattr(o, "market_index", None) for o in all_orders
            if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit")
        }

        for p in untracked:
            symbol = getattr(p, "symbol", None)
            market_index = client.MARKET_INDEX.get(symbol)
            if market_index in protected_markets:
                continue  # a real bracket exists (legitimate Manual trade) — leave it alone

            size = signed_position_size(p)
            price = await data_feed.get_live_price(symbol)
            if not price:
                self.log(f"ORPHAN ALERT: {symbol} is untracked and unprotected but no live price "
                          f"available to flatten it this tick — will retry next tick")
                continue

            close_is_ask = size > 0  # closing a LONG needs a SELL
            ok, result = await client.close_position_market(symbol, is_ask=close_is_ask,
                                                              base_amount=abs(size), ref_price=price)
            self.log_critical_error(
                "orphaned_unprotected_position", symbol=symbol, size=size, price=price,
                flattened_ok=ok, flatten_result=str(result),
                note="Position existed on the exchange with no position_agent_map entry and zero "
                     "resting SL/TP — almost certainly a bot restart landing between a real fill "
                     "and its protection being attached. Flattened immediately for safety.")

    TRACKED_GAP_PERSIST_SECONDS = 20  # ~2 ticks at the 10s interval_check cadence

    async def check_for_tracked_gap_positions(self, client, live_positions):
        """Second-layer safety net, complementary to check_for_unprotected_positions:
        catches a position that IS tracked in position_agent_map (the bot
        believes sl_on_exchange/tp_on_exchange are true) but actually has
        ZERO real resting orders on the exchange — confirmed live twice
        (DOT, then POL) where the attach step silently failed or a modify
        left nothing resting, while the bot's own bookkeeping still said
        'protected'. check_for_unprotected_positions does NOT catch this
        case since it only looks at symbols absent from the map entirely.

        Requires the gap to persist across multiple ticks
        (TRACKED_GAP_PERSIST_SECONDS) before acting: a legitimate trailing-
        stop update briefly cancels the old SL and creates a new one
        (sub-second window) — acting on a single tick's snapshot would
        falsely flatten a healthy, actively-managed position. Both real
        incidents persisted for a full 15+ minute manual check, far longer
        than any legitimate modify window, so this threshold has ample
        margin against false positives."""
        pos_map = self.state.get("position_agent_map", {})
        gap_since = self.state.setdefault("tracked_gap_since", {})

        live_by_symbol = {
            getattr(p, "symbol", None): p for p in live_positions
            if signed_position_size(p) != 0
        }

        tracked_symbols = [
            sym for sym, info in pos_map.items()
            if sym in live_by_symbol and (info.get("sl_on_exchange") or info.get("tp_on_exchange"))
        ]
        if not tracked_symbols:
            if gap_since:
                gap_since.clear()
                _save_state(self.state)
            return

        all_orders, orders_err = await client.get_active_orders()
        if orders_err:
            self.log(f"Could not fetch active orders for tracked-gap check, skipping this tick: {orders_err}")
            return
        protected_markets = {
            getattr(o, "market_index", None) for o in all_orders
            if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit")
        }

        now = time.time()
        changed = False
        for sym in tracked_symbols:
            market_index = client.MARKET_INDEX.get(sym)
            info = pos_map[sym]
            has_protection = market_index in protected_markets

            if has_protection:
                if gap_since.pop(sym, None) is not None:
                    changed = True
                continue

            if sym not in gap_since:
                gap_since[sym] = now
                changed = True
                self.log_critical_error(
                    "tracked_position_gap_detected", symbol=sym,
                    note="Tracked position shows zero real resting SL/TP orders — watching "
                         "for persistence before acting (may be a legitimate trailing-stop "
                         "modify window, which normally clears within one tick).")
                continue

            elapsed = now - gap_since[sym]
            if elapsed < self.TRACKED_GAP_PERSIST_SECONDS:
                continue

            p = live_by_symbol[sym]
            size = signed_position_size(p)
            price = await data_feed.get_live_price(sym)
            if not price:
                self.log(f"TRACKED GAP ALERT: {sym} unprotected for {elapsed:.0f}s but no live "
                          f"price available to flatten it this tick — will retry next tick")
                continue

            close_is_ask = size > 0  # closing a LONG needs a SELL
            ok, result = await client.close_position_market(sym, is_ask=close_is_ask,
                                                              base_amount=abs(size), ref_price=price)
            self.log_critical_error(
                "tracked_unprotected_position_flattened", symbol=sym, size=size, price=price,
                elapsed_seconds=round(elapsed, 1), flattened_ok=ok, flatten_result=str(result),
                note=f"Tracked position had zero real resting SL/TP for over "
                     f"{self.TRACKED_GAP_PERSIST_SECONDS}s — persisted well past any legitimate "
                     f"modify window, treated as a genuine gap. Flattened for safety.")
            gap_since.pop(sym, None)
            pos_map.pop(sym, None)
            changed = True

        if changed:
            _save_state(self.state)

    async def run_tick(self):
        """Data fetching and signal detection run WITHOUT holding the trade
        lock — scanning 2 agents x 10 pairs against Binance takes 10+ seconds,
        and holding the lock for that whole time made manual trades/closes
        wait for the entire tick to finish before they could even start. Only
        the actual order-placement moment (leverage + size + submit) takes the
        lock, and re-verifies the position state fresh at that point in case
        something changed (a manual trade, another signal) during the scan."""
        client = await self.ensure_client()
        await self.maybe_init_agent_balances()
        await self.sync_realized_pnl()
        cfg = cfgmod.load_config()  # reload — may have just been updated by the auto-init above

        # Check LIVE positions from Lighter, not local state — local state
        # drifts from reality when trades happen outside the engine (manual
        # trades, dashboard closes), so it's not a safe source of truth for
        # dedup/limit checks.
        live_positions, pos_err = await client.get_open_positions()
        if pos_err:
            self.log(f"Could not fetch live positions, skipping tick: {pos_err}")
            return
        symbols_with_position = {
            getattr(p, "symbol", None) for p in live_positions
            if signed_position_size(p) != 0
        }
        # Current direction of each live position — needed to tell an "add to
        # my own existing position" case (same direction) apart from a "flip"
        # case (opposite direction, always blocked regardless of
        # max_positions_per_symbol — handled separately, not here).
        symbol_direction = {
            getattr(p, "symbol", None): ("LONG" if signed_position_size(p) > 0 else "SHORT")
            for p in live_positions if signed_position_size(p) != 0
        }
        async with self._trade_lock:
            await self.check_for_unprotected_positions(client, live_positions)
            await self.check_for_tracked_gap_positions(client, live_positions)
            await self.update_trailing_stops(client, live_positions, cfg)
            await self.check_interval_exits(client, live_positions, cfg)

        # Prefetch every (symbol, timeframe) combo the scan below will need,
        # CONCURRENTLY instead of one-at-a-time — data_feed.get_candles()
        # already caches per (symbol, timeframe) for 8s, so this just changes
        # WHEN the cache gets populated (all at once, in parallel) instead of
        # serially as the scan loop reaches each pair. Same data, same
        # signals, same trades — purely cuts wall-clock tick duration, which
        # matters more now with 5 agents instead of 2 to scan every tick.
        needed = set()
        for agent_name, acfg in cfg["agents"].items():
            if not acfg.get("enabled"):
                continue
            agent = self._effective_agent_params(agent_name, cfg)
            if not agent:
                continue
            for symbol in PAIRS:
                # Prefetch unconditionally now — a symbol already holding a
                # position may still be eligible for an add-to-position
                # (max_positions_per_symbol > 1), so presence of a position
                # alone no longer rules a symbol out before we've even
                # evaluated the signal's direction.
                needed.add((symbol, agent["timeframe"]))
        if needed:
            fetched = await asyncio.gather(
                *(data_feed.get_candles(sym, tf) for sym, tf in needed)
            )
            candles_cache = dict(zip(needed, fetched))
        else:
            candles_cache = {}

        for agent_name, acfg in cfg["agents"].items():
            if not acfg.get("enabled"):
                continue

            agent = self._effective_agent_params(agent_name, cfg)
            if not agent:
                continue

            direction = acfg.get("direction", "BOTH")
            sfn_long  = LONG_SIGNALS.get(agent_name)
            sfn_short = SHORT_SIGNALS.get(agent_name)
            agent_open_count = self._agent_open_count(agent_name, symbols_with_position)

            agent_max_open = acfg.get("max_open_positions", 9999)
            for symbol in PAIRS:
                if agent_open_count >= agent_max_open:
                    break

                p = candles_cache.get((symbol, agent["timeframe"]))
                if not p or p["n"] < 100:  # matches comp11's warmup requirement
                    continue
                idx = p["n"] - 2

                long_sig = short_sig = False
                if direction in ("LONG", "BOTH"):
                    try: long_sig = sfn_long(p, idx) if sfn_long else False
                    except Exception as e: self.log(f"{agent_name} {symbol} long signal error: {e}")
                if direction in ("SHORT", "BOTH") and not long_sig:
                    try: short_sig = sfn_short(p, idx) if sfn_short else False
                    except Exception as e: self.log(f"{agent_name} {symbol} short signal error: {e}")

                if not (long_sig or short_sig):
                    continue

                side = "LONG" if long_sig else "SHORT"

                # Decide open vs add vs flip vs block now that we know this
                # signal's direction. A SAME-direction signal on a symbol this
                # SAME agent already holds is allowed to ADD, up to
                # max_positions_per_symbol total. An OPPOSITE-direction signal
                # on a symbol this SAME agent already holds is allowed to
                # FLIP — close the existing position at market, then open
                # fresh in the new direction, matching comp11's paper-trading
                # behavior (old trade closes, a new independent one starts).
                # A different agent's symbol is still hard-blocked (no
                # cross-agent attribution support — avoids one agent closing
                # another's position out from under it).
                is_add = False
                is_flip = False
                if symbol in symbols_with_position:
                    existing_mapping = self.state.get("position_agent_map", {}).get(symbol)
                    existing_dir = symbol_direction.get(symbol)
                    same_agent = existing_mapping and existing_mapping.get("agent") == agent_name
                    same_direction = existing_dir == side
                    if not same_agent:
                        continue  # different agent's position — hard-blocked
                    if same_direction:
                        max_per_symbol = acfg.get("max_positions_per_symbol", 9999)
                        already_count = 1 + (existing_mapping.get("add_count", 0) if existing_mapping else 0)
                        if already_count >= max_per_symbol:
                            continue  # at the per-symbol cap
                        is_add = True
                    else:
                        is_flip = True

                # Found a real signal — now take the lock for the actual
                # mutating part, re-checking fresh since the slow scan above
                # ran lock-free and state may have changed in the meantime.
                async with self._trade_lock:
                    fresh_positions, err2 = await client.get_open_positions()
                    if err2:
                        self.log(f"Could not re-verify positions before opening {symbol}: {err2}")
                        continue
                    fresh_symbols = {
                        getattr(p2, "symbol", None) for p2 in fresh_positions
                        if signed_position_size(p2) != 0
                    }
                    fresh_direction = {
                        getattr(p2, "symbol", None): ("LONG" if signed_position_size(p2) > 0 else "SHORT")
                        for p2 in fresh_positions if signed_position_size(p2) != 0
                    }

                    # Re-derive is_add/is_flip against FRESH data — state may
                    # have changed since the lock-free scan above (another
                    # tick or a manual action could have opened/closed/added
                    # in the meantime).
                    fresh_is_add = False
                    fresh_is_flip = False
                    if symbol in fresh_symbols:
                        existing_mapping = self.state.get("position_agent_map", {}).get(symbol)
                        same_agent = existing_mapping and existing_mapping.get("agent") == agent_name
                        same_direction = fresh_direction.get(symbol) == side
                        if not same_agent:
                            continue  # no longer eligible — different agent holds it now
                        if same_direction:
                            max_per_symbol = acfg.get("max_positions_per_symbol", 9999)
                            already_count = 1 + (existing_mapping.get("add_count", 0) if existing_mapping else 0)
                            if already_count >= max_per_symbol:
                                continue  # no longer eligible — at the per-symbol cap
                            fresh_is_add = True
                        else:
                            fresh_is_flip = True
                    elif self._agent_open_count(agent_name, fresh_symbols) >= agent_max_open:
                        continue

                    price = await data_feed.get_live_price(symbol)
                    if not price:
                        self.log(f"No live price for {symbol}, skipping signal")
                        continue

                    if fresh_is_flip:
                        old_pos = next((p2 for p2 in fresh_positions if getattr(p2, "symbol", None) == symbol), None)
                        old_size = signed_position_size(old_pos) if old_pos is not None else 0
                        if old_size == 0:
                            continue  # already flat — nothing to flip

                        # Cancel the old SL/TP before flattening so they can't
                        # fire mid-flip against a position that's about to change.
                        old_orders, old_orders_err = await client.get_active_orders(client.MARKET_INDEX.get(symbol))
                        if not old_orders_err:
                            for o in old_orders:
                                if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit"):
                                    await client.cancel_order(symbol, getattr(o, "order_index"))

                        close_is_ask = old_size > 0  # closing a LONG needs a SELL
                        ok, result = await client.close_position_market(
                            symbol, is_ask=close_is_ask, base_amount=abs(old_size), ref_price=price
                        )
                        self.log(f"{agent_name} FLIP-CLOSE {symbol} old_size={old_size} side={side} "
                                  f"price={price} -> ok={ok} result={result}")
                        if not ok:
                            self.log_critical_error("flip_close_failed", agent=agent_name, symbol=symbol,
                                                     side=side, old_size=old_size, price=price, error=str(result))
                            continue

                        # Position is now flat — clear the old mapping and let
                        # execution fall through to the normal fresh-open path
                        # below (fresh_is_add stays False), exactly like
                        # comp11 logging a closed trade followed by a new one.
                        self.state["position_agent_map"].pop(symbol, None)
                        fresh_symbols.discard(symbol)
                        _save_state(self.state)

                    leverage = cfg["leverage"].get(symbol, cfg["default_leverage"])
                    if not fresh_is_add:
                        # Leverage is already applied on this market from when
                        # the position first opened — Lighter always rejects a
                        # leverage change on a symbol with an existing position
                        # or resting order, so skip this call entirely for adds.
                        ok, lev_res = await client.set_leverage(symbol, leverage)
                        if not ok:
                            self.log_critical_error("leverage_set_failed", agent=agent_name, symbol=symbol,
                                                     leverage=leverage, side=side, error=str(lev_res))
                            continue

                    base_amount = await self._compute_size(symbol, leverage, price, cfg, agent_name)
                    if base_amount is None:
                        continue

                    is_ask = (side == "SHORT")

                    if fresh_is_add:
                        # Adding to our OWN existing same-direction position —
                        # the resting SL/TP (BaseAmount=0, "close whatever the
                        # position is") automatically covers the new larger
                        # size, no need to touch them.
                        ok, result = await client.add_to_position_market(symbol, is_ask, base_amount, price)
                        self.log(f"{agent_name} ADD {side} {symbol} amount={base_amount} "
                                  f"price={price} -> ok={ok} result={result}")
                        if not ok:
                            self.log_critical_error("add_to_position_failed", agent=agent_name, symbol=symbol,
                                                     side=side, amount=base_amount, price=price, error=str(result))
                        if ok:
                            mapping = self.state["position_agent_map"][symbol]
                            mapping["add_count"] = mapping.get("add_count", 0) + 1
                            _save_state(self.state)
                        continue

                    sl_price, tp_price = self._initial_sl_tp(agent, side, price, p, idx)
                    interval_mode = acfg.get("sl_tp_mode", "continuous") == "interval_check"

                    tp_on_exchange_attached = False
                    if interval_mode:
                        # No real bracket — entry only, tight SL/TP tracked in
                        # memory and checked by check_interval_exits() on the
                        # same tick cadence, matching comp11.
                        ok, result = await client.add_to_position_market(symbol, is_ask, base_amount, price)
                        self.log(f"{agent_name} SIGNAL(interval) {side} {symbol} amount={base_amount} "
                                  f"price={price} mem_sl={sl_price} mem_tp={tp_price} -> ok={ok} result={result}")
                        if not ok:
                            self.log_critical_error("trade_open_failed", agent=agent_name, symbol=symbol,
                                                     side=side, amount=base_amount, price=price,
                                                     sl_price=sl_price, tp_price=tp_price, error=str(result))
                        else:
                            sl_on_exchange = acfg.get("sl_on_exchange", False)
                            if sl_on_exchange:
                                # SL placed as a REAL resting order at the
                                # agent's actual (tight) sl_price — not a wide
                                # backstop. Makes the catastrophic backstop
                                # redundant, so it's skipped entirely here
                                # rather than stacking a second, pointless
                                # resting order underneath it.
                                seed_base = int(time.time() * 1000)
                                cok, cres = await client.attach_catastrophic_sl(symbol, is_ask, sl_price,
                                                                                  client_order_seed=seed_base)
                                if not cok:
                                    # Requested but failed to attach — don't
                                    # leave a real position with ZERO
                                    # protection at all silently; flatten
                                    # immediately, same safety philosophy as
                                    # continuous mode's SL/TP-attach failure
                                    # handling.
                                    await client.close_position_market(symbol, is_ask=not is_ask,
                                                                        base_amount=base_amount, ref_price=price)
                                    self.log_critical_error(
                                        "real_sl_attach_failed", agent=agent_name, symbol=symbol, side=side,
                                        sl_price=sl_price, error=str(cres),
                                        note="position flattened — real SL on exchange was requested but failed to attach")
                                    ok = False
                            elif acfg.get("catastrophic_enabled", True):
                                catastrophic_pct = acfg.get("catastrophic_pct", 7.0)
                                catastrophic_sl = (price * (1 - catastrophic_pct/100) if side == "LONG"
                                                    else price * (1 + catastrophic_pct/100))
                                seed_base = int(time.time() * 1000)
                                cok, cres = await client.attach_catastrophic_sl(symbol, is_ask, catastrophic_sl,
                                                                                  client_order_seed=seed_base)
                                if not cok:
                                    # Requested but failed to attach — don't
                                    # leave a real position with ZERO
                                    # protection at all silently; flatten
                                    # immediately, same safety philosophy as
                                    # continuous mode's SL/TP-attach failure
                                    # handling.
                                    await client.close_position_market(symbol, is_ask=not is_ask,
                                                                        base_amount=base_amount, ref_price=price)
                                    self.log_critical_error(
                                        "catastrophic_sl_failed", agent=agent_name, symbol=symbol, side=side,
                                        catastrophic_sl=catastrophic_sl, error=str(cres),
                                        note="position flattened — catastrophic safety-net was requested but failed to attach")
                                    ok = False

                            if ok and acfg.get("tp_on_exchange", False):
                                # Puts TP back on the exchange (watched
                                # continuously) while SL stays in-memory —
                                # there's no downside-risk reason to keep TP
                                # polled-only, unlike SL. A distinct seed
                                # offset avoids colliding with the
                                # catastrophic order's client_order_index.
                                tp_seed = int(time.time() * 1000) + 1
                                tok, tres = await client.attach_real_tp(symbol, is_ask, tp_price,
                                                                          client_order_seed=tp_seed)
                                if tok:
                                    tp_on_exchange_attached = True
                                else:
                                    # Not safety-critical like the SL side —
                                    # falls back to in-memory TP checking for
                                    # this position instead of flattening.
                                    self.log_critical_error(
                                        "real_tp_attach_failed", agent=agent_name, symbol=symbol, side=side,
                                        tp_price=tp_price, error=str(tres),
                                        note="falling back to in-memory TP check for this position")
                    else:
                        # size_before_hint=0.0 is safe: this branch only runs
                        # when NOT fresh_is_add, meaning symbol is confirmed
                        # flat here — either it was never in fresh_symbols, or
                        # the flip-close block just above flattened it and
                        # discarded it from fresh_symbols. Skips a redundant
                        # get_open_positions() round-trip.
                        ok, result = await client.place_market_order_with_sl_tp(
                            symbol, is_ask, base_amount, price, sl_price, tp_price, size_before_hint=0.0
                        )
                        self.log(f"{agent_name} SIGNAL {side} {symbol} amount={base_amount} "
                                  f"price={price} sl={sl_price} tp={tp_price} -> ok={ok} result={result}")
                        if not ok:
                            self.log_critical_error("trade_open_failed", agent=agent_name, symbol=symbol,
                                                     side=side, amount=base_amount, price=price,
                                                     sl_price=sl_price, tp_price=tp_price, error=str(result))

                    if ok:
                        # A flip closed-then-reopened the SAME symbol, so this
                        # agent's own open-slot count is unchanged — only bump
                        # it for a genuinely fresh open (per-agent cap, like
                        # comp11's independent per-agent MAX_OPEN).
                        if symbol not in symbols_with_position:
                            agent_open_count += 1
                        symbols_with_position.add(symbol)
                        mapping = {"agent": agent_name, "add_count": 0}
                        if interval_mode:
                            mapping["mem_sl"] = sl_price
                            mapping["mem_tp"] = tp_price
                            mapping["tp_on_exchange"] = tp_on_exchange_attached
                            # sl_on_exchange being True here always means it
                            # succeeded — a failed attach sets ok=False and
                            # flattens before this block is ever reached.
                            mapping["sl_on_exchange"] = acfg.get("sl_on_exchange", False)
                            mapping["next_check_ts"] = time.time() + acfg.get("interval_check_seconds", 10)
                        else:
                            # Continuous mode's place_market_order_with_sl_tp
                            # always attaches a real OCO SL/TP bracket on
                            # success — it flattens immediately and returns
                            # ok=False if attachment fails (see its docstring),
                            # so reaching this block guarantees a real resting
                            # bracket exists. These flags must be set here (not
                            # left unset/False) so check_for_tracked_gap_positions
                            # actually covers continuous-mode positions too —
                            # confirmed live that leaving them unset made that
                            # safety net silently skip every continuous-mode
                            # position, exactly the gap it was built to catch.
                            mapping["sl_on_exchange"] = True
                            mapping["tp_on_exchange"] = True
                        if agent.get("exit_mode") == "parabolic":
                            # Parabolic SAR needs continuity state across ticks
                            # (extreme point + acceleration factor) — seeded
                            # here exactly like comp11_engine.py's _open_trade,
                            # then advanced each tick in update_trailing_stops.
                            mapping["sar_ep"] = price
                            mapping["sar_af"] = agent.get("sar_af_start", 0.02)
                        self.state["position_agent_map"][symbol] = mapping
                        self._log_open(symbol, agent_name)
                        _save_state(self.state)

            # Drop mapping entries for symbols that no longer have a live position
            # (closed via SL/TP fill, manual close, etc.) so trailing doesn't act
            # on stale data next tick. For interval_check positions specifically,
            # an unpaired catastrophic-SL/real-TP order (they're placed as two
            # SEPARATE single orders, not one OCO pair, so one firing doesn't
            # auto-cancel the other) could still be resting on a now-flat
            # symbol — clean those up too rather than leaving them orphaned.
            for sym in list(self.state["position_agent_map"].keys()):
                if sym not in symbols_with_position:
                    dropped_mapping = self.state["position_agent_map"][sym]
                    dropped_acfg = cfg.get("agents", {}).get(dropped_mapping.get("agent"), {})
                    if dropped_acfg.get("sl_tp_mode") == "interval_check":
                        orders, orders_err = await client.get_active_orders(client.MARKET_INDEX.get(sym))
                        if not orders_err:
                            for o in orders:
                                if getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit"):
                                    await client.cancel_order(sym, getattr(o, "order_index"))
                    del self.state["position_agent_map"][sym]
            _save_state(self.state)


engine = LighterBotEngine()
