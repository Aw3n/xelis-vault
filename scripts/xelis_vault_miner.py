#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  XELIS Vault — All-in-One Miner & Price Oracle Daemon                      ║
║  Testnet Contract Addresses built-in — ready to run on testnet             ║
╚══════════════════════════════════════════════════════════════════════════════╝

What this daemon does:
  1. Connects to your XELIS daemon RPC
  2. Every N blocks: fetches XEL/USD price from CoinGecko + MEXC,
     proposes it to the PriceOracle (entry 2), then executes after timelock
  3. Optionally (if XelisVaultMiner is configured): registers as miner,
     submits heartbeats, monitors reputation

Quick start (testnet):
  python3 scripts/xelis_vault_miner.py --rpc http://127.0.0.1:18081

All contract hashes are pre-configured for testnet. Just point to your daemon
and the script will start updating the oracle price.

Requirements:
  - Python 3.10+
  - requests library (pip install requests)
  - XELIS daemon + wallet running (testnet or mainnet)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed. Install it:")
    print("  pip install requests")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# TESTNET CONTRACT ADDRESSES — deployed & verified 2026-07-27
# ═══════════════════════════════════════════════════════════════════════════════
PRICE_ORACLE_HASH = "083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6"
XUSD_HASH         = "909576c1fcd889ec443b63a4ce014bf756fcb8afd74c8c0ee902cac03384e3fc"
XUSD_ASSET_HASH   = "d8bd79a2aa33ad4a6fa0ac2b2440515124445ecce0468e070a8a09bb5ea9442f"
VAULT_ENGINE_HASH = "667b165c8c9cd6cc3464378799e38b172e0f2e912f4b5c6202d37a8da3939bcc"
PSM_HASH          = "9f2667447b9a850ba4b260c19cd2c3786bc4a3c5559a08332a9e13bfa47191ae"
VAULTSWAPV2_HASH  = "1b6699398e2acecbdd1fd372952696cfc37b99eb1dcac45a7216661f96c60422"
VLT_HASH          = "f1f40d151849f93dea6d78fddc8aa189a3b39f0606926bc1aa933d85e878ee86"
VLT_ASSET_HASH    = "6a52980188f964efdb2268e170b23b70a89173fb9425db0de294dbee326ae05d"

# PriceOracle entry IDs
ENTRY_PROPOSE_PRICE  = 2   # propose_price(price: u64)
ENTRY_EXECUTE_PRICE  = 3   # execute_price()
ENTRY_GET_PRICE      = 4   # get_price(asset: Hash) -> u64

# XelisVaultMiner entry IDs (optional, for miner mode)
ENTRY_REGISTER_MINER       = 0
ENTRY_SUBMIT_HEARTBEAT     = 6
ENTRY_IS_MINER_ACTIVE      = 9
ENTRY_GET_MINER_STAKE      = 10
ENTRY_GET_MINER_REPUTATION = 11

# VLT entry IDs (for balance check)
VLT_GET_ASSET_HASH = 11

# ── defaults ──────────────────────────────────────────────────────────────
VAULT_DIR          = Path.home() / ".xelis-vault"
CONFIG_PATH        = VAULT_DIR / "config" / "config.json"
LOG_DIR            = VAULT_DIR / "logs"
LOG_FILE           = LOG_DIR / "miner.log"

ORACLE_TIMELOCK_BLOCKS  = 3       # blocks between propose and execute
PRICE_UPDATE_INTERVAL   = 100     # blocks between price updates
MIN_STAKE_VLT_ATOMIC    = 10_000_000_000  # 100 VLT

HEARTBEAT_INTERVAL      = 100     # blocks between heartbeats
REPUTATION_GOOD_FLOOR   = 5_000

MIN_SOURCES             = 2
SANITY_MIN_PRICE        = 0.001
SANITY_MAX_PRICE        = 10_000.0

SERVICE_ORACLE = 1

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
def setup_logging(verbose: bool = False) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("miner")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(LOG_FILE, maxBytes=50 * 1024 * 1024, backupCount=3)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


log = logging.getLogger("miner")


