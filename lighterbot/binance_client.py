"""
Binance USDT-M Futures client — mirrors LighterClient's exact public
interface (method names, argument shapes, return-value shapes) so engine.py
can use either client interchangeably via config["platform"]. Every position/
order object returned here is normalized into the SAME shape LighterClient's
SDK objects have (symbol/position/sign for positions; type/market_index/
trigger_price/order_index/status/timestamp for orders) so signed_position_size()
and every existing engine.py call site work completely unchanged regardless
of platform.

Raw REST + HMAC-SHA256 signing (no extra dependency) via aiohttp, which is
already a transitive dependency of this project.

IMPORTANT DIFFERENCES FROM LIGHTER, read before enabling live:
1. Binance has no atomic in-place stop-order modification — modify_stop_order
   here is cancel-then-recreate (two separate requests), unlike Lighter's
   single-transaction modify. There is a brief real window between the two
   calls where the old stop is gone and the new one isn't resting yet. The
   engine's own check_for_tracked_gap_positions safety net (20s persistence
   threshold) is more than enough headroom for this — a cancel+recreate pair
   completes in well under a second — but it is a different risk profile
   than Lighter's gapless modify, worth knowing about explicitly.
2. Binance futures has no native OCO order type the way Lighter's
   create_grouped_orders does. SL/TP here are placed as two INDEPENDENT
   conditional orders, each with closePosition=true — Binance's own
   mechanism for exactly this case: a closePosition order closes whatever
   size exists when triggered and is a no-op (auto-cancelled) if the
   position is already flat by the time it fires, so a SL firing first can't
   leave a stray TP order that reopens a position later. This is
   Binance-idiomatic and functionally equivalent to Lighter's OCO for this
   bot's purposes, but isn't literally the same order type.
3. Binance made a MANDATORY breaking change effective 2025-12-09: conditional
   order types (STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT,
   TRAILING_STOP_MARKET) were migrated to a separate "Algo Order" service.
   Submitting them via the classic POST/DELETE/GET /fapi/v1/order endpoints
   now fails with error -4120 ("Order type not supported for this endpoint.
   Please use the Algo Order API endpoints instead.") — confirmed live on
   2026-08 when a real AVAX trade's SL/TP attach failed with exactly this
   error (position was safely auto-flattened by the existing failure-handling
   logic, no funds lost). Fixed by routing all conditional SL/TP/trailing
   orders through POST/DELETE/GET /fapi/v1/algoOrder and
   GET /fapi/v1/openAlgoOrders instead — see _place_close_position_stop,
   cancel_order, get_active_orders, modify_stop_order below. Plain MARKET
   entry/close orders are UNAFFECTED by this migration and still use the
   classic /fapi/v1/order endpoint.
"""
import asyncio, os, re, time, hmac, hashlib, urllib.parse
from types import SimpleNamespace

import aiohttp

# Shared across all BinanceClient instances (see class docstring below) —
# sar 2026-08-08: a fee-backfill script hammered /fapi/v1/income and tripped
# Binance's IP-level 418 ban; the bot's own normal ~10s polling loop then kept
# hitting the API *while already banned*, and each such hit pushed Binance's
# reported "banned until" timestamp further out, extending the ban
# indefinitely instead of letting it expire. This guard makes every
# _request() check the ban clock BEFORE making any network call at all, so
# a live ban is respected (zero further hits) instead of being self-extended.
_rate_limit_banned_until_ms = 0.0
_BAN_RE = re.compile(r"banned until (\d+)")


MARKET_INDEX = {
    "ETH": "ETHUSDT", "BTC": "BTCUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT",
    "LINK": "LINKUSDT", "AVAX": "AVAXUSDT", "DOT": "DOTUSDT", "POL": "POLUSDT",
    "BNB": "BNBUSDT", "ADA": "ADAUSDT",
}
SYMBOL_TO_SHORT = {v: k for k, v in MARKET_INDEX.items()}

