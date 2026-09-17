#!/usr/bin/env python3
"""Keep XEL/USD live using a configured wallet or three standalone providers.

--config PATH reads the existing CLI config without changing it. Without it,
standalone mode uses the three provider RPCs below. --rpc overrides the daemon
in either mode. Heartbeats follow each miner's on-chain last_heartbeat + hi.
Prices come from live exchanges only: cached prices are diagnostic, never fed
back into the oracle when sources fail.
"""
import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DEFAULTS, VAULT_DIR
from protocol import DAEMON_URL, Protocol, val_u64, _with_retries

DMAP_PATH = Path(__file__).resolve().parent.parent / "docs" / "entry_chunk_ids.json"
PRICE_CACHE_PATH = VAULT_DIR / "cache" / "oracle_last_good_price.json"
LOG = VAULT_DIR / "logs" / "oracle_keeper3.log"

PROVIDERS = [
    ("http://127.0.0.1:18086/json_rpc", 1),
    ("http://127.0.0.1:18087/json_rpc", 2),
    ("http://127.0.0.1:18088/json_rpc", 3),
]
FEED_ID = 0
FEED_DECIMALS = 8
# Real sources listing XEL/USDT; unavailable markets are ignored.
PRICE_SOURCES = [
    ("coinex", "https://api.coinex.com/v2/spot/ticker",
     {"market": "XELUSDT"}, ("data", 0, "last")),
    ("mexc", "https://api.mexc.com/api/v3/ticker/price",
     {"symbol": "XELUSDT"}, ("price",)),
    ("bitget", "https://api.bitget.com/api/v2/spot/market/tickers",
     {"symbol": "XELUSDT"}, ("data", 0, "lastPr")),
    ("gate", "https://api.gateio.ws/api/v4/spot/tickers",
     {"currency_pair": "XEL_USDT"}, (0, "last")),
]
SANITY_MIN = 0.001           # USD
SANITY_MAX = 10_000.0        # USD
MIN_SOURCES = 1             # One live source is enough.
SUBMIT_EVERY = 200           # blocks, below hard_stale=500
TX_FEE = 100_000             # 0.001 XEL/tx
LOOP_SECONDS = 10


@dataclass
class Provider:
    label: str
    protocol: Protocol
    address: str
    confirmed_heartbeat: int = 0


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _save_cached_price(price_atomic: int, sources: str) -> None:
    """Diagnostic snapshot only; never used as an input to submission."""
    try:
        PRICE_CACHE_PATH.write_text(json.dumps({
            "price_atomic": price_atomic, "sources": sources,
            "ts": int(time.time()),
        }), encoding="utf-8")
    except OSError:
        pass


def fetch_real_price() -> tuple[int | None, str]:
    """Median XEL/USD across public exchanges, or None if all sources fail."""
    vals = []
    for name, url, params, path in PRICE_SOURCES:
        try:
            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            d = r.json()
            for p in path:
                d = d[int(p)] if isinstance(p, int) else d[p]
            price = float(d)
            if SANITY_MIN < price < SANITY_MAX:
                vals.append((name, price))
        except Exception as e:
            log(f"  source {name}: {str(e)[:60]}")
    if len(vals) < MIN_SOURCES:
        return None, "no valid source"
    med = statistics.median([p for _, p in vals])
    used = ",".join(n for n, p in vals)
    return int(round(med * 10 ** FEED_DECIMALS)), f"median {med:.6f} USD [{used}]"


