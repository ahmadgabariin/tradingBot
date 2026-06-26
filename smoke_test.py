from paper.engine import fetch_candles, analyze, TIMEFRAME, STOP_LOSS_PCT, TAKE_PROFIT_PCT, MIN_CONFIDENCE

pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
print(f"TF={TIMEFRAME} | SL={STOP_LOSS_PCT*100}% TP={TAKE_PROFIT_PCT*100}% MinConf={MIN_CONFIDENCE}")
print()
for p in pairs:
    c = fetch_candles(p)
    sig = analyze(c)
    print(f"{p}: ${sig['price']:.2f} | {sig['signal']} | score={sig['score']} | RSI={sig['rsi']:.1f}")
    for r in sig["reasons"][:4]:
        print(f"    {r}")
    print()
