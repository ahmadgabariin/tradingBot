from paper.engine import fetch_candles, analyze, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TIMEFRAME

pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
print(f"Settings: SL={STOP_LOSS_PCT*100:.1f}% TP={TAKE_PROFIT_PCT*100:.1f}% TF={TIMEFRAME}")
print("=" * 65)

for label, limit, start_idx, end_idx in [
    ("FULL 41d", 1000, 60, None),
    ("BULL PHASE (first 500)", 1000, 60, 500),
    ("BEAR PHASE (last 500)", 1000, 500, None),
]:
    print(f"\n[ {label} ]")
    all_wins, all_losses = 0, 0
    for pair in pairs:
        candles = fetch_candles(pair, TIMEFRAME, limit)
        phase = candles[start_idx:end_idx] if end_idx else candles[start_idx:]
        full  = candles  # need full history for indicators

        wins, losses = 0, 0
        for i in range(start_idx, (end_idx or len(full)) - 5):
            sig = analyze(full[:i])
            if sig["signal"] != "BUY":
                continue
            entry = full[i][3]
            sl = entry * (1 - STOP_LOSS_PCT)
            tp = entry * (1 + TAKE_PROFIT_PCT)
            for j in range(i + 1, min(i + 48, len(full))):
                if full[j][2] <= sl:
                    losses += 1; break
                if full[j][1] >= tp:
                    wins += 1; break
        total = wins + losses
        wr = round(wins / total * 100, 1) if total > 0 else 0
        mkt = candles[start_idx][3]; mkt_end = candles[(end_idx or len(candles)) - 1][3]
        mkt_move = f"{(mkt_end/mkt-1)*100:+.1f}%"
        print(f"  {pair}: {wins+losses} trades | {wins}W/{losses}L | {wr}% WR | market {mkt_move}")
        all_wins += wins; all_losses += losses
    t = all_wins + all_losses
    wr = round(all_wins / t * 100, 1) if t else 0
    ev = (all_wins * TAKE_PROFIT_PCT - all_losses * STOP_LOSS_PCT) / max(t, 1) * 100
    print(f"  TOTAL: {t} trades | {all_wins}W/{all_losses}L | {wr}% WR | EV={ev:+.3f}%/trade")