def mask(s: Optional[str], keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}{'*' * (len(s) - keep * 2)}{s[-keep:]}"


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
class Config:
    def __init__(self) -> None:
        self.rpc_url: str = "http://127.0.0.1:18081"
        self.wallet_url: str = "http://127.0.0.1:18082"
        self.wallet_user: str = "wallet"
        self.wallet_pass: str = "testpass"
        self.miner_address: str = ""
        self.endpoint_url: str = ""
        self.services_mask: int = SERVICE_ORACLE
        self.contracts: dict[str, str] = {}
        self.price_update_interval: int = PRICE_UPDATE_INTERVAL
        self.oracle_timelock_blocks: int = ORACLE_TIMELOCK_BLOCKS
        self.heartbeat_interval: int = HEARTBEAT_INTERVAL
        self.mask_balances: bool = True
        self.enable_miner: bool = False
        self.enable_price_oracle: bool = True

    @classmethod
    def load(cls, path: Path, cli_args: argparse.Namespace) -> "Config":
        cfg = cls()
        if path.exists():
            try:
                raw = json.loads(path.read_text())
            except Exception as e:
                log.warning(f"Cannot parse {path}: {e} — using defaults")
                raw = {}
            cfg.rpc_url = raw.get("rpc_url", cfg.rpc_url)
            cfg.wallet_url = raw.get("wallet_url", cfg.wallet_url)
            cfg.wallet_user = raw.get("wallet_user", cfg.wallet_user)
            cfg.wallet_pass = raw.get("wallet_pass", cfg.wallet_pass)
            cfg.miner_address = raw.get("miner_address", cfg.miner_address)
            cfg.endpoint_url = raw.get("endpoint_url", cfg.endpoint_url)
            cfg.services_mask = int(raw.get("services_mask", cfg.services_mask))
            cfg.contracts = raw.get("contracts", {}) or {}
            cfg.price_update_interval = int(raw.get(
                "price_update_interval", cfg.price_update_interval))
            cfg.oracle_timelock_blocks = int(raw.get(
                "oracle_timelock_blocks", cfg.oracle_timelock_blocks))
            cfg.heartbeat_interval = int(raw.get(
                "heartbeat_interval", cfg.heartbeat_interval))
            cfg.mask_balances = bool(raw.get("mask_balances", True))
            cfg.enable_miner = bool(raw.get("enable_miner", False))
            cfg.enable_price_oracle = bool(raw.get("enable_price_oracle", True))
        if cli_args.rpc:
            cfg.rpc_url = cli_args.rpc
        if cli_args.wallet_url:
            cfg.wallet_url = cli_args.wallet_url
        if cli_args.endpoint:
            cfg.endpoint_url = cli_args.endpoint
        cfg.miner_address = os.environ.get("MINER_ADDRESS", cfg.miner_address)
        return cfg

    def oracle_contract(self) -> str:
        return self.contracts.get("PriceOracle", PRICE_ORACLE_HASH)

    def miner_contract(self) -> str:
        return self.contracts.get("XelisVaultMiner", "")

    def vlt_contract(self) -> str:
        return self.contracts.get("VLT", VLT_HASH)

    def vlt_asset(self) -> str:
        return self.contracts.get("vlt_asset", VLT_ASSET_HASH)


# ═══════════════════════════════════════════════════════════════════════════════
# XELIS RPC CLIENT
# ═══════════════════════════════════════════════════════════════════════════════
class XelisClient:
    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self._id = 0

    def _call(self, method: str, params: Optional[dict] = None) -> Any:
        self._id += 1
        payload = {
            "method": method,
            "params": params or {},
            "jsonrpc": "2.0",
            "id": self._id,
        }
        try:
            r = requests.post(self.rpc_url, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"RPC call failed ({method}): {e}")
        if "error" in data and data["error"]:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result", {})

    def get_topoheight(self) -> int:
        return int(self._call("get_topoheight"))

    def is_synced(self) -> bool:
        info = self._call("get_info")
        return bool(info.get("synced", False))

    def call_contract(self, entry_id: int, args: list[Any],
                      deposits: Optional[list[dict]] = None,
                      max_gas: int = 500_000) -> str:
        params: dict[str, Any] = {
            "tx_type": "CallContract",
            "contract": "...",   # must be set by caller
            "entry_id": entry_id,
            "args": [str(a) for a in args],
        }
        if deposits:
            params["deposits"] = deposits
        result = self._call("submit_transaction", params)
        tx_hash = result.get("hash") if isinstance(result, dict) else None
        if not tx_hash:
            raise RuntimeError(f"submit_transaction returned no hash: {result}")
        return tx_hash

    def read_contract(self, contract: str, entry_id: int,
                      args: Optional[list[Any]] = None) -> Any:
        return self._call("call_contract_read", {
            "contract": contract,
            "entry_id": entry_id,
            "args": [str(a) for a in (args or [])],
        })