def load_wallets(config_path: Path | None, rpc: str | None) -> list[Provider]:
    """Validate wallet identity before allowing any keeper writes."""
    if config_path is not None:
        cfg = json.loads(config_path.expanduser().read_text(encoding="utf-8-sig"))
        if not isinstance(cfg, dict):
            raise ValueError("keeper config must be a JSON object")
        daemon_url = rpc or cfg.get("rpc_url")
        for key, value in (("rpc_url", daemon_url),
                           ("wallet_url", cfg.get("wallet_url")),
                           ("miner_address", cfg.get("miner_address"))):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"keeper config requires {key}")
        auth = (cfg.get("wallet_user", DEFAULTS["wallet_user"]),
                cfg.get("wallet_pass", DEFAULTS["wallet_pass"]))
        specs = [("configured wallet", cfg["wallet_url"], auth,
                  cfg["miner_address"].strip())]
        log("mode: configured wallet (no standalone providers)")
    else:
        daemon_url = rpc or DAEMON_URL
        specs = [(f"provider{idx}", url, ("wallet", "testpass"), None)
                 for url, idx in PROVIDERS]
        log("mode: standalone three-provider keeper")

    wallets = []
    for label, url, auth, expected in specs:
        try:
            pw = Protocol(wallet_url=url, wallet_auth=auth, daemon_url=daemon_url)
            address = pw.wallet.address()
            if not isinstance(address, str) or not address:
                raise ValueError("wallet RPC returned no address")
            if expected is not None and address != expected:
                raise ValueError("wallet address does not match configured miner_address")
        except Exception as e:
            raise RuntimeError(f"{label} initialization failed: {e}") from e
        wallets.append(Provider(label, pw, address))
        log(f"{label} ready ({address[:20]}...)")
    return wallets


def _has_successful_exit(logs: list, contract: str) -> bool:
    """Require an explicit zero exit; event-only/empty logs are inconclusive."""
    success = False
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "exit_error" or entry.get("exit_error") is not None:
            raise RuntimeError(f"execution reverted: {entry.get('value', entry.get('exit_error'))}")
        if kind == "exit_code":
            value = entry.get("value")
            code = value.get("code") if isinstance(value, dict) else value
        elif "exit_code" in entry:
            value = entry
            code = entry["exit_code"]
        else:
            continue
        owner = value.get("contract") if isinstance(value, dict) else None
        owner = owner or entry.get("contract")
        if owner is not None and owner != contract:
            continue
        if type(code) not in (int, str) or str(code) != "0":
            raise RuntimeError(f"execution exit_code={code!r} (expected 0)")
        success = True
    return success


def send(pw: Protocol, contract: str, chunk: int, params: list) -> bool:
    def build():
        result = pw.wallet._call("build_transaction", {
            "invoke_contract": {
                "contract": contract, "max_gas": 3_000_000,
                "entry_id": chunk, "parameters": params,
                "deposits": {}, "permission": "all"},
            "fee": {"fixed": TX_FEE}, "broadcast": True})
        tx = result.get("hash") if isinstance(result, dict) else None
        if not tx:
            raise RuntimeError("build_transaction returned no hash")
        return tx

    try:
        tx = _with_retries(build)
        if not pw.wait(tx, timeout=120):
            raise RuntimeError(f"tx {tx} was not confirmed")
        # Logs arrive asynchronously after inclusion. Never treat missing logs
        # (or revert_reason=None, which also means unknown) as execution success.
        for attempt in range(6):
            logs = pw.daemon.get_contract_logs(tx)
            if isinstance(logs, list) and _has_successful_exit(logs, contract):
                return True
            if attempt < 5:
                time.sleep(1.5)
        raise RuntimeError(f"tx {tx}: no confirmed exit_code=0 execution log")
    except Exception as e:
        log(f"  send failed {contract[:8]}#{chunk}: {str(e)[:180]}")
        return False


def heartbeat_round(wallets: list[Provider], miner_c: str, chunk: int, topo: int) -> None:
    try:
        daemon = wallets[0].protocol.daemon
        interval = int(daemon.read_key(miner_c, "hi"))
        timeout = int(daemon.read_key(miner_c, "ht"))
        if interval <= 0 or timeout <= 0:
            raise ValueError("hi/ht must be positive")
    except Exception as e:
        log(f"heartbeat schedule unavailable (hi/ht), skip: {str(e)[:100]}")
        return

    for provider in wallets:
        try:
            # Always refresh, including after restart or an uncertain send.
            miner = provider.protocol.daemon.read_key(miner_c, "miner_" + provider.address)
            if not isinstance(miner, list) or len(miner) < 15:
                raise ValueError("miner record unavailable; check registration and daemon RPC")
            if not miner[14]:
                log(f"  {provider.label}: miner inactive, skip heartbeat")
                continue
            chain_last = int(miner[6])  # Miner.last_heartbeat
            last = max(chain_last, provider.confirmed_heartbeat)
            if topo < last + interval:
                continue
            if topo > chain_last + timeout:
                log(f"  {provider.label}: heartbeat timeout exceeded ({timeout} blocks)")
            if send(provider.protocol, miner_c, chunk, []):
                # Do not advance this wallet's schedule on timeout/revert/unknown.
                provider.confirmed_heartbeat = topo
                log(f"  {provider.label}: heartbeat confirmed @topo {topo}")
            else:
                log(f"  {provider.label}: heartbeat failed, retry next pass")
            time.sleep(4)
        except Exception as e:
            log(f"  {provider.label}: heartbeat read failed, skip: {str(e)[:100]}")


