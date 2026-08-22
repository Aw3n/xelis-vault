#!/usr/bin/env python3
"""Oracle keeper: 3 provider wallets keep the XEL/USD feed alive.

Each cycle (~AGGREGATION_BLOCKS=5 blocks):
  - every provider submits a price (small jitter around BASE_PRICE)
Every HEARTBEAT_EVERY blocks:
  - each provider submits a heartbeat to stay active
Reverts ("alreadysub", nonce races) are tolerated; the loop just continues.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import Protocol, val_u64, _with_retries

STATE_PATH = Path(__file__).resolve().parent.parent / "docs" / "deployment_state.json"
DMAP_PATH = Path(__file__).resolve().parent.parent / "docs" / "entry_chunk_ids.json"

PROVIDERS = [
    ("http://127.0.0.1:18086/json_rpc", 1),
    ("http://127.0.0.1:18087/json_rpc", 2),
    ("http://127.0.0.1:18088/json_rpc", 3),
]
FEED_ID = 0
BASE_PRICE = 5_000_000        # 0.05 USD @8dp
# v12.1: spread max accepté par StakedOracle.aggregate = 500 bps (5%).
# ±200k (±4%) → spread 800 bps → branche slash-all à chaque agrégat.
JITTER = [50_000, 0, -50_000]  # ±1% → spread ~200 bps, sous le seuil
HEARTBEAT_EVERY = 60          # blocks (< interval 100)
LOG = "/tmp/oracle_keeper3.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main() -> None:
    state = json.loads(STATE_PATH.read_text())
    dmap = json.loads(DMAP_PATH.read_text())
    miner_c = state["contracts"]["XelisVaultMiner"]
    oracle_c = state["contracts"]["StakedOracle"]

    def cid(contract: str, fn: str) -> int:
        return int(next(k for k, v in dmap[contract].items() if v["name"] == fn))

    chunk_submit = cid("StakedOracle", "submit_price")
    chunk_hb = cid("XelisVaultMiner", "submit_heartbeat")
    chunk_agg = cid("StakedOracle", "aggregate_now")

    wallets = []
    for url, idx in PROVIDERS:
        pw = Protocol(wallet_url=url, wallet_auth=("wallet", "testpass"))
        wallets.append((idx, pw))
        log(f"provider{idx} prêt ({pw.wallet.address()[:20]}…)")

    p0 = wallets[0][1]
    last_topo = 0
    last_hb_topo = 0

    def send(pw: Protocol, contract: str, chunk: int, params: list) -> bool:
        def _b():
            return pw.wallet._call("build_transaction", {
                "invoke_contract": {
                    "contract": contract, "max_gas": 3_000_000,
                    "entry_id": chunk,
                    "parameters": params,
                    "deposits": {},
                    "permission": "all"},
                "fee": {"fixed": 10_000_000}, "broadcast": True})["hash"]
        try:
            tx = _with_retries(_b)
            pw.wait(tx, timeout=120)
            rev = pw.revert_reason(tx)
            if rev is not None:
                log(f"  revert {contract[:8]}#{chunk}: {rev}")
                return False
            return True
        except Exception as e:
            msg = str(e)[:80]
            if "alreadysub" in msg or "nonce" in msg.lower():
                log(f"  soft err: {msg}")
            else:
                log(f"  err: {msg}")
            return False

    while True:
        try:
            topo = p0.daemon.topoheight()
        except Exception as e:
            log(f"daemon err: {str(e)[:60]}")
            time.sleep(15)
            continue

        if topo >= last_hb_topo + HEARTBEAT_EVERY:
            for idx, pw in wallets:
                send(pw, miner_c, chunk_hb, [])
                time.sleep(4)
            last_hb_topo = topo
            log(f"heartbeats @topo {topo}")

        if topo >= last_topo + 5:
            # Anti-deadlock v12.1: si tous les miners ont déjà soumis dans le
            # cycle courant, plus personne ne peut déclencher try_aggregate
            # (le check alreadysub précède l'appel). Un poke explicite
            # aggregate_now ouvre le cycle suivant avant les soumissions.
            send(wallets[0][1], oracle_c, chunk_agg, [val_u64(FEED_ID)])
            time.sleep(4)
            okc = 0
            for (idx, pw), jit in zip(wallets, JITTER):
                price = BASE_PRICE + jit
                if send(pw, oracle_c, chunk_submit, [val_u64(FEED_ID), val_u64(price)]):
                    okc += 1
                time.sleep(4)
            # lecture directe de l'agrégat
            try:
                raw = p0.daemon.read_key(oracle_c, "fg_" + str(FEED_ID))
                if isinstance(raw, dict):
                    log(f"submit x{okc} @topo {topo} | agg={raw.get('price', raw)}")
                elif raw is not None:
                    log(f"submit x{okc} @topo {topo} | fg_0={raw}")
                else:
                    log(f"submit x{okc} @topo {topo} | pas encore d'agrégat")
            except Exception:
                log(f"submit x{okc} @topo {topo}")
            last_topo = topo

        time.sleep(10)


if __name__ == "__main__":
    main()
