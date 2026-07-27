#!/usr/bin/env python3
"""
Price Bot — fetches XEL/USD price from CoinGecko (primary) / MEXC (fallback)
and pushes it to the PriceOracle contract on testnet.

Usage:
  ORACLE_HASH=083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6 \
  WALLET_RPC=http://127.0.0.1:18082 \
  WALLET_USER=wallet WALLET_PASS=testpass \
  python3 price_bot.py

Environment:
  ORACLE_HASH      (required) — PriceOracle contract hash
  WALLET_RPC       (default http://127.0.0.1:18082/json_rpc)
  WALLET_USER      (default wallet)
  WALLET_PASS      (default testpass)
  UPDATE_INTERVAL  (default 100) — block interval between checks
  MIN_CHANGE_BPS   (default 100) — minimum % change in bps to trigger update (100 = 1%)
  TIMELOCK_BLOCKS  (default 3)   — oracle timelock delay
"""

import os, sys, json, time, urllib.request, urllib.error, base64

ORACLE_HASH = os.environ.get("ORACLE_HASH", "083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6")
WALLET_RPC = os.environ.get("WALLET_RPC", "http://127.0.0.1:18082/json_rpc")
WALLET_USER = os.environ.get("WALLET_USER", "wallet")
WALLET_PASS = os.environ.get("WALLET_PASS", "testpass")
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "100"))
MIN_CHANGE_BPS = int(os.environ.get("MIN_CHANGE_BPS", "100"))
TIMELOCK_BLOCKS = int(os.environ.get("TIMELOCK_BLOCKS", "3"))

PRICE_DECIMALS = 100_000_000  # 8 decimals

def auth_header():
    token = base64.b64encode(f"{WALLET_USER}:{WALLET_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def wallet_rpc(method, params=None, id=1):
    payload = {"jsonrpc": "2.0", "method": method, "id": id}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        WALLET_RPC,
        data=json.dumps(payload).encode(),
        headers=auth_header()
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        raise Exception(f"RPC error: {resp['error']}")
    return resp.get("result")

def get_nonce():
    return wallet_rpc("get_nonce")

def build_and_broadcast(entry_id, params=None, deposits=None, max_gas=500000, permission="none", nonce=None):
    if nonce is None:
        nonce = get_nonce()
    invoke = {
        "contract": ORACLE_HASH,
        "entry_id": entry_id,
        "parameters": params or [],
        "deposits": deposits or {},
        "max_gas": max_gas,
        "permission": permission
    }
    tx_params = {
        "invoke_contract": invoke,
        "fee": {"fixed": 10000000},
        "broadcast": True,
        "nonce": nonce
    }
    result = wallet_rpc("build_transaction", tx_params)
    return result

def fetch_coingecko_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=xelis&vs_currencies=usd"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        price = resp.get("xelis", {}).get("usd")
        if price and price > 0:
            return price, "coingecko"
    except Exception as e:
        print(f"  coingecko error: {e}")
    return None, None

def fetch_mexc_price():
    url = "https://api.mexc.com/api/v3/ticker/price?symbol=XELUSDT"
    try:
        resp = json.loads(urllib.request.urlopen(url, timeout=10).read())
        price = float(resp.get("price", 0))
        if price > 0:
            return price, "mexc"
    except Exception as e:
        print(f"  mexc error: {e}")
    return None, None

def get_current_topoheight():
    """Get current topoheight from daemon"""
    payload = {"jsonrpc": "2.0", "method": "get_info", "id": 1}
    req = urllib.request.Request(
        "http://127.0.0.1:18081/json_rpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp.get("result", {}).get("topoheight", 0)

def atomic_from_usd(usd_price):
    return int(usd_price * PRICE_DECIMALS)

def usd_from_atomic(atomic):
    return atomic / PRICE_DECIMALS

last_proposed_price = None
current_topo = 0
next_check_topo = 0

print(f"Price bot started. Oracle: {ORACLE_HASH}")
print(f"Update interval: {UPDATE_INTERVAL} blocks, min change: {MIN_CHANGE_BPS} bps")
print(f"Wallet RPC: {WALLET_RPC}")
sys.stdout.flush()

while True:
    try:
        current_topo = get_current_topoheight()

        if current_topo < next_check_topo:
            time.sleep(5)
            continue

        next_check_topo = current_topo + UPDATE_INTERVAL

        price, source = fetch_coingecko_price()
        if price is None:
            price, source = fetch_mexc_price()
        if price is None:
            print(f"  [topo {current_topo}] failed to fetch price from all sources")
            sys.stdout.flush()
            continue

        atomic_price = atomic_from_usd(price)
        print(f"  [topo {current_topo}] {source}: ${price:.6f} → {atomic_price}")

        if last_proposed_price is not None:
            change_bps = abs(atomic_price - last_proposed_price) * 10000 // last_proposed_price
            if change_bps < MIN_CHANGE_BPS:
                print(f"  change {change_bps} bps < {MIN_CHANGE_BPS} bps, skipping")
                sys.stdout.flush()
                continue

        print(f"  proposing {atomic_price} (${price:.4f})")
        nonce = get_nonce()
        result = build_and_broadcast(
            entry_id=2,
            params=[{"type": "primitive", "value": {"type": "u64", "value": str(atomic_price)}}],
            nonce=nonce
        )
        print(f"  propose sent at nonce {nonce}, waiting {TIMELOCK_BLOCKS} blocks...")
        sys.stdout.flush()

        target_topo = current_topo + TIMELOCK_BLOCKS
        while get_current_topoheight() < target_topo:
            time.sleep(5)

        nonce2 = get_nonce()
        result2 = build_and_broadcast(
            entry_id=3,
            params=[],
            nonce=nonce2
        )
        print(f"  executing price at nonce {nonce2}")
        print(f"  ✅ Price updated to ${price:.4f}")
        last_proposed_price = atomic_price

    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)

    sys.stdout.flush()
    time.sleep(5)
