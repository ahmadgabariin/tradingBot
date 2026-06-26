from paper.engine import fetch_candles, analyze, STOP_LOSS_PCT, TAKE_PROFIT_PCT

candles = fetch_candles("SOLUSDT", "15m", 1000)
print(f"SOL: {candles[60][3]:.2f} -> {candles[-1][3]:.2f}")

for i in range(60, len(candles) - 5):
    sig = analyze(candles[:i])
    if sig["signal"] != "BUY":
        continue
    entry = candles[i][3]
    sl = entry * (1 - STOP_LOSS_PCT)
    tp = entry * (1 + TAKE_PROFIT_PCT)

    outcome = "TIMEOUT"
    for j in range(i + 1, min(i + 30, len(candles))):
        if candles[j][2] <= sl:
            outcome = "LOSS"; break
        if candles[j][1] >= tp:
            outcome = "WIN"; break

    # How many candles until SL hit?
    candles_to_sl = None
    for j in range(i + 1, min(i + 30, len(candles))):
        if candles[j][2] <= sl:
            candles_to_sl = j - i
            break

    next5 = [candles[k][3] for k in range(i+1, min(i+6, len(candles)))]
    pct_moves = [(p/entry - 1)*100 for p in next5]

    print(f"[{i}] {outcome} @ {entry:.2f} | RSI={sig['rsi']:.0f} ADX={sig.get('adx',0)} Score={sig['score']}")
    print(f"     SL={sl:.2f}({STOP_LOSS_PCT*100:.1f}%) TP={tp:.2f}({TAKE_PROFIT_PCT*100:.1f}%)")
    print(f"     Next 5 candles: {[f'{p:+.2f}%' for p in pct_moves]}")
    print(f"     SL hit in {candles_to_sl} candles" if candles_to_sl else "     SL not hit in 30 candles")
    print()
