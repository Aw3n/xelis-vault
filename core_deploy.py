#!/usr/bin/env python3
"""Core v5 deployment via wallet build_transaction RPC."""

import json, logging, os, sys, time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("core_deploy")

WALLET_RPC = os.environ.get("WALLET_RPC", "http://127.0.0.1:18082/json_rpc")
WALLET_AUTH = ("wallet", "testpass")
DAEMON_RPC = os.environ.get("DAEMON_RPC", "http://127.0.0.1:18081/json_rpc")
CONTRACTS_DIR = str(Path(__file__).resolve().parent / "contracts")
ADMIN = "xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v"
XEL_ZERO = "0x" + "0" * 64

CORE_CONTRACTS = [
    ("ContractRegistry", "proxy",  "ContractRegistry"),
    ("VLTToken",         "token",  "VLTToken"),
    ("XelisVaultMiner",  "miner",  "XelisVaultMiner"),
    ("StakedOracle",     "oracle", "StakedOracle"),
    ("xUSD",             "usd",    "xUSD"),
    ("VaultEngine",      "vault",  "VaultEngineV3"),
    ("PSM",              "amm",    "PSM"),
    ("VaultSwap",        "amm",    "VaultSwapV2"),
]

class WalletClient:
    def __init__(self, rpc_url, auth):
        self.rpc_url = rpc_url
        self.auth = auth
        self._id = 0
    def _call(self, method, params=None):
        self._id += 1
        body = {"method": method, "jsonrpc": "2.0", "id": self._id}
        if params is not None:
            body["params"] = params
        r = requests.post(self.rpc_url, json=body, auth=self.auth, timeout=120)
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(f"RPC error: {d['error']}")
        return d.get("result")

    def build_tx(self, payload):
        return self._call("build_transaction", payload)

    def deploy(self, path, gas=5_000_000):
        p = Path(path)
        if not p.exists():
            p = p.with_suffix(".slx")
        if not p.exists():
            raise FileNotFoundError(path)
        code = p.read_bytes().hex()
        log.info(f"  deploying {p.name} ({len(code)//2} bytes, gas={gas})...")
        result = self.build_tx({
            "deploy_contract": {"module": code, "invoke": {"deposits": {}, "max_gas": gas}},
            "broadcast": True,
        })
        tx = result.get("tx_hash") if isinstance(result, dict) else result
        if not tx:
            raise RuntimeError(f"Deploy returned no tx_hash: {result}")
        log.info(f"  tx {tx[:16]}... waiting for confirm...")
        time.sleep(8)
        return tx

    def invoke(self, contract, entry_id, args=None, deposits=None, gas=10_000_000):
        payload = {
            "invoke_contract": {
                "contract": contract,
                "entry_id": entry_id,
                "args": [str(a) for a in (args or [])],
                "permission": "all",
            },
            "broadcast": True,
        }
        if deposits:
            payload["invoke_contract"]["deposits"] = deposits
        result = self.build_tx(payload)
        tx = result.get("tx_hash") if isinstance(result, dict) else result
        if not tx:
            raise RuntimeError(f"Invoke returned no tx_hash: {result}")
        log.info(f"  -> {tx[:16]}")
        time.sleep(4)
        return tx

    def invoke_named(self, contract, entry, args=None, deposits=None, gas=10_000_000):
        payload = {
            "invoke_contract": {
                "contract": contract,
                "entry": entry,
                "args": [str(a) for a in (args or [])],
                "permission": "all",
            },
            "broadcast": True,
        }
        if deposits:
            payload["invoke_contract"]["deposits"] = deposits
        result = self.build_tx(payload)
        tx = result.get("tx_hash") if isinstance(result, dict) else result
        if not tx:
            raise RuntimeError(f"Invoke returned no tx_hash: {result}")
        log.info(f"  -> {tx[:16]}")
        time.sleep(4)
        return tx

