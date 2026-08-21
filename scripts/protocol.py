#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — Protocol Client (protocol.py)
============================================================================
Canonical on-chain interaction layer for the deployed XELIS Vault protocol.

- Wallet RPC (build_transaction / invoke_contract + deposits) for writes
- Daemon RPC (get_contract_data, get_asset, get_contract_logs) for reads
- Registry resolution (cur_<Name>) with fallback to deployed-hash table
- Entry chunk-id map (docs/entry_chunk_ids.json) — entry_id = compiled chunk
- Op wrappers for every externally-invokable protocol flow

Live environment (testnet):
  daemon  http://127.0.0.1:18081/json_rpc
  wallet  http://127.0.0.1:18082/json_rpc  (basic auth wallet:testpass)
============================================================================
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"

# ---------------------------------------------------------------------------
# Live environment
# ---------------------------------------------------------------------------
DAEMON_URL = "http://127.0.0.1:18081/json_rpc"
WALLET_URL = "http://127.0.0.1:18082/json_rpc"
WALLET_AUTH = ("wallet", "testpass")

ZERO_HASH = "0" * 64

ADMIN = "xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v"

# Canonical asset hashes (verified on-chain)
XEL_ASSET = ZERO_HASH                      # native XELIS (8 decimals)
VLT_ASSET = "9d074e1b0c057dbd30897f10117e4feb1d8d6442306bc23ac763c87c9f73b89a"
XUSD_ASSET = "a04b10a46698c97f3e465882dee5827e62360c30060f33f3604179769bc65100"

ASSET_NAMES = {
    XEL_ASSET: "XEL",
    VLT_ASSET: "VLT",
    XUSD_ASSET: "xUSD",
}

DECIMALS = {XEL_ASSET: 8, VLT_ASSET: 8, XUSD_ASSET: 8}

# Registered contract hashes (deploy log — registry cur_<Name> is authoritative)
CONTRACT_HASHES = {
    "ContractRegistry": "840b810c32f24b516ba5d65accef8cb706355e076a2c41ea98f2afce009f1a14",
    "ComplianceModule": "7d20ea3646e5c308b9153353f68c24e8f161bc43392f092ea138a5498f132f78",
    "VLTToken": "efd53bfa46d9fbb7494cca716cd86990299851705d408fcbff0e05d00bb09ac6",
    "xUSD": "87242c12262bf4d7144842a06e91d96af53e5ce5b786e10ccb5c687be4658ae8",
    "FaucetContract": "7da83d17c4db825083b4ae85ab95ff50654999ebf4847e284bcf11549f14256d",
    "XelisVaultMiner": "0dc49c50dabf9c97ee2efaa76d17013922a89855f63233821ed6d4c445505cbf",
    "StakedOracle": "159594c8a5a856c9bc1063271ce8930500f1cab6fcc0e2bf604c78561ec09605",
    "MinerPool": "86895d2f16fc293f3e29234b9daa6a0482be4a061e76265af049baa13e9bd275",
    "InterestRateModel": "172214c5d10f967f73e3c12832b74a6b17ce05aa9d656936ce4be0d1fbd6e2de",
    "VaultEngine": "2c22a6132fb4f21719c2acf04fe5c10f8cb796cba421b60c8d250d32a1a8b393",
    "SavingsRate": "a275a8e2cc97db7d5fb519c5d9a952fcaa9c36e55a5870339b468c7acc68c043",
    "FlashLoan": "7dcbf096f4d6f30366316e38736eb75124a9b8054624a974d4cadae7f5edf729",
    "FlashCallback": "f151220561b7d956fbd32b236111b6fc6c152c6a1d384c94b8bd5ea4fc76ea60",
    "VaultSwap": "03d3adea88c15e41105814f3f67e58f2036f593ea96a307bfbf5336356f5782a",
    "PSM": "fb8609b547e52e1364776457d88ba9b3a84d80ecf60d28ac34700626c2d7c0a6",
    "LendingMarket": "74809c24efbb2817589a6d379922a3e92650857d447f7917905a1514293f1519",
    "PeerLoan": "39de766f32a9d297fc99eaf0c7ddefafc5b2785b4b78fd63d3a0f170e4dec485",
    "SyndicatePool": "6ac66dfa4407b7a126b223e0ba4d2159f423a4806bf3031d6a9c32742d26258a",
    "SealedBidAuction": "d3b48725a4a4327249130efb3405be80b6caadbe255db00b3bbb4b1d91be3155",
    "PrivacyMixer": "c78b2e903f366519884533d75c67428521f8397af02110f2a4fe4f90bfadb79d",
    "AssetVault": "48806089766985050a81917bcfdf919dcd27df9780bcb6a16faa8e28bd06dd2b",
    "TreasuryVault": "0b2cf9761ebc8a746e4418b80fdfaef0e940f12891deef12e65b60df304c6d70",
    "RevenueShare": "beb733d651e682ab7023ca1ae41963837c5d80af6894343657051b29ac9eaa6c",
    "Payroll": "edbfb5fd0a105aaf087b8bf7f0133bd99da6ac36b83b071780eac56e0df42771",
    "InsurancePool": "bc74bae34e763895ed5795ba540ba1e60926777782b84b9d815707835962b8da",
    "PrivateInsurance": "7e313998ccba0651bfeab12c8d6ff7153cfcf14c0e7486c51194430dc045e20f",
    "GovernanceVault": "65138ab138ff0f3a73852b54767e23b84c20a110bc62f59ca09b678eaef71d56",
    "Timelock": "0c4742beb58ee4b5a2d1d7059c87bb8592b6a6dbdcf8267dec4d01d8fc748cea",
    "Governor": "bfdbbf77eccdb2101f8ad60ee3714f38918abcaa4741850160b58d875d54eded",
    "GuardianMultisig": "435e001c412cc1b434045a4b5e86e8117a98013856426582945d0de1dd29a373",
    "OracleGovernance": "97f51a646774f27cbff1508c7324845e5ed806f75ee399f259eb309bdd10cb9e",
    "VaultChat": "7560b5e33b8fde6cf5f6c81117320cfb9d7294c7edd6aa2e6c41ffdee8d7c7d2",
    "FounderVesting4y": "99ee70127dbf856f04f86bd60a55533e1ef22e7602f88978384edf7aff75da55",
    "FounderVesting10y": "d919ca28731428d7ec96238412b66c6eb33edde6eb466873ec74ec4bb20efda3",
    "FeeDistributor": "29fb3abf45d7aea116b07baaf4d79ca8c01daf7c4921fca328b4f42421a5de6a",
    "MinerDelegation": "e3c2f0f7a21502cce3b8d197a04876cbf441b75345d8dd7da64b512c66f48140",
}

