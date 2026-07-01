"""
LighterBot engine — evaluates Liquidity Hunt / Surgeon v2 signals on live
Binance data, sizes positions against real Lighter balance, and places real
orders with attached SL/TP. Designed to fail loud-but-safe: any error is
logged and the tick is skipped, never silently retried into a bad state.
"""
import asyncio, json, os, time, traceback
from datetime import datetime, timezone

from lighterbot import config as cfgmod
from lighterbot import data_feed
from lighterbot.agents import AGENTS, LONG_SIGNALS, SHORT_SIGNALS, PAIRS
from lighterbot.lighter_client import LighterClient, MARKET_INDEX

STATE_FILE = os.path.join(os.path.dirname(__file__), "lighterbot_state.json")
TICK_INTERVAL = 15  # seconds — slower than paper bots since these are real orders


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            data.setdefault("position_agent_map", {})
            data.setdefault("agent_open_log", [])
            return data
    return {"trade_log": [], "position_agent_map": {}, "agent_open_log": []}


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

    async def ensure_client(self):
        if self.client is None:
            self.client = LighterClient()
            ok, result = await self.client.refresh_max_leverage(force=True)
            if ok:
                self.log(f"Live max leverage fetched: {result}")
            else:
                self.log(f"Max leverage live fetch failed, using fallback defaults: {result}")
        return self.client

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
        cfg = cfgmod.load_config()
        cfg["running"] = True
        cfgmod.save_config(cfg)
        self.log("Engine started.")
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
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

    async def _compute_size(self, symbol, leverage, ref_price, cfg):
        """Returns base_amount in coin units, sized per config, bumped to the
        exchange minimum if below it (never silently below, never silently above
        what the user configured by more than the minimum requires)."""
        sizing = cfg["sizing"]
        client = await self.ensure_client()

        if sizing["mode"] == "fixed":
            margin_usd = sizing["fixed_usd"]
        else:
            bal, err = await client.get_balance_usd()
            if bal is None:
                self.log(f"Could not fetch balance for percent sizing: {err}")
                return None
            margin_usd = bal * (sizing["percent"] / 100.0)

        notional_usd = margin_usd * leverage
        min_notional = cfg.get("min_notional_usd", 10.0)
        if notional_usd < min_notional:
            notional_usd = min_notional  # exchange floor — orders below this are rejected outright

        base_amount = notional_usd / ref_price
        return round(base_amount, 6)

    async def manual_trade(self, symbol, side, override_usd=None,
                            leverage_override=None, sl_pct=1.5, tp_pct=3.0):
        """side: 'LONG' or 'SHORT'. Plain manual trade ticket — no agent involved.
        sl_pct/tp_pct are simple % distance from entry price (defaults: 1.5% / 3%)."""
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
            sl_dist = price * (sl_pct / 100.0)
            tp_dist = price * (tp_pct / 100.0)
            sl_price = price - sl_dist if side == "LONG" else price + sl_dist
            tp_price = price + tp_dist if side == "LONG" else price - tp_dist

            ok, result = await client.place_market_order_with_sl_tp(
                symbol, is_ask, base_amount, price, sl_price, tp_price
            )
            self.log(f"MANUAL {side} {symbol} amount={base_amount} leverage={leverage} "
                      f"price={price} sl={sl_price} tp={tp_price} -> ok={ok} result={result}")
            if ok:
                self._log_open(symbol, "Manual")
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
                    size = float(getattr(p, "position", 0) or 0)
                    if size != 0:
                        target = (p, size)
                        break
            if not target:
                return False, f"No open position on {symbol}"

            p, size = target
            price = await data_feed.get_live_price(symbol)
            if not price:
                return False, "Could not fetch live price"

            is_ask = size > 0  # closing a LONG needs a SELL; closing a SHORT needs a BUY
            ok, result = await client.close_position_market(symbol, is_ask=is_ask,
                                                              base_amount=abs(size), ref_price=price)
            self.log(f"CLOSE {symbol} size={size} -> ok={ok} result={result}")
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

    async def update_trailing_stops(self, client, live_positions):
        """Live equivalent of comp9/comp10's _update_trailing_stops(): moves the
        resting stop-loss to lock in profit as price moves favorably, using
        modify_order to update the trigger price in place — confirmed live to
        leave the paired take-profit order completely untouched. This is
        better than cancel+recreate: no window where the position is
        unprotected, and one tx instead of three. Same ATR trail formula as
        comp9: LONG new_sl = price - atr_mult*atr (only moves up), SHORT
        mirrors (only moves down).
        """
        pos_map = self.state.get("position_agent_map", {})
        for p in live_positions:
            symbol = getattr(p, "symbol", None)
            size = float(getattr(p, "position", 0) or 0)
            if not symbol or size == 0:
                continue

            mapping = pos_map.get(symbol)
            if not mapping:
                continue  # not opened by an agent we're tracking (e.g. a manual trade) — leave it alone

            agent = AGENTS.get(mapping["agent"])
            if not agent or agent.get("exit_mode") != "atr_trail":
                continue

            p_candles = await data_feed.get_candles(symbol, agent["timeframe"])
            if not p_candles or p_candles["n"] < 20 or "atr" not in p_candles:
                continue
            idx = p_candles["n"] - 2
            atr = p_candles["atr"][idx]
            if not atr or atr <= 0:
                continue

            price = await data_feed.get_live_price(symbol)
            if not price:
                continue

            side = "LONG" if size > 0 else "SHORT"
            atr_mult = agent["atr_sl_mult"]
            new_sl = price - atr_mult * atr if side == "LONG" else price + atr_mult * atr

            orders, err = await client.get_active_orders(market_id=MARKET_INDEX.get(symbol))
            if err:
                continue
            sl_order = next((o for o in orders if getattr(o, "type", "") == "stop-loss-limit"), None)
            if not sl_order:
                continue  # nothing resting to trail, or already closed

            current_sl = float(getattr(sl_order, "trigger_price", 0) or 0)
            favorable = (new_sl > current_sl) if side == "LONG" else (new_sl < current_sl)
            if not favorable:
                continue

            is_close_ask = (side == "LONG")  # closing a LONG is a SELL
            ok, result = await client.modify_stop_order(
                symbol, getattr(sl_order, "order_index"), new_sl, is_close_ask
            )
            if ok:
                self.log(f"Trailing stop {symbol}: {current_sl} -> {new_sl} (price={price})")
            else:
                self.log(f"Trailing stop modify FAILED for {symbol}, old SL still resting at "
                          f"{current_sl} (position remains protected, just not trailed this tick): {result}")

    async def run_tick(self):
        async with self._trade_lock:
            cfg = cfgmod.load_config()
            client = await self.ensure_client()

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
                if float(getattr(p, "position", 0) or 0) != 0
            }
            open_count = len(symbols_with_position)

            await self.update_trailing_stops(client, live_positions)

            for agent_name, acfg in cfg["agents"].items():
                if not acfg.get("enabled"):
                    continue

                agent = AGENTS.get(agent_name)
                if not agent:
                    continue

                direction = acfg.get("direction", "BOTH")
                sfn_long  = LONG_SIGNALS.get(agent_name)
                sfn_short = SHORT_SIGNALS.get(agent_name)

                for symbol in PAIRS:
                    if open_count >= cfg["max_open_positions"]:
                        break
                    if symbol in symbols_with_position:
                        continue  # already have a position on this symbol (any agent)

                    p = await data_feed.get_candles(symbol, agent["timeframe"])
                    if not p or p["n"] < 50:
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
                    price = await data_feed.get_live_price(symbol)
                    if not price:
                        self.log(f"No live price for {symbol}, skipping signal")
                        continue

                    leverage = cfg["leverage"].get(symbol, cfg["default_leverage"])
                    ok, lev_res = await client.set_leverage(symbol, leverage)
                    if not ok:
                        self.log(f"Leverage set failed for {symbol} @ {leverage}x: {lev_res} — skipping trade")
                        continue

                    base_amount = await self._compute_size(symbol, leverage, price, cfg)
                    if base_amount is None:
                        continue

                    is_ask = (side == "SHORT")
                    sl_dist = agent["atr_sl_mult"] * p["atr"][idx]
                    tp_dist = agent["atr_tp_mult"] * p["atr"][idx]
                    sl_price = price - sl_dist if side == "LONG" else price + sl_dist
                    tp_price = price + tp_dist if side == "LONG" else price - tp_dist

                    ok, result = await client.place_market_order_with_sl_tp(
                        symbol, is_ask, base_amount, price, sl_price, tp_price
                    )
                    self.log(f"{agent_name} SIGNAL {side} {symbol} amount={base_amount} "
                              f"price={price} sl={sl_price} tp={tp_price} -> ok={ok} result={result}")

                    if ok:
                        symbols_with_position.add(symbol)
                        open_count += 1
                        self.state["position_agent_map"][symbol] = {"agent": agent_name}
                        self._log_open(symbol, agent_name)
                        _save_state(self.state)

            # Drop mapping entries for symbols that no longer have a live position
            # (closed via SL/TP fill, manual close, etc.) so trailing doesn't act
            # on stale data next tick.
            for sym in list(self.state["position_agent_map"].keys()):
                if sym not in symbols_with_position:
                    del self.state["position_agent_map"][sym]
            _save_state(self.state)


engine = LighterBotEngine()