class DaemonClient:
    def __init__(self, rpc_url):
        self.rpc_url = rpc_url
        self._id = 0
    def _call(self, method, params=None):
        self._id += 1
        body = {"method": method, "jsonrpc": "2.0", "id": self._id}
        if params is not None:
            body["params"] = params
        r = requests.post(self.rpc_url, json=body, timeout=60)
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(f"Daemon error: {d['error']}")
        return d.get("result")
    def read_contract(self, contract, entry_id, args=None):
        return self._call("call_contract_read", {"contract": contract, "entry_id": entry_id, "args": [str(a) for a in (args or [])]})
    def get_tx(self, tx_hash):
        return self._call("get_transaction", {"hash": tx_hash})
    def get_topoheight(self):
        return int(self._call("get_topoheight"))

wallet = WalletClient(WALLET_RPC, WALLET_AUTH)
daemon = DaemonClient(DAEMON_RPC)

def get_contract_hash(tx_hash, retries=5):
    for i in range(retries):
        try:
            tx = daemon.get_tx(tx_hash)
            ch = tx.get("contract_hash")
            if ch:
                return ch
        except Exception:
            pass
        log.info(f"  waiting for contract_hash ({i+1}/{retries})...")
        time.sleep(4)
    return tx_hash

def deploy_all():
    log.info(f"Deploying {len(CORE_CONTRACTS)} core contracts...")
    deployed = {}
    for name, subdir, stem in CORE_CONTRACTS:
        path = Path(CONTRACTS_DIR) / subdir / f"{stem}.slx"
        log.info(f"\n--- {name} ---")
        try:
            tx = wallet.deploy(str(path))
            ch = get_contract_hash(tx)
            deployed[name] = ch
            log.info(f"  ✓ {name:<20} → {ch[:16]}...")
        except Exception as e:
            log.error(f"  ✗ {name} failed: {e}")
            raise
    return deployed

def create_assets(deployed):
    assets = {}
    log.info("\n--- Creating VLT asset ---")
    wallet.invoke(deployed["VLTToken"], 5, gas=5_000_000)
    time.sleep(6)
    vlt_a = daemon.read_contract(deployed["VLTToken"], 11)
    assets["VLT"] = vlt_a
    log.info(f"  ✓ VLT: {vlt_a[:16] if vlt_a else '?'}...")

    log.info("\n--- Creating xUSD asset ---")
    wallet.invoke(deployed["xUSD"], 0, gas=5_000_000)
    time.sleep(6)
    xusd_a = daemon.read_contract(deployed["xUSD"], 12)
    assets["xUSD"] = xusd_a
    log.info(f"  ✓ xUSD: {xusd_a[:16] if xusd_a else '?'}...")
    return assets