# Fallback only — real values fetched live from the public (no-auth)
# exchangeInfo endpoint on client startup and refreshed periodically, exactly
# like LighterClient.refresh_max_leverage(). Never trust these for an actual
# live order — they exist purely so the bot doesn't crash before the first
# successful refresh.
PRICE_DECIMALS_FALLBACK = {
    "ETH": 2, "BTC": 1, "SOL": 3, "XRP": 4, "LINK": 3,
    "AVAX": 3, "DOT": 3, "POL": 5, "BNB": 2, "ADA": 4,
}
SIZE_DECIMALS_FALLBACK = {
    "ETH": 3, "BTC": 3, "SOL": 2, "XRP": 1, "LINK": 2,
    "AVAX": 1, "DOT": 1, "POL": 0, "BNB": 3, "ADA": 0,
}
MIN_NOTIONAL_FALLBACK = 5.0
MAX_LEVERAGE_FALLBACK = {
    "BTC": 125, "ETH": 100, "SOL": 50, "XRP": 50, "BNB": 50,
    "LINK": 50, "DOT": 50, "AVAX": 50, "ADA": 50, "POL": 25,
}
SYMBOL_INFO_REFRESH_SECONDS = 300

BASE_URL_LIVE = "https://fapi.binance.com"
BASE_URL_TESTNET = "https://testnet.binancefuture.com"


def signed_position_size(p) -> float:
    """Same contract as lighter_client.signed_position_size — works
    identically here because get_open_positions() below normalizes every
    position into this exact {position: magnitude-string, sign: +-1} shape."""
    magnitude = float(getattr(p, "position", 0) or 0)
    sign = float(getattr(p, "sign", 1) or 1)
    return magnitude * sign


