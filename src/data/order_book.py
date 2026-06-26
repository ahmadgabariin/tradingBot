from loguru import logger


def analyze_order_book(order_book: dict) -> tuple[int, list[str]]:
    if not order_book or not order_book.get("bids") or not order_book.get("asks"):
        return 0, []

    bids = order_book["bids"][:10]
    asks = order_book["asks"][:10]

    bid_volume = sum(float(b[1]) for b in bids)
    ask_volume = sum(float(a[1]) for a in asks)
    total = bid_volume + ask_volume

    if total == 0:
        return 0, []

    bid_pct = bid_volume / total
    score = 0
    reasons = []

    if bid_pct >= 0.65:
        score += 15
        reasons.append(f"Strong buy pressure in order book ({bid_pct*100:.0f}% bids)")
    elif bid_pct >= 0.55:
        score += 8
        reasons.append(f"Moderate buy pressure ({bid_pct*100:.0f}% bids)")
    elif bid_pct <= 0.35:
        score -= 15
        reasons.append(f"Strong sell pressure in order book ({(1-bid_pct)*100:.0f}% asks)")
    elif bid_pct <= 0.45:
        score -= 8
        reasons.append(f"Moderate sell pressure ({(1-bid_pct)*100:.0f}% asks)")
    else:
        reasons.append(f"Balanced order book ({bid_pct*100:.0f}% bids)")

    # Check for large walls
    best_ask = float(asks[0][0])
    best_bid = float(bids[0][0])
    spread_pct = (best_ask - best_bid) / best_bid * 100

    if spread_pct > 0.1:
        score -= 5
        reasons.append(f"Wide spread ({spread_pct:.3f}%) — low liquidity")

    return score, reasons