# Oracle feed ids
FEED_XEL_USD = 0
FEED_IDS = {FEED_XEL_USD: "XEL/USD"}
FEED_ASSETS = {FEED_XEL_USD: XEL_ASSET}
FEED_DECIMALS = {FEED_XEL_USD: 8}

# Miner service ids (XelisVaultMiner.register_service)
SERVICE_ORACLE = 1
SERVICE_CHAT = 2

MIN_STAKE_VLT = 100_000_000_000  # 1000 VLT (v10.7 anti-Sybil)

TX_CONFIRM_TIMEOUT = 120
INVOKE_FEE = 10_000_000        # 0.1 XEL
DEPLOY_FEE = 100_000_000       # 1 XEL
INVOKE_GAS = 5_000_000
HEAVY_GAS = 10_000_000


# ---------------------------------------------------------------------------
# ValueCell builders (adjacently tagged)
# ---------------------------------------------------------------------------
def _prim(t: str, v: Any) -> dict:
    return {"type": "primitive", "value": {"type": t, "value": v}}


def val_u64(n: int) -> dict:
    return _prim("u64", str(n))


def val_u128(n: int) -> dict:
    return _prim("u128", str(n))


def val_u8(n: int) -> dict:
    return _prim("u8", int(n))


def val_u16(n: int) -> dict:
    return _prim("u16", int(n))


def val_bool(b: bool) -> dict:
    return _prim("boolean", bool(b))


def val_str(s: str) -> dict:
    return _prim("string", s)


def val_hash(hexstr: str) -> dict:
    return _prim("opaque", {"type": "Hash", "value": hexstr})


def val_addr(addr: str) -> dict:
    return _prim("opaque", {"type": "Address", "value": addr})


def val_bytes(hexstr: str) -> dict:
    return {"type": "bytes", "value": hexstr}


def parse_cell(cell: dict) -> Any:
    """Parse a ValueCell into a python value (best effort)."""
    if not isinstance(cell, dict):
        return cell
    t = cell.get("type")
    if t == "primitive":
        v = cell.get("value", {})
        vt = v.get("type")
        val = v.get("value")
        if vt in ("u8", "u16", "u32"):
            return int(val)
        if vt in ("u64", "u128", "amount", "balance", "nonce", "fee"):
            try:
                return int(val)
            except (TypeError, ValueError):
                return val
        if vt == "boolean":
            return bool(val)
        if vt == "string":
            return val
        if vt == "opaque":
            # nested type: Hash / Address / PublicKey / ...
            if isinstance(val, dict):
                return val.get("value", val)
            return val
        return val
    if t == "bytes":
        return cell.get("value")
    if t == "object":
        # custom struct — return list of parsed field values
        items = cell.get("value") or []
        return [parse_cell(i) for i in items]
    return cell