def submit_prices(wallets: list[Provider], oracle_c: str, chunk_submit: int,
                  chunk_agg: int, topo: int) -> int:
    successes = 0
    poked = False
    for provider in wallets:
        # Each provider fetches independently. A disk snapshot is never fresh.
        price, desc = fetch_real_price()
        if price is None:
            log(f"  {provider.label}: no live price ({desc}), skip submission")
            continue
        if not poked:
            # Anti-deadlock: alreadysub otherwise prevents try_aggregate from
            # opening the next cycle. No poke is needed when all sources fail.
            send(wallets[0].protocol, oracle_c, chunk_agg, [val_u64(FEED_ID)])
            poked = True
            time.sleep(4)
        log(f"  {provider.label}: submit {price} atomic = "
            f"{price / 10**FEED_DECIMALS:.6f} USD ({desc})")
        if send(provider.protocol, oracle_c, chunk_submit, [val_u64(FEED_ID), val_u64(price)]):
            successes += 1
            _save_cached_price(price, desc)
        time.sleep(4)
    try:
        raw = wallets[0].protocol.daemon.read_key(oracle_c, "fg_" + str(FEED_ID))
        log(f"submit x{successes} confirmed @topo {topo} | fg_{FEED_ID}={raw}")
    except Exception:
        log(f"submit x{successes} confirmed @topo {topo}")
    return successes


def run(wallets: list[Provider], miner_c: str, oracle_c: str, chunks: dict) -> None:
    last_submit_topo = None
    while True:
        try:
            topo = wallets[0].protocol.daemon.topoheight()
            heartbeat_round(wallets, miner_c, chunks["heartbeat"], topo)
            if last_submit_topo is None or topo >= last_submit_topo + SUBMIT_EVERY:
                submit_prices(wallets, oracle_c, chunks["submit"], chunks["aggregate"], topo)
                last_submit_topo = topo
        except Exception as e:
            log(f"keeper pass failed: {str(e)[:180]}")
        # Failed heartbeats stay eligible on the next normal pass, not a tight loop.
        time.sleep(LOOP_SECONDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="existing CLI config JSON (single wallet)")
    parser.add_argument("--rpc", help="daemon RPC override for either launch mode")
    args = parser.parse_args(argv)
    try:
        dmap = json.loads(DMAP_PATH.read_text(encoding="utf-8"))

        def cid(contract: str, fn: str) -> int:
            return int(next(k for k, v in dmap[contract].items() if v["name"] == fn))

        chunks = {"submit": cid("StakedOracle", "submit_price"),
                  "heartbeat": cid("XelisVaultMiner", "submit_heartbeat"),
                  "aggregate": cid("StakedOracle", "aggregate_now")}
        wallets = load_wallets(args.config, args.rpc)
        p0 = wallets[0].protocol
        try:
            p0.daemon.topoheight()
        except Exception as e:
            raise RuntimeError(f"daemon RPC unavailable: {e}") from e
        miner_c = p0.resolve("XelisVaultMiner")
        oracle_c = p0.resolve("StakedOracle")
        log(f"contracts resolved: miner={miner_c}, oracle={oracle_c}")
        run(wallets, miner_c, oracle_c, chunks)
    except KeyboardInterrupt:
        log("keeper stopped")
        return 0
    except Exception as e:
        log(f"FATAL: keeper initialization/run failed: {str(e)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
