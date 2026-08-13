"""Shared real-trade-history reconstruction — pairs entry fills with their
exit fills from Lighter's account_inactive_orders (ground truth for
prices/timing). Used by both server.py (Trade History table / stats) and
engine.py (compounding balance: an agent's current working balance grows or
shrinks with its own realized PnL, so sizing scales up/down as it wins/loses).
"""


def find_agent(agent_open_log, symbol, opened_at, tolerance_sec=180):
    """Best-effort join: find the agent_open_log entry for this symbol whose
    logged open time is closest to (and within tolerance of) the exchange's
    actual fill timestamp. Falls back to 'Manual' if nothing matches — this
    happens for trades placed before this tracking existed, or from outside
    the bot entirely."""
    candidates = [e for e in agent_open_log if e["symbol"] == symbol]
    if not candidates:
        return "Manual"
    best = min(candidates, key=lambda e: abs(e["opened_at"] - opened_at))
    if abs(best["opened_at"] - opened_at) <= tolerance_sec:
        return best["agent"]
    return "Manual"


async def get_closed_trades(client, state, price_decimals, leverage_cfg=None,
                             default_leverage=None, limit=100, max_pages=1):
    """Returns (trades, error). trades is unsorted, unfiltered by cutoff —
    callers apply their own sort/cutoff/pagination. Lighter caps a single
    call at `limit` (max 100) orders, but supports walking further back via
    next_cursor — max_pages controls how many 100-order pages to fetch (e.g.
    max_pages=10 covers up to 1000 orders / ~500 round trips). Engine ticks
    use the default (1 page, fast) since the durable realized-PnL tracker
    doesn't need full history each call; the Trade History display endpoint
    asks for more pages to show deeper real history."""
    leverage_cfg = leverage_cfg or {}
    orders = []
    cursor = None
    for _ in range(max_pages):
        page, next_cursor, err = await client.get_inactive_orders(limit=limit, cursor=cursor)
        if err:
            if orders:
                break  # keep whatever pages succeeded rather than discarding them
            return [], err
        orders.extend(page)
        if not next_cursor or not page:
            break
        cursor = next_cursor

    agent_open_log = state.get("agent_open_log", [])
    filled = [o for o in orders if getattr(o, "status", "") == "filled"]
    by_market = {}
    for o in filled:
        by_market.setdefault(getattr(o, "market_index", None), []).append(o)

    result = []
    for market_index, group in by_market.items():
        group.sort(key=lambda o: getattr(o, "timestamp", 0))
        symbol = _symbol_for(market_index, client.MARKET_INDEX)

        pending_entries = []  # ALL entries accumulated since the last close —
                               # max_positions_per_symbol > 1 (stacking) means
                               # a single close can follow many separate ADD
                               # entries, not just one. Losing all but the
                               # last one here was the root cause of PnL being
                               # massively undercounted, trades vanishing from
                               # history, and "opened_at" being read from the
                               # last add instead of when the position truly
                               # first started (making durations look like
                               # seconds when the position had really been
                               # open much longer).
        for o in group:
            reduce_only = getattr(o, "reduce_only", False)
            if not reduce_only:
                pending_entries.append(o)
                continue

            if not pending_entries:
                continue  # exit with no matching entry in this window — skip

            entries = pending_entries
            pending_entries = []

            # `price` on a filled market order is the worst-acceptable
            # slippage-buffer price WE submitted, not the real fill price —
            # the real average fill price is filled_quote/filled_base.
            def _real_price(order):
                amt = float(getattr(order, "filled_base_amount", 0) or 0)
                quote = float(getattr(order, "filled_quote_amount", 0) or 0)
                return quote / amt if amt else float(getattr(order, "price", 0) or 0)

            # Combine every stacked entry into one volume-weighted position —
            # total size across all adds, weighted-average entry price, and
            # the FIRST add's timestamp as the true open time.
            total_qty = sum(float(getattr(e, "filled_base_amount", 0) or 0) for e in entries)
            if total_qty <= 0:
                continue
            weighted_price = sum(_real_price(e) * float(getattr(e, "filled_base_amount", 0) or 0)
                                  for e in entries) / total_qty

            side = "LONG" if not getattr(entries[0], "is_ask", False) else "SHORT"
            price_dec = price_decimals.get(symbol, 4)
            entry_price = round(weighted_price, price_dec)
            exit_price = round(_real_price(o), price_dec)
            qty = total_qty
            pnl = qty * (exit_price - entry_price) if side == "LONG" else qty * (entry_price - exit_price)

            exit_type_raw = getattr(o, "type", "")
            if "take-profit" in exit_type_raw:
                exit_label = "TP"
            elif "stop-loss" in exit_type_raw:
                exit_label = "SL"
            else:
                exit_label = "Manual"

            opened_at = getattr(entries[0], "timestamp", 0)  # first add, not last
            closed_at = getattr(o, "timestamp", 0)
            agent = find_agent(agent_open_log, symbol, opened_at)

            result.append({
                "agent": agent,
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "exit_type": exit_label,
                "result": "WIN" if pnl >= 0 else "LOSS",
                "pnl": round(pnl, 4),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "leverage": leverage_cfg.get(symbol, default_leverage),
            })
    return result, None


async def attach_fee(client, trade):
    """Best-effort enrichment: attaches real 'fee' (positive = cost) and
    'net_pnl' (pnl minus fee) to ONE trade dict in place, using Binance's
    /fapi/v1/income COMMISSION history. Called exactly once per trade, at
    the moment sync_realized_pnl() first confirms it closed — NOT on every
    tick's get_closed_trades() call, which would mean a live Binance query
    every ~10s for every historical symbol forever (that was the earlier,
    now-reverted mistake). Lighter (or any client without get_income_history)
    is silently skipped — fee/net_pnl just won't be present. A fee-lookup
    failure must never break trade history or realized-PnL tracking, which
    is why every real exception here is swallowed rather than propagated."""
    if not hasattr(client, "get_income_history"):
        return
    try:
        start_ms = int(trade["opened_at"] * 1000) - 2000
        end_ms = int(trade["closed_at"] * 1000) + 5000
        entries, err = await client.get_income_history(
            "COMMISSION", symbol=trade["symbol"], start_time_ms=start_ms, end_time_ms=end_ms)
        if err or not entries:
            return
        fee = -sum(float(e["income"]) for e in entries)
        trade["fee"] = round(fee, 6)
        trade["net_pnl"] = round(trade["pnl"] - fee, 6)
    except Exception:
        pass


def _symbol_for(market_index, platform_market_index):
    """platform_market_index is the ACTIVE client's own MARKET_INDEX
    (client.MARKET_INDEX) — Lighter's is symbol->numeric-id, Binance's is
    symbol->full-pair-string ('BTCUSDT'), so reversing it must use whichever
    mapping actually produced the market_index value on the orders being
    processed, not a hardcoded platform's."""
    return {v: k for k, v in platform_market_index.items()}.get(market_index, f"market_{market_index}")