# ---------------------------------------------------------------------------
# Entry chunk-id map
# ---------------------------------------------------------------------------
_ENTRY_MAP: Optional[dict] = None

# Registry names -> entry-chunk map keys (registry name != source module name
# for some contracts: the registry keeps deploy names, the chunk map is keyed
# by the compiled module's source name).
_ENTRY_ALIASES = {
    "VaultEngine": "VaultEngineV3",
    "VaultSwap": "VaultSwapV2",
    "FounderVesting4y": "FounderVesting",
    "FounderVesting10y": "FounderVesting",
}


def _entry_key(name: str) -> str:
    return _ENTRY_ALIASES.get(name, name)


def entry_map() -> dict:
    global _ENTRY_MAP
    if _ENTRY_MAP is None:
        path = DOCS / "entry_chunk_ids.json"
        if not path.exists():
            raise RuntimeError(f"entry chunk map not found: {path}")
        _ENTRY_MAP = json.loads(path.read_text())
    return _ENTRY_MAP


def entry_id(contract_name: str, fn: str) -> int:
    m = entry_map().get(_entry_key(contract_name))
    if not m:
        raise RuntimeError(f"no entry map for contract {contract_name}")
    if fn not in m:
        raise RuntimeError(f"{contract_name}.{fn} is not an Entry chunk "
                          f"(All/pub-fn chunks are not wallet-invokable)")
    return m[fn]


def list_entries(contract_name: str) -> dict:
    return entry_map().get(contract_name, {})


# ---------------------------------------------------------------------------
# RPC clients
# ---------------------------------------------------------------------------
class RPCError(RuntimeError):
    """RPC failure. transient=True when a retry after a short sleep can fix it
    (nonce race, proof-verification race, temporary storage miss)."""

    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


def _is_transient(method: str, err: dict) -> bool:
    msg = str(err.get("message", "")).lower()
    if "nonce" in msg and ("already used" in msg or "expected" in msg):
        return True
    if "proof verification error" in msg:
        return True
    if "not enough funds" in msg:
        return False  # permanent — funding required, retrying won't help
    if method == "get_transaction" and "not found" in msg:
        return False
    return False


def _post(url: str, method: str, params: Any, auth: Optional[tuple] = None,
          timeout: int = 60) -> Any:
    payload: dict = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        payload["params"] = params
    r = requests.post(url, auth=auth, json=payload, timeout=timeout)
    data = r.json()
    if data.get("error"):
        err = data["error"]
        raise RPCError(f"{method}: {err}",
                       transient=_is_transient(method, err))
    return data.get("result")


