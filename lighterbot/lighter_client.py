"""
Thin wrapper around the official `lighter-sdk` (pip install lighter-sdk).
Every call that touches real money is wrapped in try/except and returns a
structured (ok, result_or_error) tuple instead of raising — the engine logs
failures and skips the trade rather than crashing or retrying blindly.
"""
import os, time, inspect, asyncio

try:
    import lighter
    from lighter.signer_client import CreateOrderTxReq
except ImportError:
    lighter = None  # allows the dashboard/config to load even before `pip install lighter-sdk`
    CreateOrderTxReq = None


async def _call(fn, *args, **kwargs):
    """Call an SDK method that may be sync or async depending on SDK version —
    avoids hardcoding an assumption that breaks on a version mismatch."""
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


# All 10 confirmed live via /api/v1/orderBookDetails on 2026-07-01 — matches
# the pairs list used by paper9/paper11 agents (COMP9_PAIRS).
MARKET_INDEX = {
    "ETH": 0, "BTC": 1, "SOL": 2, "XRP": 7, "LINK": 8,
    "AVAX": 9, "DOT": 11, "POL": 14, "BNB": 25, "ADA": 39,
}
MIN_BASE_AMOUNT = {
    "ETH": 0.0050, "BTC": 0.00020, "SOL": 0.050, "XRP": 20, "LINK": 1.0,
    "AVAX": 0.50, "DOT": 2.0, "POL": 40, "BNB": 0.02, "ADA": 10.0,
}
PRICE_DECIMALS = {
    "ETH": 2, "BTC": 1, "SOL": 3, "XRP": 6, "LINK": 5,
    "AVAX": 4, "DOT": 5, "POL": 6, "BNB": 4, "ADA": 5,
}
# From live orderBookDetails (size_decimals) — the SDK wants base_amount and
# price as scaled integers, not floats.
SIZE_DECIMALS = {
    "ETH": 4, "BTC": 5, "SOL": 3, "XRP": 0, "LINK": 1,
    "AVAX": 2, "DOT": 1, "POL": 0, "BNB": 2, "ADA": 1,
}
# Fallback only — used before the first live fetch succeeds, or if a live
# refresh fails. The real values are fetched from Lighter on client startup
# and refreshed periodically; see LighterClient.refresh_max_leverage().
MAX_LEVERAGE_FALLBACK = {
    "BTC": 50, "ETH": 50, "SOL": 25, "XRP": 20, "BNB": 20,
    "LINK": 10, "DOT": 10, "AVAX": 10, "ADA": 10, "POL": 8,
}
MAX_LEVERAGE_REFRESH_SECONDS = 300  # re-check every 5 minutes
MIN_NOTIONAL_USD = 10.0


def to_scaled_int(value: float, decimals: int) -> int:
    return int(round(value * (10 ** decimals)))


def signed_position_size(p) -> float:
    """Lighter's `position` field is always a positive magnitude — direction
    is a SEPARATE `sign` field (-1 for SHORT, 1 for LONG). Reading `position`
    alone and assuming positive=LONG is wrong and silently sends closes in
    the wrong direction for shorts (confirmed live: a 'successful' close on a
    SHORT position did nothing because it sent a SELL instead of a BUY)."""
    magnitude = float(getattr(p, "position", 0) or 0)
    sign = float(getattr(p, "sign", 1) or 1)
    return magnitude * sign


