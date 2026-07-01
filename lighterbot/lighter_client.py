"""
Thin wrapper around the official `lighter-sdk` (pip install lighter-sdk).
Every call that touches real money is wrapped in try/except and returns a
structured (ok, result_or_error) tuple instead of raising — the engine logs
failures and skips the trade rather than crashing or retrying blindly.
"""
import os, time

try:
    import lighter
except ImportError:
    lighter = None  # allows the dashboard/config to load even before `pip install lighter-sdk`

MARKET_INDEX = {
    "ETH": 0,
    "BTC": 1,
    "SOL": 2,
}
MIN_BASE_AMOUNT = {
    "ETH": 0.0050,
    "BTC": 0.00020,
    "SOL": 0.050,
}
PRICE_DECIMALS = {
    "ETH": 2,
    "BTC": 1,
    "SOL": 3,
}
MIN_NOTIONAL_USD = 10.0


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
        acct, err = await self._get_account_obj()
        if acct is None:
            return None, err
        try:
            for attr in ("available_balance", "collateral", "total_asset_value",
                         "balance", "portfolio_value", "cross_asset_value"):
                if hasattr(acct, attr):
                    val = getattr(acct, attr)
                    if val is not None:
                        return float(val), None
            # Nothing matched — dump the full record so the real field name is visible
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

    # ── Leverage ───────────────────────────────────────────────────────────
    async def set_leverage(self, symbol: str, leverage: int):
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"
        try:
            fraction = 10_000 // leverage
            tx = await self.signer.sign_update_leverage(
                market_index=market_index,
                fraction=fraction,
                margin_mode=self.signer.ISOLATED_MARGIN_MODE,
            )
            return True, tx
        except Exception as e:
            # Exchange rejected the leverage tier (too high for this market/risk bracket).
            return False, str(e)

    # ── Orders ─────────────────────────────────────────────────────────────
    async def place_market_order_with_sl_tp(self, symbol: str, is_ask: bool,
                                              base_amount: float, ref_price: float,
                                              sl_price: float, tp_price: float):
        """
        is_ask=False -> BUY (long), is_ask=True -> SELL (short)
        Places a market entry, then attaches OCO stop-loss/take-profit via
        create_grouped_orders. Every step is independently error-checked;
        if SL/TP attachment fails, the position is flattened immediately
        rather than left unprotected.
        """
        market_index = MARKET_INDEX.get(symbol)
        if market_index is None:
            return False, f"Unknown symbol {symbol}"

        min_base = MIN_BASE_AMOUNT.get(symbol, 0)
        if base_amount < min_base:
            return False, f"base_amount {base_amount} below exchange minimum {min_base} for {symbol}"

        notional = base_amount * ref_price
        if notional < MIN_NOTIONAL_USD:
            return False, f"notional ${notional:.2f} below exchange minimum ${MIN_NOTIONAL_USD}"

        try:
            client_order_index = int(time.time() * 1000) % 1_000_000
            entry_tx, entry_hash, err = await self.signer.create_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=base_amount,
                price=ref_price,
                is_ask=is_ask,
                order_type=self.signer.ORDER_TYPE_MARKET,
                time_in_force=self.signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only=False,
                order_expiry=self.signer.DEFAULT_IOC_EXPIRY,
            )
            if err:
                return False, f"entry order failed: {err}"
        except Exception as e:
            return False, f"entry order exception: {e}"

        # Attach OCO stop-loss / take-profit, reduce-only, opposite side of entry
        try:
            tp_order = {
                "market_index": market_index,
                "is_ask": not is_ask,
                "base_amount": base_amount,
                "trigger_price": tp_price,
                "price": tp_price,
                "order_type": self.signer.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                "reduce_only": True,
            }
            sl_order = {
                "market_index": market_index,
                "is_ask": not is_ask,
                "base_amount": base_amount,
                "trigger_price": sl_price,
                "price": sl_price,
                "order_type": self.signer.ORDER_TYPE_STOP_LOSS_LIMIT,
                "reduce_only": True,
            }
            oco_tx = await self.signer.create_grouped_orders(
                grouping_type=self.signer.GROUPING_TYPE_ONE_CANCELS_THE_OTHER,
                orders=[tp_order, sl_order],
            )
            return True, {"entry": entry_hash, "oco": oco_tx}
        except Exception as e:
            # SL/TP failed to attach — flatten the now-unprotected position immediately.
            await self.close_position_market(symbol, is_ask=not is_ask, base_amount=base_amount, ref_price=ref_price)
            return False, f"SL/TP attach failed, position flattened: {e}"

    async def close_position_market(self, symbol: str, is_ask: bool, base_amount: float, ref_price: float):
        market_index = MARKET_INDEX.get(symbol)
        try:
            client_order_index = int(time.time() * 1000) % 1_000_000
            tx, tx_hash, err = await self.signer.create_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=base_amount,
                price=ref_price,
                is_ask=is_ask,
                order_type=self.signer.ORDER_TYPE_MARKET,
                time_in_force=self.signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only=True,
                order_expiry=self.signer.DEFAULT_IOC_EXPIRY,
            )
            return (err is None), (tx_hash or err)
        except Exception as e:
            return False, str(e)