def _with_retries(fn, attempts: int = 4, delay: float = 8.0):
    """Run fn(); retry on transient RPC errors (nonce / proof races)."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn()
        except RPCError as e:
            if not e.transient:
                raise
            last = e
            time.sleep(delay)
        except requests.RequestException as e:
            last = e
            time.sleep(delay)
    raise last


class WalletClient:
    """xelis_wallet v1.25 — build_transaction (flattened TransactionTypeBuilder)."""

    def __init__(self, url: str = WALLET_URL, auth: tuple = WALLET_AUTH):
        self.url = url
        self.auth = auth

    def _call(self, method: str, params: Any = None) -> Any:
        return _post(self.url, method, params, auth=self.auth)

    def address(self) -> str:
        return self._call("get_address")

    def balance(self, asset: str = XEL_ASSET) -> int:
        return int(self._call("get_balance", {"asset": asset}))

    def track_asset(self, asset: str) -> None:
        self._call("track_asset", {"asset": asset})

    def invoke(self, contract: str, entry: int, params: Optional[list] = None,
               deposits: Optional[dict] = None, max_gas: int = INVOKE_GAS,
               fee: int = INVOKE_FEE, broadcast: bool = True) -> str:
        """Build + broadcast an invoke_contract transaction. Returns tx hash.

        Waits for the wallet's stored nonce to catch up with the daemon
        (the wallet syncs its nonce lazily), then retries on nonce /
        proof-verification races."""
        self._wait_nonce_catchup()

        def _build() -> str:
            payload = {
                "invoke_contract": {
                    "contract": contract,
                    "max_gas": max_gas,
                    "entry_id": entry,
                    "parameters": params or [],
                    "deposits": deposits or {},
                    "permission": "all",
                },
                "fee": {"fixed": fee},
                "broadcast": broadcast,
            }
            result = self._call("build_transaction", payload)
            tx_hash = result.get("hash") if isinstance(result, dict) else None
            if not tx_hash:
                raise RPCError(f"build_transaction returned no hash: {result}")
            return tx_hash
        tx = _with_retries(_build)
        # wait for wallet nonce to advance (confirms tx was processed)
        self.wait_nonce_advance(int(self._call("get_nonce")), timeout=180)
        return tx

    def wait_nonce_advance(self, before: int, timeout: int = 120) -> int:
        """Wait until the wallet's stored nonce advances past `before`."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            n = int(self._call("get_nonce"))
            if n > before:
                return n
            time.sleep(5)
        return int(self._call("get_nonce"))

    def _wait_nonce_catchup(self, timeout: int = 120) -> None:
        """Wait until the wallet's stored nonce >= the daemon's account nonce."""
        addr = self.address()
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                w = int(self._call("get_nonce"))
                d = int(_post(DAEMON_URL, "get_nonce",
                              {"address": addr}).get("nonce", 0))
                if w >= d:
                    return
            except Exception:
                pass
            time.sleep(5)

    def transfer(self, to: str, amount: int, asset: str = XEL_ASSET,
                 fee: int = INVOKE_FEE) -> str:
        self._wait_nonce_catchup()

        def _build() -> str:
            payload = {
                "transfers": [{"destination": to, "amount": amount,
                               "asset": asset}],
                "fee": {"fixed": fee},
                "broadcast": True,
            }
            result = self._call("build_transaction", payload)
            tx_hash = result.get("hash") if isinstance(result, dict) else None
            if not tx_hash:
                raise RPCError(f"transfer returned no hash: {result}")
            return tx_hash
        return _with_retries(_build)


class DaemonClient:
    def __init__(self, url: str = DAEMON_URL):
        self.url = url

    def _call(self, method: str, params: Any = None) -> Any:
        return _post(self.url, method, params)

    def topoheight(self) -> int:
        return int(self._call("get_topoheight"))

    def get_contract_data(self, contract: str, key: dict) -> Any:
        """Raw get_contract_data. Raises RPCError when key never set."""
        return self._call("get_contract_data",
                          {"contract": contract, "key": key})

    def read_key(self, contract: str, key_str: str) -> Any:
        """Read a string-keyed storage cell; returns parsed value or None."""
        try:
            res = self.get_contract_data(contract, val_str(key_str))
        except RPCError:
            return None
        data = res.get("data") if isinstance(res, dict) else None
        if data is None:
            return None
        return parse_cell(data)

    def read_hash_key(self, contract: str, key: dict) -> Any:
        try:
            res = self.get_contract_data(contract, key)
        except RPCError:
            return None
        data = res.get("data") if isinstance(res, dict) else None
        if data is None:
            return None
        return parse_cell(data)

    def get_asset(self, asset: str) -> Optional[dict]:
        try:
            return self._call("get_asset", {"asset": asset})
        except RPCError:
            return None

    def get_contract_balance(self, contract: str, asset: str) -> int:
        try:
            res = self._call("get_contract_balance",
                             {"contract": contract, "asset": asset})
        except RPCError:
            return 0
        if isinstance(res, dict):
            return int(res.get("data", 0))
        return int(res) if res else 0

    def get_transaction(self, tx_hash: str) -> Optional[dict]:
        try:
            return self._call("get_transaction", {"hash": tx_hash})
        except RPCError:
            return None

    def get_contract_logs(self, caller: str) -> list:
        try:
            res = self._call("get_contract_logs", {"caller": caller})
            return res if isinstance(res, list) else []
        except RPCError:
            return []