class LighterClient:
    def __init__(self):
        self.base_url   = os.environ["LIGHTER_BASE_URL"]
        self.account_index = int(os.environ["LIGHTER_ACCOUNT_INDEX"])
        self.api_key_index = int(os.environ["LIGHTER_API_KEY_INDEX"])
        self.private_key   = os.environ["LIGHTER_API_PRIVATE_KEY"]

        if lighter is None:
            raise RuntimeError("lighter-sdk not installed. Run: pip install lighter-sdk")

        self.signer = lighter.SignerClient(
            url=self.base_url,
            api_private_keys={self.api_key_index: self.private_key},
            account_index=self.account_index,
        )
        self.api_client = lighter.ApiClient(
            configuration=lighter.Configuration(host=self.base_url)
        )
        self.account_api = lighter.AccountApi(self.api_client)
        self.order_api   = lighter.OrderApi(self.api_client)

        # Validates the API key is actually registered on-chain for this
        # account. Skipping this is what produces "invalid signature" (21120)
        # on every signed request instead of a clear error up front.
        check_err = self.signer.check_client()
        self.client_check_error = str(check_err) if check_err else None

        # Max leverage per symbol — fetched live below, this is just the seed
        # value used until the first successful refresh completes.
        self.max_leverage_cache = dict(MAX_LEVERAGE_FALLBACK)
        self.max_leverage_last_refresh = 0.0

        # Instance-level mirrors of the module constants above — lets
        # engine.py call client.MARKET_INDEX/client.PRICE_DECIMALS/etc
        # identically regardless of whether client is a LighterClient or a
        # BinanceClient, instead of importing platform-specific constants
        # directly (which would make the platform switch not actually work).
        self.MARKET_INDEX = MARKET_INDEX
        self.PRICE_DECIMALS = PRICE_DECIMALS
        self.SIZE_DECIMALS = SIZE_DECIMALS
        self.MIN_BASE_AMOUNT = MIN_BASE_AMOUNT
        self.min_notional_usd = MIN_NOTIONAL_USD

    def get_max_leverage(self, symbol: str) -> int:
        return self.max_leverage_cache.get(symbol, MAX_LEVERAGE_FALLBACK.get(symbol, 1))

    async def refresh_max_leverage(self, force: bool = False):
        """Pulls min_initial_margin_fraction per market from Lighter's public
        orderBookDetails endpoint and recomputes max_leverage = 10000 / fraction.
        Cached for MAX_LEVERAGE_REFRESH_SECONDS so this isn't hit every tick."""
        now = time.time()
        if not force and (now - self.max_leverage_last_refresh) < MAX_LEVERAGE_REFRESH_SECONDS:
            return True, None
        try:
            res = await _call(self.order_api.order_book_details, market_id=255, filter="perp")
            markets = getattr(res, "order_book_details", None) or []
            symbol_by_market_index = {v: k for k, v in MARKET_INDEX.items()}
            updated = {}
            for m in markets:
                market_id = getattr(m, "market_id", None)
                symbol = symbol_by_market_index.get(market_id)
                if symbol is None:
                    continue
                frac = getattr(m, "min_initial_margin_fraction", None)
                if frac:
                    updated[symbol] = int(10_000 // frac)
            if updated:
                self.max_leverage_cache.update(updated)
                self.max_leverage_last_refresh = now
                return True, updated
            return False, "No matching markets in orderBookDetails response"
        except Exception as e:
            # Keep the last known-good values on failure — never wipe the cache.
            return False, str(e)

    # ── Read-only ──────────────────────────────────────────────────────────
    async def get_account_raw(self):
        """Raw account() response — used by the startup self-test to verify
        field names before trading logic depends on them."""
        try:
            res = await self.account_api.account(by="index", value=str(self.account_index))
            return True, res
        except Exception as e:
            return False, str(e)

    async def _get_account_obj(self):
        """The account() call returns DetailedAccounts{accounts: [...]}, not a
        flat object — drill into accounts[0] for the actual account record."""
        ok, res = await self.get_account_raw()
        if not ok:
            return None, res
        accounts = getattr(res, "accounts", None)
        if not accounts:
            return None, f"No accounts in response: {res.to_dict() if hasattr(res,'to_dict') else res}"
        return accounts[0], None

    async def get_balance_usd(self):
        """Total account equity (mark-to-market: cash + open position value +
        unrealized PnL) — NOT just uncommitted/free cash. Confirmed live on a
        real account: available_balance read $0.50 while total_asset_value
        (==cross_asset_value) correctly read $11.94 with $10+ margin locked in
        open positions. Using available_balance here silently understated the
        real account size any time a position was open, which corrupted
        anything computed from it — displayed Balance, per-agent auto-split
        start_balance, and manual-trade percent sizing all inherited the same
        deflated number."""
        acct, err = await self._get_account_obj()
        if acct is None:
            return None, err
        try:
            for attr in ("total_asset_value", "cross_asset_value", "collateral",
                         "balance", "portfolio_value", "available_balance"):
                if hasattr(acct, attr):
                    val = getattr(acct, attr)
                    if val is not None:
                        return float(val), None
            dump = acct.to_dict() if hasattr(acct, "to_dict") else vars(acct)
            return None, f"Could not find balance field. Full account record: {dump}"
        except Exception as e:
            return None, str(e)

    async def get_open_positions(self):
        acct, err = await self._get_account_obj()
        if acct is None:
            return [], err
        try:
            positions = getattr(acct, "positions", []) or []
            return positions, None
        except Exception as e:
            return [], str(e)

    async def get_active_orders(self, market_id: int = None):
        """Ground-truth check for resting orders (incl. stop/take-profit
        triggers) — the position object's open_order_count field may not
        reflect conditional orders, so this hits the order book directly."""
        try:
            auth_token, err = self.signer.create_auth_token_with_expiry()
            if err:
                return [], f"auth token error: {err}"
            res = await _call(
                self.order_api.account_active_orders,
                authorization=auth_token,
                account_index=self.account_index,
                market_id=market_id,
            )
            return getattr(res, "orders", []) or [], None
        except Exception as e:
            return [], str(e)

    async def get_inactive_orders(self, limit: int = 100, cursor: str = None):
        """Real trade history — filled/cancelled orders (entries, SL/TP fills,
        manual closes). This is ground truth from the exchange, not something
        the bot reconstructs locally. `limit` is capped at 100 by Lighter's
        API — pass the previous response's next_cursor to page further back
        (see trade_history.get_closed_trades, which walks multiple pages).
        Returns (orders, next_cursor, error)."""
        try:
            auth_token, err = self.signer.create_auth_token_with_expiry()
            if err:
                return [], None, f"auth token error: {err}"
            res = await _call(
                self.order_api.account_inactive_orders,
                authorization=auth_token,
                account_index=self.account_index,
                limit=limit,
                cursor=cursor,
            )
            return getattr(res, "orders", []) or [], getattr(res, "next_cursor", None), None
        except Exception as e:
            return [], None, str(e)

    async def _describe_fill_failure(self, market_index: int, base_amount: float, actual_filled: float) -> str:
        """Looks up the real exchange rejection reason for the order that was
        just submitted, instead of guessing. Confirmed live: the previous
        hardcoded 'likely price moved past the slippage tolerance' message
        was shown for EVERY failed fill regardless of cause — including a
        stretch where the true reason was margin exhaustion
        (canceled-margin-not-allowed), not slippage at all. Falls back to the
        old generic wording only if the real status can't be determined."""
        try:
            orders, _cursor, err = await self.get_inactive_orders(limit=5)
            if not err and orders:
                same_market = [o for o in orders if getattr(o, "market_index", None) == market_index]
                if same_market:
                    latest = max(same_market, key=lambda o: getattr(o, "timestamp", 0))
                    status = getattr(latest, "status", None)
                    if status and status != "filled":
                        return (f"order rejected by exchange: status={status} "
                                f"(intended {base_amount}, actual change {actual_filled})")
        except Exception:
            pass
        return (f"order accepted but did not fill as expected "
                f"(intended {base_amount}, actual change {actual_filled}) — "
                f"likely price moved past the slippage tolerance before matching")

    async def cancel_order(self, symbol: str, order_index: int):
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        try:
            tx, tx_hash, err = await _call(
                self.signer.cancel_order,
                market_index=market_index,
                order_index=order_index,
            )
            return (err is None), (tx_hash or err)
        except Exception as e:
            return False, str(e)

    async def modify_stop_order(self, symbol: str, order_index: int, new_trigger_price: float,
                                  is_close_ask: bool, fill_buffer_pct: float = 0.5):
        """Moves a resting stop-loss/take-profit trigger price in place —
        confirmed live to NOT touch the paired OCO order (TP stays resting
        untouched when only the SL is modified). Strictly better than
        cancel+recreate: no window where the position is unprotected, and one
        less thing that can fail (only one tx instead of cancel+cancel+create)."""
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = PRICE_DECIMALS.get(symbol, 2)

        # Same fill-buffer direction logic as attach_sl_tp: closing side needs
        # a worse price than trigger to guarantee execution once triggered.
        fill_price = (new_trigger_price * (1 - fill_buffer_pct/100) if is_close_ask
                      else new_trigger_price * (1 + fill_buffer_pct/100))
        try:
            result = await _call(
                self.signer.modify_order,
                market_index=market_index,
                order_index=order_index,
                base_amount=0,  # keep position-tied semantics (closes whatever size exists)
                price=to_scaled_int(fill_price, price_dec),
                trigger_price=to_scaled_int(new_trigger_price, price_dec),
            )
            return True, result
        except Exception as e:
            return False, str(e)

    # ── Leverage ───────────────────────────────────────────────────────────
    async def set_leverage(self, symbol: str, leverage: int):
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"

        await self.refresh_max_leverage()  # cached, cheap no-op if recently refreshed
        max_lev = self.get_max_leverage(symbol)
        if leverage > max_lev:
            return False, f"Requested {leverage}x exceeds {symbol}'s live max of {max_lev}x"

        try:
            # sign_update_leverage() ONLY SIGNS the tx — it never submits it,
            # so the leverage change was never actually applied on-chain.
            # update_leverage() does sign + send_tx (confirmed by reading the
            # SDK source directly) and is the one that actually changes
            # anything. Found live: BTC/XRP positions were still sitting at
            # whatever leverage they'd always been at (20x/15x) while every
            # set_leverage() call kept reporting success and the bot's own
            # position-sizing math assumed the configured 50x/20x — a real
            # mismatch between assumed and actual margin usage, not just a
            # display bug.
            tx_info, api_response, error = await _call(
                self.signer.update_leverage,
                market_index=market_index,
                margin_mode=self.signer.ISOLATED_MARGIN_MODE,
                leverage=leverage,
            )
            if error is not None:
                return False, error
            return True, api_response
        except Exception as e:
            # Exchange rejected the leverage tier (too high for this market/risk bracket).
            return False, str(e)

    # ── Orders ─────────────────────────────────────────────────────────────
    async def place_market_order_with_sl_tp(self, symbol: str, is_ask: bool,
                                              base_amount: float, ref_price: float,
                                              sl_price: float, tp_price: float,
                                              size_before_hint: float = None):
        """
        is_ask=False -> BUY (long), is_ask=True -> SELL (short)
        Places a market entry via create_market_order, then attaches OCO
        stop-loss/take-profit via create_grouped_orders. Every step is
        independently error-checked; if SL/TP attachment fails, the position
        is flattened immediately rather than left unprotected.

        size_before_hint: if the caller already fetched positions moments
        earlier in the same locked section (e.g. manual_trade's duplicate-
        position check, or run_tick's fresh-position re-check before opening),
        pass that known size here to skip a redundant get_open_positions()
        call — cuts a full network round-trip off every trade with no loss
        of accuracy, since nothing can trade on this symbol between that
        fetch and this call (same trade lock held the whole time).
        """
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"

        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"

        min_base = MIN_BASE_AMOUNT.get(symbol, 0)
        if base_amount < min_base:
            return False, f"base_amount {base_amount} below exchange minimum {min_base} for {symbol}"

        notional = base_amount * ref_price
        if notional < MIN_NOTIONAL_USD - 0.01:  # tolerance for float rounding (e.g. $9.99998 is really $10)
            return False, f"notional ${notional:.2f} below exchange minimum ${MIN_NOTIONAL_USD}"

        size_dec  = SIZE_DECIMALS.get(symbol, 4)
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        amount_i    = to_scaled_int(base_amount, size_dec)
        sl_price_i  = to_scaled_int(sl_price, price_dec)
        tp_price_i  = to_scaled_int(tp_price, price_dec)

        # avg_execution_price is a worst-acceptable-price bound for the IOC
        # market order, not an exact price. Apply slippage tolerance so a
        # SELL entry (short) or SELL close actually crosses the book.
        slippage_pct = 1.0
        entry_limit_price = ref_price * (1 + slippage_pct/100) if not is_ask else ref_price * (1 - slippage_pct/100)
        entry_limit_price_i = to_scaled_int(entry_limit_price, price_dec)

        # Same fill-verification as add_to_position_market: an IOC order can
        # be accepted on-chain (code=200, no error) while filling ZERO if it
        # can't cross the book within our slippage tolerance — confirmed live
        # to otherwise let the bot think a position exists (and here, worse,
        # go on to attach a real SL/TP bracket) when nothing actually traded.
        if size_before_hint is not None:
            size_before = size_before_hint
        else:
            before_positions, before_err = await self.get_open_positions()
            size_before = 0.0
            if not before_err:
                existing = next((p for p in before_positions if getattr(p, "symbol", None) == symbol), None)
                size_before = signed_position_size(existing) if existing is not None else 0.0

        try:
            entry_client_order_index = int(time.time() * 1000) % 1_000_000
            entry_tx, entry_hash, err = await _call(
                self.signer.create_market_order,
                market_index=market_index,
                client_order_index=entry_client_order_index,
                base_amount=amount_i,
                avg_execution_price=entry_limit_price_i,
                is_ask=is_ask,
            )
            if err:
                return False, f"entry order failed: {err}"
        except Exception as e:
            return False, f"entry order exception: {e}"

        # Same propagation-lag handling as add_to_position_market — a single
        # instant re-check is not reliable, poll with backoff first.
        actual_filled = 0.0
        for attempt, delay in enumerate((0, 0.5, 1.0, 2.0)):
            if delay:
                await asyncio.sleep(delay)
            after_positions, after_err = await self.get_open_positions()
            if after_err:
                continue
            existing_after = next((p for p in after_positions if getattr(p, "symbol", None) == symbol), None)
            size_after = signed_position_size(existing_after) if existing_after is not None else 0.0
            actual_filled = abs(size_after - size_before)
            if actual_filled >= base_amount * 0.5:
                break
        if actual_filled < base_amount * 0.5:
            return False, await self._describe_fill_failure(market_index, base_amount, actual_filled)

        # A handful of quick retries absorbs transient failures (network
        # blip, rate limit, momentary RPC error) without leaving the position
        # unprotected for long — each attempt needs a FRESH seed since
        # attach_sl_tp derives its two order IDs from it (seed+1/seed+2),
        # and reusing a failed attempt's seed would collide with those IDs.
        # If every attempt fails, flatten immediately rather than keep
        # retrying indefinitely with a real position sitting naked.
        ok, result = False, None
        for attempt in range(3):
            retry_seed = int(time.time() * 1000 + attempt) % 1_000_000
            ok, result = await self.attach_sl_tp(symbol, is_ask, sl_price, tp_price,
                                                  client_order_seed=retry_seed)
            if ok:
                break
            if attempt < 2:
                await asyncio.sleep(0.5)
        if not ok:
            # SL/TP failed to attach after 3 attempts — flatten the now-unprotected position immediately.
            await self.close_position_market(symbol, is_ask=not is_ask, base_amount=base_amount, ref_price=ref_price)
            return False, f"SL/TP attach failed after 3 attempts, position flattened: {result}"
        return True, {"entry": entry_hash, "oco": result}

    async def add_to_position_market(self, symbol: str, is_ask: bool, base_amount: float, ref_price: float):
        """Increases an ALREADY-OPEN position via another market entry in the
        SAME direction — used when max_positions_per_symbol > 1 lets an agent
        stack onto a symbol it already holds. Deliberately does NOT touch the
        existing SL/TP orders: they were placed with BaseAmount=0, meaning
        "close whatever the position size is at trigger time" (confirmed via
        the SDK's own create_position_tied_sl_tp.py example) — so they
        automatically cover the new, larger combined position with no
        modification needed. The original SL/TP price levels stay as they
        were; this only adds size, not a new bracket."""
        if self.client_check_error:
            return False, f"Client not properly initialized: {self.client_check_error}"

        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"

        min_base = MIN_BASE_AMOUNT.get(symbol, 0)
        if base_amount < min_base:
            return False, f"base_amount {base_amount} below exchange minimum {min_base} for {symbol}"

        notional = base_amount * ref_price
        if notional < MIN_NOTIONAL_USD - 0.01:  # tolerance for float rounding (e.g. $9.99998 is really $10)
            return False, f"notional ${notional:.2f} below exchange minimum ${MIN_NOTIONAL_USD}"

        size_dec = SIZE_DECIMALS.get(symbol, 4)
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        amount_i = to_scaled_int(base_amount, size_dec)

        slippage_pct = 1.0
        entry_limit_price = ref_price * (1 + slippage_pct/100) if not is_ask else ref_price * (1 - slippage_pct/100)
        entry_limit_price_i = to_scaled_int(entry_limit_price, price_dec)

        # A market order can be accepted on-chain (code=200, no error) while
        # actually filling ZERO — an IOC order that can't cross the book
        # within our slippage tolerance just expires unmatched, which the
        # chain treats as a valid outcome, not an error. Confirmed live: this
        # was causing the bot to "successfully open" a position that never
        # actually existed, over and over, every ~30s, with the resting
        # SL/TP catastrophe-safety logic never even engaging because there
        # was nothing real to protect. Comparing position size before/after
        # is the only reliable way to know whether anything actually traded.
        before_positions, before_err = await self.get_open_positions()
        size_before = 0.0
        if not before_err:
            existing = next((p for p in before_positions if getattr(p, "symbol", None) == symbol), None)
            size_before = signed_position_size(existing) if existing is not None else 0.0

        try:
            entry_client_order_index = int(time.time() * 1000) % 1_000_000
            entry_tx, entry_hash, err = await _call(
                self.signer.create_market_order,
                market_index=market_index,
                client_order_index=entry_client_order_index,
                base_amount=amount_i,
                avg_execution_price=entry_limit_price_i,
                is_ask=is_ask,
            )
            if err:
                return False, f"add-to-position entry failed: {err}"
        except Exception as e:
            return False, f"add-to-position entry exception: {e}"

        # Lighter's own position-state can lag the transaction's real on-chain
        # execution by anywhere from under a second to tens of seconds —
        # confirmed live: a fill that genuinely happened was read as "zero
        # change" on the FIRST immediate re-check, only to show up as a real,
        # unprotected position a full 30+ seconds later once the safety net
        # (check_for_unprotected_positions) caught it. A single instant
        # re-check is not reliable — poll with backoff before concluding the
        # order truly didn't fill, so a genuine fill isn't mistaken for a
        # failure (which would otherwise skip attaching real protection).
        actual_filled = 0.0
        for attempt, delay in enumerate((0, 0.5, 1.0, 2.0)):
            if delay:
                await asyncio.sleep(delay)
            after_positions, after_err = await self.get_open_positions()
            if after_err:
                continue
            existing_after = next((p for p in after_positions if getattr(p, "symbol", None) == symbol), None)
            size_after = signed_position_size(existing_after) if existing_after is not None else 0.0
            actual_filled = abs(size_after - size_before)
            if actual_filled >= base_amount * 0.5:
                break

        # Require at least half the intended size to have actually traded —
        # a full-precision exact match isn't realistic (rounding, tiny
        # partial fills), but near-zero fill after all retries means the
        # order genuinely expired unmatched and nothing real happened.
        if actual_filled < base_amount * 0.5:
            return False, await self._describe_fill_failure(market_index, base_amount, actual_filled)

        return True, {"entry": entry_hash, "filled": actual_filled}

    async def attach_sl_tp(self, symbol: str, is_ask: bool, sl_price: float, tp_price: float,
                            client_order_seed: int = None):
        """Attaches OCO stop-loss/take-profit to an EXISTING position — no new
        entry order. Used both for the initial bracket and for re-attaching a
        moved trailing stop (cancel old bracket, call this again with new SL).

        BaseAmount=0 is intentional: position-tied SL/TP orders close whatever
        the position size is at trigger time, not a fixed amount — confirmed
        from the SDK's own create_position_tied_sl_tp.py example. Passing the
        actual order size caused the tx to be silently dropped (accepted into
        mempool with code=200, but never actually included on-chain).

        Price gets a small buffer past TriggerPrice in the fill direction so
        the limit order guarantees execution once triggered (closing side is
        a SELL for a LONG position, so worse price = lower)."""
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        sl_price_i = to_scaled_int(sl_price, price_dec)
        tp_price_i = to_scaled_int(tp_price, price_dec)
        seed = client_order_seed if client_order_seed is not None else int(time.time() * 1000) % 1_000_000

        close_is_ask = not is_ask
        fill_buffer_pct = 0.5
        tp_fill_price = tp_price * (1 - fill_buffer_pct/100) if close_is_ask else tp_price * (1 + fill_buffer_pct/100)
        sl_fill_price = sl_price * (1 - fill_buffer_pct/100) if close_is_ask else sl_price * (1 + fill_buffer_pct/100)

        try:
            tp_order = CreateOrderTxReq(
                MarketIndex=market_index,
                ClientOrderIndex=(seed + 1) % 1_000_000,
                BaseAmount=0,
                Price=to_scaled_int(tp_fill_price, price_dec),
                IsAsk=int(close_is_ask),
                Type=self.signer.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                TimeInForce=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                ReduceOnly=1,
                TriggerPrice=tp_price_i,
                OrderExpiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
            )
            sl_order = CreateOrderTxReq(
                MarketIndex=market_index,
                ClientOrderIndex=(seed + 2) % 1_000_000,
                BaseAmount=0,
                Price=to_scaled_int(sl_fill_price, price_dec),
                IsAsk=int(close_is_ask),
                Type=self.signer.ORDER_TYPE_STOP_LOSS_LIMIT,
                TimeInForce=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                ReduceOnly=1,
                TriggerPrice=sl_price_i,
                OrderExpiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
            )
            oco_tx = await _call(
                self.signer.create_grouped_orders,
                grouping_type=self.signer.GROUPING_TYPE_ONE_CANCELS_THE_OTHER,
                orders=[tp_order, sl_order],
            )
            # create_grouped_orders returns (None, None, error_str) on failure —
            # this was previously never checked, so a failed OCO attach (e.g.
            # "OrderExpiry is invalid") was silently reported as ok=True,
            # leaving a real position open with zero SL/TP protection and
            # never triggering the caller's flatten-on-failure safety net.
            if isinstance(oco_tx, tuple) and len(oco_tx) >= 3 and oco_tx[2]:
                return False, oco_tx[2]
            return True, oco_tx
        except Exception as e:
            return False, str(e)

    async def attach_catastrophic_sl(self, symbol: str, is_ask: bool, sl_price: float,
                                       client_order_seed: int = None):
        """Places a SINGLE wide stop-loss-limit order with no paired take-profit
        — used only as the safety-net backstop for 'interval_check' exit mode,
        where the real (tight) trailing SL/TP is tracked in the bot's own
        memory and checked/closed manually each tick instead of resting on
        the exchange (matching comp11's polling behavior). This one order is
        the only real protection against a crash that blows past the
        in-memory SL faster than the bot's next check can react. BaseAmount=0
        = close whatever the position size is at trigger time, same semantics
        as attach_sl_tp's bracket orders."""
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        seed = client_order_seed if client_order_seed is not None else int(time.time() * 1000) % 1_000_000

        close_is_ask = not is_ask
        fill_buffer_pct = 0.5
        sl_fill_price = sl_price * (1 - fill_buffer_pct/100) if close_is_ask else sl_price * (1 + fill_buffer_pct/100)

        try:
            order, resp, err = await _call(
                self.signer.create_sl_limit_order,
                market_index=market_index,
                client_order_index=seed % 1_000_000,
                base_amount=0,
                trigger_price=to_scaled_int(sl_price, price_dec),
                price=to_scaled_int(sl_fill_price, price_dec),
                is_ask=close_is_ask,
                reduce_only=True,
            )
            if err:
                return False, err
            return True, resp
        except Exception as e:
            return False, str(e)

    async def attach_real_tp(self, symbol: str, is_ask: bool, tp_price: float,
                               client_order_seed: int = None):
        """Places a SINGLE take-profit-limit order with no paired stop-loss —
        the 'interval_check' exit mode's optional counterpart to
        attach_catastrophic_sl: lets a user put the TAKE-PROFIT side back on
        the exchange (watched continuously, fires the instant price touches
        it) while the STOP-LOSS side stays purely in-memory/polled. There's
        no downside-risk reason to keep TP in-memory — catching a good exit
        early is never a problem the way an unprotected SL gap is.
        BaseAmount=0 = close whatever the position size is at trigger time,
        same semantics as attach_sl_tp's bracket orders."""
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        seed = client_order_seed if client_order_seed is not None else int(time.time() * 1000) % 1_000_000

        close_is_ask = not is_ask
        fill_buffer_pct = 0.5
        tp_fill_price = tp_price * (1 - fill_buffer_pct/100) if close_is_ask else tp_price * (1 + fill_buffer_pct/100)

        try:
            order, resp, err = await _call(
                self.signer.create_tp_limit_order,
                market_index=market_index,
                client_order_index=seed % 1_000_000,
                base_amount=0,
                trigger_price=to_scaled_int(tp_price, price_dec),
                price=to_scaled_int(tp_fill_price, price_dec),
                is_ask=close_is_ask,
                reduce_only=True,
            )
            if err:
                return False, err
            return True, resp
        except Exception as e:
            return False, str(e)

    async def close_position_market(self, symbol: str, is_ask: bool, base_amount: float,
                                      ref_price: float, slippage_pct: float = 1.0):
        """avg_execution_price acts as a worst-acceptable-price bound for a
        marketable IOC order, not an exact price — passing the exact mid price
        can fail to cross the book. Apply slippage tolerance so it actually fills:
        selling needs a price below market, buying needs a price above market."""
        market_index = MARKET_INDEX.get(symbol)
        size_dec  = SIZE_DECIMALS.get(symbol, 4)
        price_dec = PRICE_DECIMALS.get(symbol, 2)
        limit_price = ref_price * (1 - slippage_pct/100) if is_ask else ref_price * (1 + slippage_pct/100)
        try:
            client_order_index = int(time.time() * 1000) % 1_000_000
            tx, tx_hash, err = await _call(
                self.signer.create_market_order,
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=to_scaled_int(base_amount, size_dec),
                avg_execution_price=to_scaled_int(limit_price, price_dec),
                is_ask=is_ask,
                reduce_only=True,
            )
            return (err is None), (tx_hash or err)
        except Exception as e:
            return False, str(e)
