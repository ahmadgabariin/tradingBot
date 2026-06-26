from paper.engine import fetch_candles, analyze

pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

print("=== 1H TIMEFRAME ===")
all_candles_1h = {p: fetch_candles(p, "1h", 500) for p in pairs}
for sl, tp in [(0.005, 0.010), (0.008, 0.016), (0.010, 0.020), (0.012, 0.024), (0.015, 0.030)]:
    wins, losses = 0, 0
    for pair in pairs:
        candles = all_candles_1h[pair]
        for i in range(60, len(candles) - 5):
            sig = analyze(candles[:i])
            if sig["signal"] != "BUY":
                continue
            entry = candles[i][3]
            for j in range(i + 1, min(i + 48, len(candles))):
                if candles[j][2] <= entry * (1 - sl):
                    losses += 1; break
                if candles[j][1] >= entry * (1 + tp):
                    wins += 1; break
    total = wins + losses
    wr = wins / total if total > 0 else 0
    ev = wr * tp - (1 - wr) * sl
    print(f"  SL={sl*100:.1f}% TP={tp*100:.1f}% | {total} trades | {wr*100:.1f}% WR | EV={ev*100:+.3f}%")

print("\n=== 15M TIMEFRAME (more candles) ===")
all_candles_15m = {p: fetch_candles(p, "15m", 1000) for p in pairs}
for sl, tp in [(0.004, 0.008), (0.005, 0.010), (0.006, 0.012), (0.008, 0.016), (0.003, 0.009)]:
    wins, losses = 0, 0
    for pair in pairs:
        candles = all_candles_15m[pair]
        for i in range(60, len(candles) - 5):
            sig = analyze(candles[:i])
            if sig["signal"] != "BUY":
                continue
            entry = candles[i][3]
            for j in range(i + 1, min(i + 60, len(candles))):
                if candles[j][2] <= entry * (1 - sl):
                    losses += 1; break
                if candles[j][1] >= entry * (1 + tp):
                    wins += 1; break
    total = wins + losses
    wr = wins / total if total > 0 else 0
    ev = wr * tp - (1 - wr) * sl
    print(f"  SL={sl*100:.1f}% TP={tp*100:.1f}% | {total} trades | {wr*100:.1f}% WR | EV={ev*100:+.3f}%")