# ---------------------------------------------------------------------------
# Protocol facade
# ---------------------------------------------------------------------------
class Protocol:
    def __init__(self, wallet: Optional[WalletClient] = None,
                 daemon: Optional[DaemonClient] = None,
                 wallet_url: str = WALLET_URL,
                 wallet_auth: tuple = WALLET_AUTH,
                 daemon_url: str = DAEMON_URL):
        if wallet is None:
            wallet = WalletClient(url=wallet_url, auth=wallet_auth)
        if daemon is None:
            daemon = DaemonClient(url=daemon_url)
        self.wallet = wallet
        self.daemon = daemon
        self._registry_cache: dict[str, str] = {}

    # --- resolution --------------------------------------------------------
    def resolve(self, name: str) -> str:
        """Registry cur_<Name> first, then static deploy table."""
        name = name.replace("VaultEngineV3", "VaultEngine")
        if name in self._registry_cache:
            return self._registry_cache[name]
        h = self.daemon.read_key(CONTRACT_HASHES["ContractRegistry"],
                                 f"cur_{name}")
        if h:
            self._registry_cache[name] = h
            return h
        if name in CONTRACT_HASHES:
            return CONTRACT_HASHES[name]
        raise RuntimeError(f"cannot resolve contract {name}")

    def hash_of(self, name: str) -> str:
        return self.resolve(name)

    def entry(self, name: str, fn: str) -> int:
        return entry_id(name, fn)

    # --- reads -------------------------------------------------------------
    def read(self, name: str, key_str: str) -> Any:
        return self.daemon.read_key(self.resolve(name), key_str)

    def read_contract(self, contract_hash: str, key_str: str) -> Any:
        return self.daemon.read_key(contract_hash, key_str)

    def topoheight(self) -> int:
        return self.daemon.topoheight()

    def price(self, asset: str = XEL_ASSET) -> Optional[int]:
        """Aggregated XEL/USD price (fg_<feed_id> struct) — needs 3+ active miners."""
        oracle = self.resolve("StakedOracle")
        fid = FEED_XEL_USD
        agg = self.read_contract(oracle, f"fg_{fid}")
        if agg and isinstance(agg, list) and len(agg) >= 1:
            return int(agg[0])
        return None

    # --- writes ------------------------------------------------------------
    def invoke(self, name: str, fn: str, params: Optional[list] = None,
               deposits: Optional[dict] = None, max_gas: int = INVOKE_GAS,
               fee: int = INVOKE_FEE) -> str:
        contract = self.resolve(name)
        eid = self.entry(name, fn)
        return self.wallet.invoke(contract, eid, params, deposits,
                                  max_gas=max_gas, fee=fee)

    def invoke_hash(self, contract_hash: str, eid: int,
                    params: Optional[list] = None,
                    deposits: Optional[dict] = None,
                    max_gas: int = INVOKE_GAS, fee: int = INVOKE_FEE) -> str:
        return self.wallet.invoke(contract_hash, eid, params, deposits,
                                  max_gas=max_gas, fee=fee)

    def wait(self, tx_hash: str, timeout: int = TX_CONFIRM_TIMEOUT) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            res = self.daemon.get_transaction(tx_hash)
            if res:
                return res
            time.sleep(3)
        raise TimeoutError(f"tx {tx_hash} not confirmed in {timeout}s")

    def confirm(self, tx_hash: str, label: str = "") -> str:
        self.wait(tx_hash)
        if label:
            print(f"[ok] {label}: {tx_hash[:16]}...")
        return tx_hash

    def revert_reason(self, tx_hash: str, timeout: float = 8.0) -> Optional[str]:
        """Return the contract revert message, or None on success/unknown.

        Logs are written asynchronously by the daemon after mining — poll
        until the exit entry appears (empty logs would otherwise be read as
        success)."""
        deadline = time.time() + timeout
        while True:
            try:
                logs = self.daemon.get_contract_logs(tx_hash)
            except RPCError:
                logs = []
            if isinstance(logs, list) and logs:
                for entry in logs:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("type") == "exit_error":
                        v = entry.get("value") or {}
                        err = v.get("err") if isinstance(v, dict) else None
                        if isinstance(err, dict):
                            return err.get("message") or str(err)
                        return str(err)
                    if entry.get("exit_error"):
                        return str(entry["exit_error"])
                return None
            if time.time() >= deadline:
                return None
            time.sleep(1.5)

    # --- balance helpers ----------------------------------------------------
    def balance(self, asset: str = XEL_ASSET) -> int:
        return self.wallet.balance(asset)

    def contract_balance(self, name: str, asset: str) -> int:
        return self.daemon.get_contract_balance(self.resolve(name), asset)

    def send(self, to: str, amount: int, asset: str = XEL_ASSET) -> str:
        return self.wallet.transfer(to, amount, asset)


# ---------------------------------------------------------------------------
# Op wrappers — Oracle
# ---------------------------------------------------------------------------
def oracle_submit_price(p: Protocol, price_atomic: int, feed_id: int = FEED_XEL_USD,
                        max_gas: int = 500_000, fee: int = 1_000_000) -> str:
    """StakedOracle.submit_price — caller must be an active miner (svc 1).
    Low fee/gas by default: submit_price uses very little gas."""
    return p.invoke("StakedOracle", "submit_price",
                    [val_u64(feed_id), val_u64(price_atomic)],
                    max_gas=max_gas, fee=fee)