class WalletClient:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base_url = base_url.rstrip("/") + "/json_rpc"
        self.auth = (user, password)
        self._id = 0

    def _call(self, method: str, params: Optional[dict] = None) -> Any:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._id,
        }
        r = requests.post(self.base_url, json=payload, auth=self.auth, timeout=60)
        r.raise_for_status()
        data = r.json()
        if "error" in data and data["error"]:
            raise RuntimeError(f"Wallet RPC error: {data['error']}")
        return data.get("result", {})

    def get_nonce(self) -> int:
        return int(self._call("get_nonce"))

    def build_transaction(self, params: dict) -> dict:
        return self._call("build_transaction", params)

    def invoke_contract(self, contract: str, entry_id: int, parameters: list[dict],
                        deposits: Optional[dict] = None,
                        max_gas: int = 500_000,
                        nonce: Optional[int] = None) -> str:
        invoke = {
            "contract": contract,
            "entry_id": entry_id,
            "parameters": parameters,
            "deposits": deposits or {},
            "max_gas": max_gas,
            "permission": "all",
        }
        tx_params: dict[str, Any] = {
            "invoke_contract": invoke,
            "fee": {"fixed": 10_000_000},
            "broadcast": True,
        }
        if nonce is not None:
            tx_params["nonce"] = nonce
        try:
            result = self.build_transaction(tx_params)
            tx_hash = result.get("hash") or ""
            return tx_hash
        except Exception as e:
            log.error(f"invoke_contract failed: {e}")
            return ""


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE FETCHING
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_coingecko() -> Optional[float]:
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "xelis", "vs_currencies": "usd"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return float(data["xelis"]["usd"])
    except Exception as e:
        log.debug(f"CoinGecko failed: {e}")
        return None