class BinanceClient:
    def __init__(self):
        # Missing credentials set client_check_error instead of raising —
        # same graceful-degradation pattern as LighterClient, so the
        # dashboard/config can still load and show a clear status message
        # instead of crashing the whole engine if platform="binance" is
        # selected before keys are actually added to .env.
        self.api_key = os.environ.get("BINANCE_API_KEY", "")
        self.api_secret = os.environ.get("BINANCE_API_SECRET", "")
        self.testnet = os.environ.get("BINANCE_TESTNET", "false").lower() == "true"
        self.base_url = BASE_URL_TESTNET if self.testnet else BASE_URL_LIVE
        self.client_check_error = (
            "BINANCE_API_KEY/BINANCE_API_SECRET not set in .env — add them before trading on Binance"
            if not (self.api_key and self.api_secret) else None
        )

        self.MARKET_INDEX = dict(MARKET_INDEX)
        self.PRICE_DECIMALS = dict(PRICE_DECIMALS_FALLBACK)
        self.SIZE_DECIMALS = dict(SIZE_DECIMALS_FALLBACK)
        self.MIN_BASE_AMOUNT = {}  # filled in by refresh_symbol_info from minQty
        self.min_notional_usd = MIN_NOTIONAL_FALLBACK
        self.max_leverage_cache = dict(MAX_LEVERAGE_FALLBACK)
        self.symbol_info_last_refresh = 0.0

    # ── Low-level signed/unsigned request helpers ───────────────────────────
    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urllib.parse.urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _request(self, method: str, path: str, params: dict = None, signed: bool = True):
        global _rate_limit_banned_until_ms
        now_ms = time.time() * 1000
        if now_ms < _rate_limit_banned_until_ms:
            remaining = (_rate_limit_banned_until_ms - now_ms) / 1000
            return None, (f"Skipping request — IP rate-limit ban active for another "
                           f"{remaining:.0f}s (no network call made, avoids extending the ban further)")
        params = params or {}
        headers = {"X-MBX-APIKEY": self.api_key} if signed else {}
        if signed:
            params = self._sign(params)
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        text = str(data)
                        m = _BAN_RE.search(text)
                        if m:
                            _rate_limit_banned_until_ms = max(_rate_limit_banned_until_ms, float(m.group(1)))
                        return None, f"HTTP {resp.status}: {data}"
                    return data, None
        except Exception as e:
            return None, str(e)

    # ── Symbol info / leverage ───────────────────────────────────────────────
    def get_max_leverage(self, symbol: str) -> int:
        return self.max_leverage_cache.get(symbol, MAX_LEVERAGE_FALLBACK.get(symbol, 1))

    async def refresh_max_leverage(self, force: bool = False):
        """Alias kept for interface parity with LighterClient — Binance
        bundles leverage brackets and precision into the same refresh."""
        return await self.refresh_symbol_info(force=force)

    async def refresh_symbol_info(self, force: bool = False):
        """Pulls live price/quantity precision and min notional from the
        PUBLIC (no-auth) exchangeInfo endpoint, and max leverage from the
        account's own leverage-bracket endpoint (requires auth). Cached for
        SYMBOL_INFO_REFRESH_SECONDS. Never wipes the cache on failure — same
        philosophy as LighterClient.refresh_max_leverage."""
        now = time.time()
        if not force and (now - self.symbol_info_last_refresh) < SYMBOL_INFO_REFRESH_SECONDS:
            return True, None
        try:
            data, err = await self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
            if err:
                return False, err
            updated_price, updated_size, updated_min_qty = {}, {}, {}
            for s in data.get("symbols", []):
                sym = SYMBOL_TO_SHORT.get(s.get("symbol"))
                if not sym:
                    continue
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = f.get("tickSize", "0.01")
                        updated_price[sym] = max(0, -self._exp10(tick))
                    if f.get("filterType") == "LOT_SIZE":
                        step = f.get("stepSize", "0.001")
                        updated_size[sym] = max(0, -self._exp10(step))
                        updated_min_qty[sym] = float(f.get("minQty", 0))
            if updated_price:
                self.PRICE_DECIMALS.update(updated_price)
                self.SIZE_DECIMALS.update(updated_size)
                self.MIN_BASE_AMOUNT.update(updated_min_qty)
                self.symbol_info_last_refresh = now

            brackets, berr = await self._request("GET", "/fapi/v1/leverageBracket", signed=True)
            if not berr and isinstance(brackets, list):
                updated_lev = {}
                for b in brackets:
                    sym = SYMBOL_TO_SHORT.get(b.get("symbol"))
                    if not sym:
                        continue
                    tiers = b.get("brackets", [])
                    if tiers:
                        updated_lev[sym] = int(tiers[0].get("initialLeverage", MAX_LEVERAGE_FALLBACK.get(sym, 1)))
                if updated_lev:
                    self.max_leverage_cache.update(updated_lev)
            return True, {"price_decimals": self.PRICE_DECIMALS, "leverage": self.max_leverage_cache}
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _exp10(decimal_str: str) -> int:
        """'0.0010' -> -3 (i.e. 3 decimal places). Avoids float rounding
        issues from log10 on strings like '0.00001000'."""
        s = decimal_str.rstrip("0")
        if "." not in s:
            return 0
        return -len(s.split(".")[1])

    async def set_leverage(self, symbol: str, leverage: int):
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        await self.refresh_symbol_info()
        max_lev = self.get_max_leverage(symbol)
        if leverage > max_lev:
            return False, f"Requested {leverage}x exceeds {symbol}'s live max of {max_lev}x"
        data, err = await self._request("POST", "/fapi/v1/leverage",
                                         {"symbol": binance_symbol, "leverage": leverage})
        if err:
            return False, err
        return True, data

    # ── Read-only ────────────────────────────────────────────────────────────
    async def get_balance_usd(self):
        """totalMarginBalance = cash + open position value + unrealized PnL —
        the mark-to-market equivalent of LighterClient.get_balance_usd, not
        just uncommitted/free cash (same reasoning: available balance alone
        understates the account whenever a position is open)."""
        data, err = await self._request("GET", "/fapi/v2/account")
        if err:
            return None, err
        try:
            return float(data["totalMarginBalance"]), None
        except (KeyError, ValueError) as e:
            return None, f"Could not find balance field: {e}. Full record: {data}"

    async def get_open_positions(self):
        """Normalizes Binance's positionRisk entries into Lighter's exact
        {symbol, position (magnitude string), sign} shape so
        signed_position_size() and every engine.py caller work unchanged."""
        data, err = await self._request("GET", "/fapi/v2/positionRisk")
        if err:
            return [], err
        try:
            positions = []
            for p in data:
                amt = float(p.get("positionAmt", 0) or 0)
                sym = SYMBOL_TO_SHORT.get(p.get("symbol"))
                if not sym:
                    continue
                positions.append(SimpleNamespace(
                    symbol=sym,
                    position=str(abs(amt)),
                    sign=1 if amt >= 0 else -1,
                    avg_entry_price=float(p.get("entryPrice", 0) or 0),
                    mark_price=float(p.get("markPrice", 0) or 0),
                    unrealized_pnl=float(p.get("unRealizedProfit", 0) or 0),
                    leverage=int(float(p.get("leverage", 0) or 0)) or None,
                ))
            return positions, None
        except Exception as e:
            return [], str(e)

    @staticmethod
    def _normalize_order_type(binance_type: str) -> str:
        """Maps Binance's order-type vocabulary onto Lighter's exact strings
        so every existing engine.py check like
        `getattr(o, "type", "") in ("stop-loss-limit", "take-profit-limit")`
        keeps working unmodified regardless of platform."""
        if binance_type in ("STOP_MARKET", "STOP"):
            return "stop-loss-limit"
        if binance_type in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
            return "take-profit-limit"
        return binance_type

    def _normalize_order(self, o: dict):
        """Handles BOTH response shapes: classic /fapi/v1/order orders
        (orderId/type/stopPrice/status) and the newer /fapi/v1/algoOrder
        conditional orders (algoId/orderType/triggerPrice/algoStatus) — SL/TP
        now always come from the algo endpoints (see module docstring #3),
        but this stays defensive about field names since Binance's
        list-vs-create response shapes aren't guaranteed identical."""
        order_type = o.get("orderType") or o.get("type", "")
        return SimpleNamespace(
            type=self._normalize_order_type(order_type),
            market_index=o.get("symbol"),  # same value MARKET_INDEX.get(short_symbol) returns — consistent grouping key
            trigger_price=float(o.get("triggerPrice") or o.get("stopPrice") or 0),
            order_index=o.get("algoId") if o.get("algoId") is not None else o.get("orderId"),
            status=(o.get("algoStatus") or o.get("status") or "").lower() or None,
            timestamp=int(o.get("time") or o.get("updateTime") or o.get("createTime") or 0) / 1000.0,
            is_ask=(o.get("side") == "SELL"),
            reduce_only=bool(o.get("reduceOnly") or o.get("closePosition")),
            price=float(o.get("price", 0) or 0),
            filled_base_amount=float(o.get("executedQty", 0) or 0),
            filled_quote_amount=float(o.get("cumQuote", 0) or 0),
        )

    async def get_active_orders(self, market_id: str = None):
        """market_id here is the FULL Binance symbol string (e.g. 'BTCUSDT') —
        the same value self.MARKET_INDEX.get(short_symbol) returns, kept
        consistent with how engine.py already calls this (passing whatever
        MARKET_INDEX.get(symbol) returned) regardless of platform.

        Queries BOTH /fapi/v1/openAlgoOrders (conditional SL/TP/trailing-stop
        orders THIS BOT places via the API — see module docstring #3) AND the
        classic /fapi/v1/openOrders. Confirmed live: a conditional SL/TP
        added through Binance's own WEBSITE ("TP/SL for position" inline
        editor) is submitted through the CLASSIC endpoint, not the Algo Order
        API — so a manually-added stop was completely invisible to a
        single-endpoint check, and the bot's own safety nets
        (check_for_unprotected_positions/check_for_tracked_gap_positions)
        would have wrongly concluded a fully-protected position was naked
        and flattened it. Querying both sources and merging is the only way
        to see everything actually resting on the account regardless of
        which channel placed it."""
        params = {"symbol": market_id} if market_id else {}
        algo_data, algo_err = await self._request("GET", "/fapi/v1/openAlgoOrders", params)
        classic_data, classic_err = await self._request("GET", "/fapi/v1/openOrders", params)
        if algo_err and classic_err:
            return [], f"algo: {algo_err}; classic: {classic_err}"
        try:
            orders = []
            if not algo_err:
                orders.extend(algo_data.get("orders", algo_data) if isinstance(algo_data, dict) else algo_data)
            if not classic_err:
                orders.extend(classic_data)
            return [self._normalize_order(o) for o in orders], None
        except Exception as e:
            return [], str(e)

    async def get_inactive_orders(self, limit: int = 100, cursor: str = None):
        """Binance's allOrders is paginated by orderId (cursor), not an opaque
        token like Lighter's — `cursor` here, if provided, is the last seen
        orderId to page backward from. Returns (orders, next_cursor, error)
        matching LighterClient's exact shape."""
        params = {"limit": min(limit, 1000)}
        if cursor:
            params["orderId"] = cursor
        data, err = await self._request("GET", "/fapi/v1/allOrders", params)
        if err:
            return [], None, err
        try:
            orders = [self._normalize_order(o) for o in data]
            next_cursor = data[0].get("orderId") - 1 if data else None
            return orders, next_cursor, None
        except Exception as e:
            return [], None, str(e)

    async def get_income_history(self, income_type: str, symbol: str = None,
                                   start_time_ms: int = None, end_time_ms: int = None,
                                   limit: int = 1000):
        """Wraps /fapi/v1/income (read-only, no auth risk) — used to attach
        real trading fees to closed-trade history. income_type is Binance's
        own vocabulary ('COMMISSION', 'FUNDING_FEE', ...). symbol filters to
        one pair; omit to fetch the whole account for a time window. Returns
        (entries, error) where entries are the raw Binance dicts (each has
        'income' as a signed string and 'time' in ms) — caller sums them."""
        params = {"incomeType": income_type, "limit": min(limit, 1000)}
        if symbol:
            binance_symbol = self.MARKET_INDEX.get(symbol, symbol)
            params["symbol"] = binance_symbol
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        data, err = await self._request("GET", "/fapi/v1/income", params)
        if err:
            return [], err
        return data, None

    async def _describe_fill_failure(self, binance_symbol: str, base_amount: float, actual_filled: float) -> str:
        """Same purpose as LighterClient's version: report the REAL rejection
        reason from the exchange instead of guessing, using the most recent
        order for this symbol."""
        try:
            orders, err = await self._request("GET", "/fapi/v1/allOrders", {"symbol": binance_symbol, "limit": 5})
            if not err and orders:
                latest = max(orders, key=lambda o: o.get("time", 0))
                status = latest.get("status")
                if status and status != "FILLED":
                    return (f"order rejected by exchange: status={status} "
                            f"(intended {base_amount}, actual change {actual_filled})")
        except Exception:
            pass
        return (f"order accepted but did not fill as expected "
                f"(intended {base_amount}, actual change {actual_filled}) — "
                f"likely price moved past the slippage tolerance before matching")

    async def cancel_order(self, symbol: str, order_index):
        """order_index cancels a conditional SL/TP order — but which
        endpoint owns it depends on WHERE it was placed, not who's
        cancelling it: this bot's own orders are algoId (Algo Order API),
        while one added through Binance's website UI is a classic orderId
        (confirmed live — see get_active_orders' docstring). Tries the algo
        endpoint first (the common case for this bot's own orders), and
        falls back to the classic endpoint if that fails — rather than
        requiring every caller to know and pass which type it is."""
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        data, err = await self._request("DELETE", "/fapi/v1/algoOrder", {"algoId": order_index})
        if err is None:
            return True, data
        classic_data, classic_err = await self._request(
            "DELETE", "/fapi/v1/order", {"symbol": binance_symbol, "orderId": order_index})
        if classic_err is None:
            return True, classic_data
        return False, f"algo cancel failed: {err}; classic cancel failed: {classic_err}"

    async def modify_stop_order(self, symbol: str, order_index, new_trigger_price: float,
                                  is_close_ask: bool, fill_buffer_pct: float = 0.5):
        """Binance has NO atomic in-place stop modification — this is
        cancel-then-recreate (see module docstring for the resulting brief
        real gap, which the engine's tracked-gap safety net comfortably
        covers). Recreated as the SAME closePosition=true STOP_MARKET type
        the original was, at the new trigger price."""
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        cancel_ok, cancel_result = await self.cancel_order(symbol, order_index)
        if not cancel_ok:
            return False, f"cancel step failed: {cancel_result}"
        price_dec = self.PRICE_DECIMALS.get(symbol, 4)
        side = "SELL" if is_close_ask else "BUY"
        data, err = await self._request("POST", "/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": binance_symbol, "side": side, "type": "STOP_MARKET",
            "triggerPrice": round(new_trigger_price, price_dec),
            "closePosition": "true",
        })
        if err:
            return False, f"recreate step failed (old stop already cancelled — position may be briefly unprotected): {err}"
        return True, data

    # ── Orders ────────────────────────────────────────────────────────────────
    async def _market_order(self, binance_symbol: str, side: str, quantity: float, reduce_only: bool = False):
        params = {"symbol": binance_symbol, "side": side, "type": "MARKET", "quantity": quantity}
        if reduce_only:
            params["reduceOnly"] = "true"
        return await self._request("POST", "/fapi/v1/order", params)

    async def _place_close_position_stop(self, binance_symbol: str, order_type: str, side: str, stop_price: float, price_dec: int):
        """Conditional order (SL/TP) — must go through the Algo Order API
        (see module docstring #3), not the classic /fapi/v1/order. Requires
        an ACTUAL open position on binance_symbol to accept a closePosition
        order; will reject with -4509 otherwise (confirmed live) — that's
        correct/expected, not a bug, since "close position" is meaningless
        without one."""
        return await self._request("POST", "/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": binance_symbol, "side": side, "type": order_type,
            "triggerPrice": round(stop_price, price_dec), "closePosition": "true",
        })

    async def place_market_order_with_sl_tp(self, symbol: str, is_ask: bool,
                                              base_amount: float, ref_price: float,
                                              sl_price: float, tp_price: float,
                                              size_before_hint: float = None):
        """is_ask=False -> BUY (long), is_ask=True -> SELL (short). Places a
        market entry, verifies the fill actually happened (same before/after
        position-size check as LighterClient, since a MARKET order can be
        accepted but reject for insufficient margin without raising), then
        attaches SL/TP as two independent closePosition=true conditional
        orders (see module docstring on why this is Binance's OCO
        equivalent). If either attach fails, flattens immediately rather
        than leave a real position unprotected.

        size_before_hint: skips the "before" get_open_positions() call if the
        caller already knows the current size from moments earlier in the
        same locked section — see lighter_client.py's identical parameter
        for the full reasoning. Cuts a real network round-trip off every
        trade's latency."""
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"

        min_base = self.MIN_BASE_AMOUNT.get(symbol, 0)
        if base_amount < min_base:
            return False, f"base_amount {base_amount} below exchange minimum {min_base} for {symbol}"
        notional = base_amount * ref_price
        if notional < self.min_notional_usd - 0.01:
            return False, f"notional ${notional:.2f} below exchange minimum ${self.min_notional_usd}"

        size_dec = self.SIZE_DECIMALS.get(symbol, 3)
        price_dec = self.PRICE_DECIMALS.get(symbol, 4)
        qty = round(base_amount, size_dec)

        if size_before_hint is not None:
            size_before = size_before_hint
        else:
            before_positions, before_err = await self.get_open_positions()
            size_before = 0.0
            if not before_err:
                existing = next((p for p in before_positions if p.symbol == symbol), None)
                size_before = signed_position_size(existing) if existing is not None else 0.0

        side = "SELL" if is_ask else "BUY"
        data, err = await self._market_order(binance_symbol, side, qty)
        if err:
            return False, f"entry order failed: {err}"

        actual_filled = 0.0
        # Tighter than LighterClient's (0, 0.5, 1.0, 2.0) schedule DELIBERATELY:
        # that longer backoff exists because of a confirmed real zk-rollup
        # propagation lag on Lighter specifically (a genuine fill took up to
        # 30+s to show up there). Binance's centralized matching engine
        # reflects fills in its position endpoint dramatically faster —
        # confirmed live (the SOL trade filled and was visible on the very
        # first, zero-delay check). Still retries on a genuine delay, just
        # checks sooner, so a real slow fill is still caught correctly.
        for attempt, delay in enumerate((0, 0.15, 0.4, 1.0)):
            if delay:
                await asyncio.sleep(delay)
            after_positions, after_err = await self.get_open_positions()
            if after_err:
                continue
            existing_after = next((p for p in after_positions if p.symbol == symbol), None)
            size_after = signed_position_size(existing_after) if existing_after is not None else 0.0
            actual_filled = abs(size_after - size_before)
            if actual_filled >= base_amount * 0.5:
                break
        if actual_filled < base_amount * 0.5:
            return False, await self._describe_fill_failure(binance_symbol, base_amount, actual_filled)

        close_side = "SELL" if not is_ask else "BUY"  # closing side is opposite the entry side
        # TP and SL are two INDEPENDENT requests (neither depends on the
        # other's result) -- placing them concurrently instead of one after
        # another cuts a full network round-trip off every trade's latency
        # with no change in behavior or safety.
        (tp_data, tp_err), (sl_data, sl_err) = await asyncio.gather(
            self._place_close_position_stop(binance_symbol, "TAKE_PROFIT_MARKET", close_side, tp_price, price_dec),
            self._place_close_position_stop(binance_symbol, "STOP_MARKET", close_side, sl_price, price_dec),
        )
        if tp_err or sl_err:
            await self.close_position_market(symbol, is_ask=not is_ask, base_amount=base_amount, ref_price=ref_price)
            return False, f"SL/TP attach failed, position flattened: tp_err={tp_err} sl_err={sl_err}"
        return True, {"entry": data, "tp": tp_data, "sl": sl_data}

    async def add_to_position_market(self, symbol: str, is_ask: bool, base_amount: float, ref_price: float):
        """Increases an already-open position — deliberately does NOT touch
        existing SL/TP orders: both are closePosition=true (close whatever
        size exists at trigger time), so they automatically cover the new,
        larger combined position with no modification needed, same semantics
        as LighterClient's BaseAmount=0 position-tied orders."""
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"

        min_base = self.MIN_BASE_AMOUNT.get(symbol, 0)
        if base_amount < min_base:
            return False, f"base_amount {base_amount} below exchange minimum {min_base} for {symbol}"
        notional = base_amount * ref_price
        if notional < self.min_notional_usd - 0.01:
            return False, f"notional ${notional:.2f} below exchange minimum ${self.min_notional_usd}"

        size_dec = self.SIZE_DECIMALS.get(symbol, 3)
        qty = round(base_amount, size_dec)

        before_positions, before_err = await self.get_open_positions()
        size_before = 0.0
        if not before_err:
            existing = next((p for p in before_positions if p.symbol == symbol), None)
            size_before = signed_position_size(existing) if existing is not None else 0.0

        side = "SELL" if is_ask else "BUY"
        data, err = await self._market_order(binance_symbol, side, qty)
        if err:
            return False, f"add-to-position entry failed: {err}"

        actual_filled = 0.0
        # Tighter than LighterClient's (0, 0.5, 1.0, 2.0) schedule DELIBERATELY:
        # that longer backoff exists because of a confirmed real zk-rollup
        # propagation lag on Lighter specifically (a genuine fill took up to
        # 30+s to show up there). Binance's centralized matching engine
        # reflects fills in its position endpoint dramatically faster —
        # confirmed live (the SOL trade filled and was visible on the very
        # first, zero-delay check). Still retries on a genuine delay, just
        # checks sooner, so a real slow fill is still caught correctly.
        for attempt, delay in enumerate((0, 0.15, 0.4, 1.0)):
            if delay:
                await asyncio.sleep(delay)
            after_positions, after_err = await self.get_open_positions()
            if after_err:
                continue
            existing_after = next((p for p in after_positions if p.symbol == symbol), None)
            size_after = signed_position_size(existing_after) if existing_after is not None else 0.0
            actual_filled = abs(size_after - size_before)
            if actual_filled >= base_amount * 0.5:
                break
        if actual_filled < base_amount * 0.5:
            return False, await self._describe_fill_failure(binance_symbol, base_amount, actual_filled)
        return True, {"entry": data, "filled": actual_filled}

    async def attach_sl_tp(self, symbol: str, is_ask: bool, sl_price: float, tp_price: float,
                            client_order_seed: int = None):
        """Attaches OCO-equivalent SL/TP to an EXISTING position (no new
        entry order) — used for the initial bracket and for re-attaching
        after a moved trailing stop."""
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = self.PRICE_DECIMALS.get(symbol, 4)
        close_side = "SELL" if not is_ask else "BUY"
        (tp_data, tp_err), (sl_data, sl_err) = await asyncio.gather(
            self._place_close_position_stop(binance_symbol, "TAKE_PROFIT_MARKET", close_side, tp_price, price_dec),
            self._place_close_position_stop(binance_symbol, "STOP_MARKET", close_side, sl_price, price_dec),
        )
        if tp_err or sl_err:
            return False, f"tp_err={tp_err} sl_err={sl_err}"
        return True, {"tp": tp_data, "sl": sl_data}

    async def attach_catastrophic_sl(self, symbol: str, is_ask: bool, sl_price: float,
                                       client_order_seed: int = None):
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = self.PRICE_DECIMALS.get(symbol, 4)
        close_side = "SELL" if not is_ask else "BUY"
        data, err = await self._place_close_position_stop(binance_symbol, "STOP_MARKET", close_side, sl_price, price_dec)
        if err:
            return False, err
        return True, data

    async def attach_real_tp(self, symbol: str, is_ask: bool, tp_price: float,
                               client_order_seed: int = None):
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = self.PRICE_DECIMALS.get(symbol, 4)
        close_side = "SELL" if not is_ask else "BUY"
        data, err = await self._place_close_position_stop(binance_symbol, "TAKE_PROFIT_MARKET", close_side, tp_price, price_dec)
        if err:
            return False, err
        return True, data

    async def close_position_market(self, symbol: str, is_ask: bool, base_amount: float,
                                      ref_price: float, slippage_pct: float = 1.0):
        binance_symbol = self.MARKET_INDEX.get(symbol)
        if binance_symbol is None:
            return False, f"Unknown symbol {symbol}"
        size_dec = self.SIZE_DECIMALS.get(symbol, 3)
        side = "SELL" if is_ask else "BUY"
        data, err = await self._market_order(binance_symbol, side, round(base_amount, size_dec), reduce_only=True)
        return (err is None), (data or err)