def oracle_aggregate_now(p: Protocol, feed_id: int = FEED_XEL_USD) -> str:
    return p.invoke("StakedOracle", "aggregate_now", [val_u64(feed_id)])


def oracle_feed_info(p: Protocol, feed_id: int = FEED_XEL_USD) -> dict:
    """Read feed struct (fd_<id> object), activeness (fa_<id>),
    aggregated price (fg_<id>), last aggregation (la_<id>), cycle (cy_<id>)."""
    oracle = p.resolve("StakedOracle")
    info: dict[str, Any] = {}
    feed = p.read_contract(oracle, f"fd_{feed_id}")
    if feed and isinstance(feed, list) and len(feed) >= 7:
        info["id"] = feed[0]
        info["name"] = feed[1]
        info["asset"] = feed[2]
        info["decimals"] = feed[3]
        info["min_price"] = feed[4]
        info["max_price"] = feed[5]
        info["created_at"] = feed[6]
    info["active"] = p.read_contract(oracle, f"fa_{feed_id}")
    agg = p.read_contract(oracle, f"fg_{feed_id}")
    if agg and isinstance(agg, list) and len(agg) >= 5:
        info["agg_price"] = agg[0]
        info["agg_topo"] = agg[1]
        info["agg_deviation_bps"] = agg[2]
        info["agg_sources"] = agg[3]
        info["agg_cycle"] = agg[4]
    info["last_agg"] = p.read_contract(oracle, f"la_{feed_id}")
    info["cycle"] = p.read_contract(oracle, f"cy_{feed_id}")
    return info


def oracle_active_providers(p: Protocol) -> int:
    """Active miners registered for oracle service (sm_<service>)."""
    v = p.read_contract(p.resolve("XelisVaultMiner"), f"sm_{SERVICE_ORACLE}")
    return int(v) if v else 0


# ---------------------------------------------------------------------------
# Op wrappers — Miner
# ---------------------------------------------------------------------------
def miner_register(p: Protocol, endpoint_url: str, miner_pubkey: str,
                   services_mask: int = SERVICE_ORACLE,
                   stake_vlt: int = MIN_STAKE_VLT) -> str:
    """XelisVaultMiner.register_miner — deposits stake_vlt VLT (min 1000)."""
    return p.invoke("XelisVaultMiner", "register_miner",
                    [val_str(endpoint_url), val_hash(miner_pubkey),
                     val_u8(services_mask)],
                    deposits={VLT_ASSET: {"amount": stake_vlt}},
                    max_gas=HEAVY_GAS)


def miner_heartbeat(p: Protocol) -> str:
    return p.invoke("XelisVaultMiner", "submit_heartbeat", [])


def miner_active_count(p: Protocol) -> int:
    """Total registered miners (MINERS_COUNT_KEY = mc)."""
    v = p.read_contract(p.resolve("XelisVaultMiner"), "mc")
    return int(v) if v else 0


def miner_total_staked(p: Protocol) -> int:
    v = p.read_contract(p.resolve("XelisVaultMiner"), "ts")
    return int(v) if v else 0


# ---------------------------------------------------------------------------
# Op wrappers — VaultEngine (XEL collateral → xUSD debt)
# ---------------------------------------------------------------------------
def vault_deposit(p: Protocol, amount_xel: int, salt: str = "0" * 64) -> str:
    """deposit(collateral_asset, collateral_amount, salt) — deposits XEL."""
    return p.invoke("VaultEngine", "deposit",
                    [val_hash(XEL_ASSET), val_u64(amount_xel), val_hash(salt)],
                    deposits={XEL_ASSET: {"amount": amount_xel}},
                    max_gas=HEAVY_GAS)


def vault_borrow(p: Protocol, vault_id: int, amount_xusd: int) -> str:
    return p.invoke("VaultEngine", "borrow",
                    [val_u64(vault_id), val_u64(amount_xusd)])


def vault_repay(p: Protocol, vault_id: int, amount_xusd: int) -> str:
    return p.invoke("VaultEngine", "repay",
                    [val_u64(vault_id), val_u64(amount_xusd)],
                    deposits={XUSD_ASSET: {"amount": amount_xusd}})


def vault_withdraw(p: Protocol, vault_id: int, amount_xel: int) -> str:
    return p.invoke("VaultEngine", "withdraw",
                    [val_u64(vault_id), val_u64(amount_xel)])