def fetch_mexc() -> Optional[float]:
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/ticker/price",
            params={"symbol": "XELUSDT"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return float(data["price"])
    except Exception as e:
        log.debug(f"MEXC failed: {e}")
        return None


def fetch_price() -> Optional[float]:
    prices: list[tuple[str, float]] = []
    cg = fetch_coingecko()
    if cg is not None:
        prices.append(("coingecko", cg))
        log.info(f"  CoinGecko: ${cg:.6f}")
    mx = fetch_mexc()
    if mx is not None:
        prices.append(("mexc", mx))
        log.info(f"  MEXC:      ${mx:.6f}")
    if len(prices) < MIN_SOURCES:
        log.warning(f"Price fetch: only {len(prices)} source(s) (need {MIN_SOURCES})")
        return None
    median = statistics.median(p for _, p in prices)
    if not (SANITY_MIN_PRICE < median < SANITY_MAX_PRICE):
        log.warning(f"Price out of sanity range: ${median:.6f}")
        return None
    sources_str = "+".join(s for s, _ in prices)
    log.info(f"  Median:    ${median:.6f} ({sources_str})")
    return median


def usd_to_atomic(price_usd: float, decimals: int = 8) -> int:
    return int(round(price_usd * 10 ** decimals))


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE ORACLE DAEMON
# ═══════════════════════════════════════════════════════════════════════════════
class PriceOracleDaemon:
    def __init__(self, cfg: Config, client: XelisClient,
                 wallet: WalletClient, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.client = client
        self.wallet = wallet
        self.dry_run = dry_run
        self.running = True
        self.last_price_topo: int = 0
        self.pending_proposal_topo: int = 0
        self._register_signals()

    def _register_signals(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except (ValueError, OSError):
                pass

    def _handle_signal(self, signum, frame) -> None:
        log.info(f"Signal {signum} — shutting down")
        self.running = False

    def get_current_price(self) -> Optional[int]:
        try:
            result = self.client.read_contract(
                self.cfg.oracle_contract(),
                ENTRY_GET_PRICE,
                ["0" * 64],
            )
            return int(result) if result else None
        except Exception:
            return None

    def propose_price(self, price_atomic: int, nonce: int) -> bool:
        if self.dry_run:
            log.info(f"[DRY-RUN] propose_price({price_atomic})")
            return True
        oracle = self.cfg.oracle_contract()
        params = [
            {"type": "primitive", "value": {"type": "u64", "value": str(price_atomic)}}
        ]
        tx = self.wallet.invoke_contract(
            oracle, ENTRY_PROPOSE_PRICE, params, nonce=nonce
        )
        if tx:
            log.info(f"propose_price({price_atomic}) → tx={tx}")
            return True
        log.error("propose_price failed")
        return False

    def execute_price(self, nonce: int) -> bool:
        if self.dry_run:
            log.info("[DRY-RUN] execute_price()")
            return True
        oracle = self.cfg.oracle_contract()
        tx = self.wallet.invoke_contract(
            oracle, ENTRY_EXECUTE_PRICE, [], nonce=nonce
        )
        if tx:
            log.info(f"execute_price() → tx={tx}")
            return True
        log.error("execute_price failed")
        return False

    def run_once(self, topo: int, nonce: int) -> int:
        blocks_since = topo - self.last_price_topo
        if self.last_price_topo == 0:
            self.last_price_topo = topo
            cur = self.get_current_price()
            log.info(f"Oracle price check ... current price: {cur or 'N/A'}")
            return nonce

        if blocks_since < self.cfg.price_update_interval:
            return nonce

        log.info(f"── Price update cycle (topo={topo}, "
                 f"last={self.last_price_topo}) ──")

        price_usd = fetch_price()
        if price_usd is None:
            log.warning("Skipping price update — no valid price")
            self.last_price_topo = topo
            return nonce

        price_atomic = usd_to_atomic(price_usd)
        cur = self.get_current_price()
        if cur is not None:
            change_pct = abs(price_atomic - cur) / max(cur, 1) * 100
            log.info(f"  Current on-chain: ${cur / 1e8:.6f}")
            log.info(f"  Proposed:         ${price_usd:.6f} "
                     f"(change={change_pct:.2f}%)")
            if change_pct < 1.0:
                log.info("  ─ Skipping: change <1%")
                self.last_price_topo = topo
                return nonce

        log.info("  Step 1/2: propose_price ...")
        if not self.propose_price(price_atomic, nonce):
            self.last_price_topo = topo
            return nonce + 1
        nonce += 1
        self.pending_proposal_topo = topo

        log.info(f"  Step 2/2: execute_price (after "
                 f"{self.cfg.oracle_timelock_blocks} blocks) ...")
        if topo - self.pending_proposal_topo >= self.cfg.oracle_timelock_blocks:
            if not self.execute_price(nonce):
                log.warning("  execute_price failed — will retry next cycle")
                return nonce
            nonce += 1
            self.last_price_topo = topo
            self.pending_proposal_topo = 0
            new_price = self.get_current_price()
            log.info(f"  ✅ Price updated: on-chain now "
                     f"${new_price / 1e8:.6f}" if new_price else
                     f"  ✅ Price executed")

        return nonce


# ═══════════════════════════════════════════════════════════════════════════════
# MINER DAEMON (optional)
# ═══════════════════════════════════════════════════════════════════════════════
class MinerDaemon:
    def __init__(self, cfg: Config, client: XelisClient,
                 wallet: WalletClient, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.client = client
        self.wallet = wallet
        self.dry_run = dry_run
        self.last_heartbeat_topo: int = 0

    def verify_vlt_balance(self) -> bool:
        mc = self.cfg.miner_contract()
        if not mc:
            log.error("XelisVaultMiner not configured — set contracts.XelisVaultMiner")
            return False
        addr = self.cfg.miner_address
        if not addr:
            log.error("miner_address not set")
            return False
        vlt_asset = self.cfg.vlt_asset()
        try:
            bal = self.client.read_contract(
                self.cfg.vlt_contract(), 5, [addr]
            ) if False else 0
        except Exception:
            pass
        return True

    def is_registered(self) -> bool:
        mc = self.cfg.miner_contract()
        if not mc:
            return False
        try:
            result = self.client.read_contract(
                mc, ENTRY_GET_MINER_STAKE, [self.cfg.miner_address]
            )
            return int(result) > 0 if result else False
        except Exception:
            return False

    def register(self, nonce: int) -> int:
        if not self.cfg.miner_address:
            log.error("miner_address not set")
            return nonce
        if self.dry_run:
            log.info(f"[DRY-RUN] register_miner("
                     f"endpoint={self.cfg.endpoint_url})")
            return nonce + 1
        mc = self.cfg.miner_contract()
        params = [
            {"type": "primitive", "value": {"type": "string",
             "value": self.cfg.endpoint_url}},
            {"type": "primitive", "value": {"type": "string",
             "value": "0x" + "0" * 64}},
            {"type": "primitive", "value": {"type": "u64",
             "value": str(self.cfg.services_mask)}},
        ]
        deposits = {self.cfg.vlt_asset(): {"amount": MIN_STAKE_VLT_ATOMIC}}
        tx = self.wallet.invoke_contract(
            mc, ENTRY_REGISTER_MINER, params,
            deposits=deposits, max_gas=1_000_000, nonce=nonce
        )
        if tx:
            log.info(f"register_miner → tx={tx}")
            nonce += 1
        return nonce

    def submit_heartbeat(self, nonce: int) -> int:
        mc = self.cfg.miner_contract()
        if not mc:
            return nonce
        if self.dry_run:
            log.info("[DRY-RUN] submit_heartbeat")
            return nonce + 1
        tx = self.wallet.invoke_contract(
            mc, ENTRY_SUBMIT_HEARTBEAT, [], nonce=nonce
        )
        if tx:
            log.info(f"heartbeat → tx={tx}")
            nonce += 1
        return nonce

    def get_reputation(self) -> int:
        mc = self.cfg.miner_contract()
        if not mc:
            return 0
        try:
            result = self.client.read_contract(
                mc, ENTRY_GET_MINER_REPUTATION, [self.cfg.miner_address]
            )
            return int(result) if result else 0
        except Exception:
            return 0

    def run_once(self, topo: int, nonce: int) -> int:
        if not self.cfg.enable_miner:
            return nonce
        mc = self.cfg.miner_contract()
        if not mc:
            return nonce

        if not self.is_registered():
            if self.cfg.miner_address and self.cfg.endpoint_url:
                nonce = self.register(nonce)
            return nonce

        blocks_since = topo - self.last_heartbeat_topo
        if blocks_since >= self.cfg.heartbeat_interval:
            nonce = self.submit_heartbeat(nonce)
            self.last_heartbeat_topo = topo

        rep = self.get_reputation()
        if rep > 0:
            tier = "Excellent" if rep >= 8000 else \
                   "Good" if rep >= 5000 else \
                   "Warning" if rep >= 2000 else \
                   "Critical" if rep >= 1000 else "Banned"
            if rep < REPUTATION_GOOD_FLOOR:
                log.warning(f"Reputation={rep} ({tier}) — below Good")
            else:
                log.debug(f"Reputation={rep} ({tier})")

        return nonce


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DAEMON
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="XELIS Vault — All-in-One Miner & Price Oracle Daemon"
    )
    parser.add_argument("--rpc", help="XELIS daemon RPC URL")
    parser.add_argument("--wallet-url", help="Wallet RPC URL "
                        "(default: http://127.0.0.1:18082)")
    parser.add_argument("--endpoint", help="Public endpoint URL (for miner mode)")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help=f"Config file (default: {CONFIG_PATH})")
    parser.add_argument("--enable-miner", action="store_true",
                        help="Enable XelisVaultMiner registration + heartbeat")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without submitting txs")
    parser.add_argument("--verbose", action="store_true",
                        help="DEBUG-level logging")
    args = parser.parse_args()

    global log
    log = setup_logging(verbose=args.verbose)

    cfg = Config.load(args.config, args)
    if args.enable_miner:
        cfg.enable_miner = True

    client = XelisClient(cfg.rpc_url)
    wallet = WalletClient(cfg.wallet_url, cfg.wallet_user, cfg.wallet_pass)

    price = PriceOracleDaemon(cfg, client, wallet, dry_run=args.dry_run)
    miner = MinerDaemon(cfg, client, wallet, dry_run=args.dry_run)

    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║     XELIS Vault v5 — All-in-One Daemon                 ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    log.info(f"  RPC:           {cfg.rpc_url}")
    log.info(f"  Wallet:        {cfg.wallet_url}")
    log.info(f"  PriceOracle:   {mask(cfg.oracle_contract())}")
    log.info(f"  Price updates: every {cfg.price_update_interval} blocks")
    if cfg.enable_miner:
        log.info(f"  Miner:         {mask(cfg.miner_address)}")
        log.info(f"  Endpoint:      {cfg.endpoint_url or '(none)'}")
        log.info(f"  Heartbeat:     every {cfg.heartbeat_interval} blocks")
    else:
        log.info("  Miner mode:    disabled (use --enable-miner)")
    log.info(f"  Dry run:       {args.dry_run}")
    log.info("")

    nonce = 0
    try:
        nonce = wallet.get_nonce()
        log.info(f"  Wallet nonce:  {nonce}")
    except Exception as e:
        log.warning(f"Could not init nonce: {e}")

    last_topo = 0
    while price.running:
        try:
            topo = client.get_topoheight()
            if topo == last_topo:
                time.sleep(5)
                continue
            last_topo = topo

            if topo % 50 == 0:
                log.debug(f"topo={topo}")

            if cfg.enable_price_oracle:
                nonce = price.run_once(topo, nonce)

            if cfg.enable_miner:
                nonce = miner.run_once(topo, nonce)

            time.sleep(5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Main loop: {e}")
            time.sleep(10)

    log.info("Daemon stopped — goodbye")


if __name__ == "__main__":
    main()
