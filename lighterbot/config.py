"""
Runtime configuration for LighterBot. Persisted to lighterbot_config.json.
Editable live via the dashboard (POST /config) without restarting the bot.
"""
import json, os, threading

from lighterbot.agents import AGENTS

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "lighterbot_config.json")
_lock = threading.Lock()

# Only the numeric trailing/SL-TP knobs are user-editable per agent — not
# timeframe/exit_mode/description, which are structural and tied to the
# signal logic itself. Seeded straight from agents.py's AGENTS dict so the
# dashboard's defaults always start out identical to what's actually running,
# with no risk of the two drifting out of sync.
_TRAILING_KEYS = ("atr_sl_mult", "atr_tp_mult",
                  "sar_af_start", "sar_af_step", "sar_af_max",
                  "st_period", "st_mult",
                  "keltner_period", "keltner_mult",
                  "sl_pct", "tp_pct")


def _default_trailing_for(agent_name: str) -> dict:
    agent = AGENTS.get(agent_name, {})
    return {k: agent[k] for k in _TRAILING_KEYS if k in agent}

DEFAULT_CONFIG = {
    # Which agents are active. Engine only evaluates signals for agents set True.
    # "start_balance" is the USD amount originally allocated to this agent.
    # The agent's WORKING balance (what percent-mode sizing and equity/return %
    # are actually computed against) is start_balance + that agent's own
    # cumulative realized PnL — it compounds up as the agent wins and down as
    # it loses, same idea as each paper-trading agent's isolated $1000 that
    # grows/shrinks with its own trades. Real orders still execute against the
    # real (shared) Lighter account balance — this is a bookkeeping split.
    #
    # start_balance starts at 0.0 / balance_initialized=False on purpose — a
    # hardcoded guess (e.g. $50) can wildly overstate a small real account.
    # The engine auto-splits the REAL live balance evenly across agents still
    # marked uninitialized the first time it can fetch it (see
    # engine.maybe_init_agent_balances), then flips the flag so it never
    # overwrites a value the user set afterward, including an intentional 0.
    # max_open_positions: how many different coins THIS agent can hold
    # positions on at once — a per-agent budget, not shared with other
    # agents (matches comp11's independent per-agent MAX_OPEN).
    # max_positions_per_symbol: how many times THIS agent may add to its own
    # already-open position on the same coin (same direction) before a new
    # signal on that coin is skipped. Both default to 9999 (effectively
    # unlimited, matching comp11) and are editable anytime per-agent from
    # each agent's Edit dialog on the dashboard.
    #
    # sl_tp_mode: "continuous" (default) = today's behavior, real SL/TP
    # orders resting on the exchange, watched nonstop, trailed via live order
    # modification. "interval_check" = comp11-matching behavior instead: the
    # tight SL/TP is tracked purely in the bot's own memory and checked every
    # interval_check_seconds, closing via a real market order the instant the
    # polled price crosses it — same mechanism/cadence as comp11's paper
    # simulation. catastrophic_enabled/catastrophic_pct control an optional
    # (but default-on) wide real stop-loss resting on the exchange purely as
    # a backstop for a crash that outruns the in-memory check between polls —
    # user has explicitly acknowledged and accepted the risk of disabling it.
    # tp_on_exchange (default True): when True, the TAKE-PROFIT side of an
    # 'interval_check' agent is placed as a real resting order on the
    # exchange (watched continuously, fires the instant price touches it)
    # instead of being tracked purely in memory — there's no downside-risk
    # reason to keep TP polled-only, so this is purely an accuracy/timing
    # improvement with no tradeoff.
    # sl_on_exchange (default False): when True, the STOP-LOSS side is ALSO
    # placed as a real resting order, at the agent's actual (tight) sl_price
    # — not the wide catastrophic backstop. This gives up the comp11-style
    # tie-break/blind-spot matching that keeping SL in-memory provides, in
    # exchange for a real, continuously-watched stop and exact real fill
    # price reporting (no more "recorded exit assumed a perfect fill at the
    # SL level" mismatch vs what actually happened). Since a real tight SL
    # already covers the crash-protection role, the catastrophic_enabled/
    # catastrophic_pct backstop is skipped entirely whenever this is True —
    # stacking a second, wider stop order underneath it would be redundant.
    "agents": {
        # "Liquidity Hunt" (comp9/comp10's ATR-trailing version) removed —
        # losing in both its own source comps (comp9: -31.1%, comp10:
        # -25.7%). "The Liquidity Hunt" below is the profitable comp2
        # version of the same entry signal.
        "Surgeon v2":     {"enabled": True,  "direction": "SHORT", "start_balance": 0.0, "balance_initialized": False,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        # Ported from paper11 (comp11) — same signal logic, real money.
        # Deliberately added OFFLINE with $0 allocated and balance_initialized
        # already True (so the auto-balance-split logic never touches them) —
        # stays inert until start_balance is set and enabled is flipped on
        # via the dashboard.
        "Momentum":       {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        "The Structure":  {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        "Mean Reversion": {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        # Both added the same way as Momentum/The Structure/Mean Reversion
        # above — OFFLINE, $0 allocated, balance_initialized already True so
        # auto-balance-split never touches them — inert until the user sets
        # a start_balance and flips enabled on.
        "The Surgeon v2":    {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        "The Liquidity Hunt": {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
        "The Mean Reversion": {"enabled": False, "direction": "BOTH",  "start_balance": 0.0, "balance_initialized": True,
                            "max_open_positions": 9999, "max_positions_per_symbol": 9999,
                            "sl_tp_mode": "continuous", "interval_check_seconds": 10,
                            "catastrophic_enabled": True, "catastrophic_pct": 7.0,
                            "tp_on_exchange": True, "sl_on_exchange": False,
                            "sizing": {"mode": "percent", "fixed_usd": 10.0, "percent": 20.0}},
    },

    # Position sizing used ONLY for Manual Trade tickets (no agent involved) —
    # mode: "fixed" (USD amount) or "percent" (% of the account's live total balance).
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
    "min_notional_usd": 10.0,  # Lighter's exchange-enforced floor; sizing is bumped up to this if below

    # Which exchange actually executes real orders. "lighter" (default) keeps
    # everything exactly as it's always worked. "binance" routes every order
    # through binance_client.py instead — same agents, same signals, same
    # config, just a different exchange underneath. Switching requires the
    # bot to be stopped first (see server.py's /config handler) and takes
    # effect on the next ensure_client() call. API credentials for Binance
    # live in the .env file (BINANCE_API_KEY/BINANCE_API_SECRET/
    # BINANCE_TESTNET), never in this config file or the dashboard UI, same
    # security boundary as Lighter's own credentials.
    "platform": "lighter",

    "running": False,

    # Trades closed at/before this unix timestamp are hidden from the Trade
    # History table. The real trades still exist on Lighter (can't be erased,
    # it's exchange history) — this just clears the DISPLAYED table going
    # forward, e.g. to drop early manual test trades from the view.
    "trade_history_cutoff": 0,
}

# Seed each agent's editable trailing/SL-TP overrides from agents.py's
# hardcoded defaults, so "Trailing Settings" on the dashboard starts out
# showing exactly what's actually running, with a single source of truth
# for the numbers instead of duplicating them by hand here.
for _name in DEFAULT_CONFIG["agents"]:
    DEFAULT_CONFIG["agents"][_name]["trailing"] = _default_trailing_for(_name)
del _name


def _ensure_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)


def _deep_merge_defaults(default: dict, saved: dict) -> dict:
    """Backfills any keys missing from a previously-saved config (e.g. after
    adding new fields like per-agent balance/sizing) without discarding the
    user's saved values — recurses through nested dicts at any depth."""
    merged = dict(default)
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(default.get(k), dict):
            merged[k] = _deep_merge_defaults(default[k], v)
        else:
            merged[k] = v
    return merged


def load_config() -> dict:
    with _lock:
        _ensure_file()
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # backfill any new keys added after a user's config was already saved
        merged = dict(DEFAULT_CONFIG)
        for k, v in DEFAULT_CONFIG.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                if k == "agents":
                    # per-agent dicts (balance/sizing/etc) need their own
                    # backfill too, using each DEFAULT agent as the template
                    # for agents that already existed before these fields did.
                    merged_agents = dict(v)
                    for name, acfg in cfg[k].items():
                        template = v.get(name) or next(iter(v.values()))
                        merged_agents[name] = _deep_merge_defaults(template, acfg)
                    merged[k] = merged_agents
                else:
                    merged[k] = _deep_merge_defaults(v, cfg[k])
            elif k in cfg:
                merged[k] = cfg[k]
        return merged


def save_config(cfg: dict):
    with _lock:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