def vault_liquidate(p: Protocol, vault_id: int,
                    max_borrow_to_repay: int) -> str:
    return p.invoke("VaultEngine", "liquidate",
                    [val_u64(vault_id), val_u64(max_borrow_to_repay)])


def vault_redeem(p: Protocol, amount_xusd: int) -> str:
    return p.invoke("VaultEngine", "redeem", [val_u64(amount_xusd)])


def vault_total(p: Protocol) -> int:
    """Vault id counter (COUNTER_KEY = n)."""
    v = p.read_contract(p.resolve("VaultEngine"), "n")
    return int(v) if v else 0


# ---------------------------------------------------------------------------
# Op wrappers — PSM (1:1 XEL <-> xUSD at oracle price)
# ---------------------------------------------------------------------------
def psm_mint(p: Protocol, xel_amount: int, min_xusd_out: int) -> str:
    if min_xusd_out <= 0:
        raise ValueError("psm_mint: min_xusd_out must be > 0 (contract rejects 0)")
    return p.invoke("PSM", "mint",
                    [val_u64(xel_amount), val_u64(min_xusd_out)],
                    deposits={XEL_ASSET: {"amount": xel_amount}})


def psm_redeem(p: Protocol, xusd_amount: int, min_xel_out: int) -> str:
    if min_xel_out <= 0:
        raise ValueError("psm_redeem: min_xel_out must be > 0 (contract rejects 0)")
    return p.invoke("PSM", "redeem",
                    [val_u64(xusd_amount), val_u64(min_xel_out)],
                    deposits={XUSD_ASSET: {"amount": xusd_amount}})


# ---------------------------------------------------------------------------
# Op wrappers — VaultSwap AMM
# ---------------------------------------------------------------------------
def swap_create_pool(p: Protocol, asset_a: str, asset_b: str,
                     is_psm: bool = False) -> str:
    return p.invoke("VaultSwap", "create_pool",
                    [val_hash(asset_a), val_hash(asset_b), val_bool(is_psm)])


def swap_add_liquidity(p: Protocol, asset_a: str, asset_b: str,
                       amount_a: int, amount_b: int) -> str:
    return p.invoke("VaultSwap", "add_liquidity",
                    [val_hash(asset_a), val_hash(asset_b),
                     val_u64(amount_a), val_u64(amount_b)],
                    deposits={asset_a: {"amount": amount_a},
                              asset_b: {"amount": amount_b}},
                    max_gas=HEAVY_GAS)


def swap_swap(p: Protocol, asset_in: str, asset_out: str, amount_in: int,
              min_amount_out: int = 1) -> str:
    return p.invoke("VaultSwap", "swap",
                    [val_hash(asset_in), val_hash(asset_out),
                     val_u64(amount_in), val_u64(min_amount_out)],
                    deposits={asset_in: {"amount": amount_in}})


def swap_psm_mint(p: Protocol, xel_amount: int, min_xusd_out: int) -> str:
    if min_xusd_out <= 0:
        raise ValueError("swap_psm_mint: min_xusd_out must be > 0")
    return p.invoke("VaultSwap", "psm_mint",
                    [val_u64(xel_amount), val_u64(min_xusd_out)],
                    deposits={XEL_ASSET: {"amount": xel_amount}})


def swap_psm_redeem(p: Protocol, xusd_amount: int, min_xel_out: int) -> str:
    if min_xel_out <= 0:
        raise ValueError("swap_psm_redeem: min_xel_out must be > 0")
    return p.invoke("VaultSwap", "psm_redeem",
                    [val_u64(xusd_amount), val_u64(min_xel_out)],
                    deposits={XUSD_ASSET: {"amount": xusd_amount}})


def swap_pools_count(p: Protocol) -> int:
    v = p.read_contract(p.resolve("VaultSwap"), "pc")
    return int(v) if v else 0


# ---------------------------------------------------------------------------
# Op wrappers — Governance
# ---------------------------------------------------------------------------
def gov_stake(p: Protocol, amount_vlt: int, lock_days: int = 0) -> str:
    return p.invoke("GovernanceVault", "stake",
                    [val_u64(amount_vlt), val_u64(lock_days)],
                    deposits={VLT_ASSET: {"amount": amount_vlt}})


def gov_unstake(p: Protocol, stake_id: int) -> str:
    return p.invoke("GovernanceVault", "unstake", [val_u64(stake_id)])


