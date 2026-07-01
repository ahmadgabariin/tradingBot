"""
Runtime configuration for LighterBot. Persisted to lighterbot_config.json.
Editable live via the dashboard (POST /config) without restarting the bot.
"""
import json, os, threading

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "lighterbot_config.json")
_lock = threading.Lock()

DEFAULT_CONFIG = {
    # Which agents are active. Engine only evaluates signals for agents set True.
    "agents": {
        "Liquidity Hunt": {"enabled": True,  "direction": "LONG"},   # LONG | SHORT | BOTH
        "Surgeon v2":     {"enabled": True,  "direction": "SHORT"},
    },

    # Position sizing. mode: "fixed" (USD amount) or "percent" (% of live balance).
    "sizing": {
        "mode":  "percent",
        "fixed_usd": 10.0,
        "percent":   5.0,
    },

    # Leverage per symbol, defaulted to each market's real max (confirmed live
    # via Lighter's min_initial_margin_fraction on 2026-07-01). Bot attempts
    # this leverage via sign_update_leverage; if the exchange rejects it, the
    # trade is skipped and logged (never silently retried at a guessed value).
    "leverage": {
        "BTC": 50, "ETH": 50, "SOL": 25, "XRP": 20, "BNB": 20,
        "LINK": 10, "DOT": 10, "AVAX": 10, "ADA": 10, "POL": 8,
    },
    "default_leverage": 10,

    # Hard safety rails
    "max_open_positions": 1,     # matches small account reality — avoid overcommitting $12
    "min_notional_usd":   10.0,  # Lighter's exchange-enforced floor; sizing is bumped up to this if below

    "running": False,
}


def _ensure_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)


def load_config() -> dict:
    with _lock:
        _ensure_file()
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # backfill any new keys added after a user's config was already saved
        merged = {**DEFAULT_CONFIG, **cfg}
        for k, v in DEFAULT_CONFIG.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged[k] = {**v, **cfg[k]}
        return merged


def save_config(cfg: dict):
    with _lock:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