def wire(deployed, assets):
    log.info("\n=== Wiring ===")
    reg = deployed["ContractRegistry"]
    vlt = deployed["VLTToken"]
    vlt_a = assets.get("VLT")
    xusd = deployed["xUSD"]
    xusd_a = assets.get("xUSD")
    miner = deployed["XelisVaultMiner"]
    oracle = deployed["StakedOracle"]
    ve = deployed["VaultEngine"]
    psm = deployed["PSM"]
    vs = deployed["VaultSwap"]

    def c(contract, eid, args, desc=""):
        try:
            wallet.invoke(contract, eid, args)
            log.info(f"  ✓ {desc or f'entry {eid}'}")
        except Exception as e:
            log.warning(f"  ! {desc or f'entry {eid}'}: {e}")

    def cn(contract, entry, args, desc=""):
        try:
            wallet.invoke_named(contract, entry, args)
            log.info(f"  ✓ {desc or entry}")
        except Exception as e:
            log.warning(f"  ! {desc or entry}: {e}")

    # ContractRegistry self-register
    c(reg, 1, ["ContractRegistry", reg], "Registry.self-register")

    # VLTToken.set_registry (entry 6)
    c(vlt, 6, [reg], "VLT.set_registry")

    # XelisVaultMiner wiring
    c(miner, 25, [vlt], "Miner.set_vlt_contract")
    c(miner, 26, [vlt_a], "Miner.set_vlt_asset")
    c(miner, 27, [ADMIN], "Miner.set_treasury")
    c(miner, 28, [reg], "Miner.set_registry")
    c(miner, 29, [reg], "Miner.set_timelock")
    c(miner, 30, [ADMIN], "Miner.set_guardian")
    c(miner, 31, [ADMIN], "Miner.set_emergency")

    # StakedOracle wiring
    c(oracle, 21, [miner], "Oracle.set_miner_contract")
    c(oracle, 22, [reg], "Oracle.set_registry")
    c(oracle, 23, [reg], "Oracle.set_timelock")
    c(oracle, 24, [ADMIN], "Oracle.set_guardian")
    c(oracle, 25, [ADMIN], "Oracle.set_emergency")

    # Authorize miner as VLT minter (VLTToken entry 3)
    c(vlt, 3, [miner, True], "VLT.set_minter(miner)")

    # xUSD: authorize VaultEngine, PSM, VaultSwap as minters (entry 5) and burners (entry 6)
    for contract in [ve, psm, vs]:
        c(xusd, 5, [contract, True], f"xUSD.set_minter({contract[:12]}...)")
        c(xusd, 6, [contract, True], f"xUSD.set_burner({contract[:12]}...)")

    # VaultEngine wiring (uses named entries)
    cn(ve, "set_registry", [reg], "VE.set_registry")
    cn(ve, "set_xusd_contract", [xusd], "VE.set_xusd_contract")
    cn(ve, "set_xusd_asset", [xusd_a], "VE.set_xusd_asset")
    cn(ve, "set_oracle", [oracle], "VE.set_oracle")
    cn(ve, "set_treasury", [ADMIN], "VE.set_treasury")

    # PSM wiring
    cn(psm, "set_xusd_contract", [xusd], "PSM.set_xusd_contract")
    cn(psm, "set_xusd_asset", [xusd_a], "PSM.set_xusd_asset")
    cn(psm, "set_oracle", [oracle], "PSM.set_oracle")
    cn(psm, "set_treasury", [ADMIN], "PSM.set_treasury")
    cn(psm, "set_registry", [reg], "PSM.set_registry")

    # VaultSwap wiring
    cn(vs, "set_registry", [reg], "VS.set_registry")
    cn(vs, "set_xusd_asset", [xusd_a], "VS.set_xusd_asset")
    cn(vs, "set_xusd_contract", [xusd], "VS.set_xusd_contract")
    cn(vs, "set_oracle", [oracle], "VS.set_oracle")
    cn(vs, "set_treasury", [ADMIN], "VS.set_treasury")

    log.info("✓ Wiring complete")

def add_feed(deployed):
    log.info("\n--- Adding XEL/USD feed ---")
    wallet.invoke(deployed["StakedOracle"], 0, ["XEL/USD", XEL_ZERO, 8, 100000, 10000000000000])
    time.sleep(6)
    feed_id = daemon.read_contract(deployed["StakedOracle"], 10, ["XEL/USD"])
    log.info(f"  ✓ XEL/USD feed id = {feed_id}")

def verify(deployed, assets):
    log.info("\n=== Verification ===")
    for name, ch in deployed.items():
        try:
            info = daemon.read_contract(ch, 0)  # try any read
            log.info(f"  ✓ {name:<20} {ch[:16]}...")
        except:
            log.warning(f"  ? {name:<20} {ch[:16]}... (unreachable)")

def save_result(deployed, assets):
    out = Path.home() / ".xelis-vault" / "config" / "core_deployment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "contracts": deployed,
        "assets": assets,
        "timestamp": int(time.time()),
    }, indent=2))
    log.info(f"Saved to {out}")

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Core v5 Deployment")
    log.info(f"Wallet: {WALLET_RPC}")
    log.info(f"Daemon: {DAEMON_RPC}")
    log.info("=" * 60)

    topo = daemon.get_topoheight()
    log.info(f"Daemon topoheight: {topo}")

    deployed = deploy_all()
    assets = create_assets(deployed)
    wire(deployed, assets)
    add_feed(deployed)
    verify(deployed, assets)
    save_result(deployed, assets)

    log.info("=" * 60)
    log.info("✓ Core deployment complete!")
    log.info("=" * 60)
    print()
    print("Deployed contracts:")
    for name, ch in deployed.items():
        print(f"  {name:<20} {ch}")
    print("Assets:")
    for name, ah in assets.items():
        print(f"  {name:<20} {ah}")