def gov_claim_rewards(p: Protocol) -> str:
    return p.invoke("GovernanceVault", "claim_rewards", [])


def gov_total_staked(p: Protocol) -> int:
    v = p.read_contract(p.resolve("GovernanceVault"), "ts")
    return int(v) if v else 0


def gov_stakes_count(p: Protocol) -> int:
    v = p.read_contract(p.resolve("GovernanceVault"), "sc")
    return int(v) if v else 0


# ---------------------------------------------------------------------------
# Op wrappers — PrivacyMixer
# ---------------------------------------------------------------------------
def mixer_deposit(p: Protocol, recipient: str, asset: str,
                  min_anonymity: int = 0) -> str:
    return p.invoke("PrivacyMixer", "deposit",
                    [val_addr(recipient), val_hash(asset), val_u64(min_anonymity)],
                    deposits={asset: {"amount": 1}}, max_gas=HEAVY_GAS)


def mixer_execute_mix(p: Protocol) -> str:
    return p.invoke("PrivacyMixer", "execute_mix", [], max_gas=HEAVY_GAS)


# ---------------------------------------------------------------------------
# Op wrappers — Insurance
# ---------------------------------------------------------------------------
def insurance_stake(p: Protocol, amount: int) -> str:
    return p.invoke("InsurancePool", "stake", [val_u64(amount)],
                    deposits={XUSD_ASSET: {"amount": amount}})


def insurance_unstake(p: Protocol, amount: int) -> str:
    return p.invoke("InsurancePool", "unstake", [val_u64(amount)])


def insurance_claim_premium(p: Protocol) -> str:
    return p.invoke("InsurancePool", "claim_premium", [])


# ---------------------------------------------------------------------------
# Op wrappers — Vesting / Delegation / Savings / Faucet / Chat
# ---------------------------------------------------------------------------
def vesting_claim(p: Protocol, name: str = "FounderVesting4y") -> str:
    return p.invoke(name, "claim_founder_tokens", [])


def delegation_register_profile(p: Protocol, name: str, description: str,
                                commission_bps: int) -> str:
    return p.invoke("MinerDelegation", "register_miner_profile",
                    [val_str(name), val_str(description), val_u64(commission_bps)])


def delegation_delegate(p: Protocol, miner_addr: str, amount_vlt: int,
                        auto_compound: bool = False) -> str:
    return p.invoke("MinerDelegation", "delegate",
                    [val_addr(miner_addr), val_u64(amount_vlt),
                     val_bool(auto_compound)],
                    deposits={VLT_ASSET: {"amount": amount_vlt}})


def delegation_undelegate(p: Protocol, amount_vlt: int) -> str:
    return p.invoke("MinerDelegation", "undelegate", [val_u64(amount_vlt)])


def savings_deposit(p: Protocol, amount_xusd: int) -> str:
    return p.invoke("SavingsRate", "deposit", [val_u64(amount_xusd)],
                    deposits={XUSD_ASSET: {"amount": amount_xusd}})


def savings_withdraw(p: Protocol, amount_xusd: int) -> str:
    return p.invoke("SavingsRate", "withdraw", [val_u64(amount_xusd)])


def faucet_distribute(p: Protocol, addresses: list) -> str:
    return p.invoke("FaucetContract", "distribute",
                    [val_addr(a) for a in addresses])


def chat_register_session(p: Protocol, chat_pubkey: str) -> str:
    return p.invoke("VaultChat", "register_session", [val_hash(chat_pubkey)])


def chat_anchor_messages(p: Protocol, merkle_root: str, message_count: int,
                         sender_count: int, msg_type: int = 0) -> str:
    return p.invoke("VaultChat", "anchor_messages",
                    [val_hash(merkle_root), val_u64(message_count),
                     val_u64(sender_count), val_u8(msg_type)])


# ---------------------------------------------------------------------------
# Bootstrap defaults
# ---------------------------------------------------------------------------
_default: Optional[Protocol] = None


def get_protocol() -> Protocol:
    global _default
    if _default is None:
        _default = Protocol()
    return _default


def set_protocol(p: Protocol) -> None:
    global _default
    _default = p


if __name__ == "__main__":
    p = get_protocol()
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        print("wallet address:", p.wallet.address())
        print("topoheight:", p.topoheight())
        for name in ["StakedOracle", "XelisVaultMiner", "VaultEngine", "PSM"]:
            print(f"{name}: {p.resolve(name)[:16]}...")
        print("VLT balance:", p.balance(VLT_ASSET))
        print("xUSD balance:", p.balance(XUSD_ASSET))
        print("XEL balance:", p.balance())