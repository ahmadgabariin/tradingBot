"""
Standalone balance-fetch test — run directly to verify get_balance_usd()
works reliably before trusting it for percent-based position sizing.

Usage:
    C:/Python312/python.exe -m lighterbot.test_balance
"""
import asyncio, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        print("No .env found — copy .env.example to .env and fill in your keys first.")
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


async def main():
    _load_dotenv()
    from lighterbot.lighter_client import LighterClient

    print("Connecting to Lighter...")
    client = LighterClient()

    if client.client_check_error:
        print(f"❌ check_client() FAILED: {client.client_check_error}")
        print("   Fix LIGHTER_API_KEY_INDEX / LIGHTER_API_PRIVATE_KEY in .env before continuing.")
        return
    print("✅ check_client() passed — API key is valid for this account.\n")

    print("Fetching raw account object...")
    acct, err = await client._get_account_obj()
    if acct is None:
        print(f"❌ Could not fetch account: {err}")
        return

    dump = acct.to_dict() if hasattr(acct, "to_dict") else vars(acct)
    print("✅ Raw account record:")
    for k, v in dump.items():
        print(f"   {k}: {v}")

    print("\nFetching balance via get_balance_usd()...")
    balance, bal_err = await client.get_balance_usd()
    if balance is not None:
        print(f"✅ Balance: ${balance:.2f}")
    else:
        print(f"❌ Balance fetch failed: {bal_err}")

    print("\nFetching open positions...")
    positions, pos_err = await client.get_open_positions()
    if pos_err:
        print(f"❌ Positions fetch failed: {pos_err}")
    else:
        print(f"✅ Open positions: {len(positions)}")
        for p in positions:
            print(f"   {p}")

    # Run the balance fetch 3x in a row to check for flakiness/consistency
    print("\nRunning 3x consistency check...")
    for i in range(3):
        b, e = await client.get_balance_usd()
        print(f"   Attempt {i+1}: {'$'+format(b,'.2f') if b is not None else 'FAILED — '+str(e)}")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
