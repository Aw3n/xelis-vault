#!/usr/bin/env python3
"""Static consistency checks for hashes, chunks, versions, and installers.

Exit 0 if everything matches the canonical deployment_state.json.
Does not require a running daemon.
"""
from __future__ import annotations

import ast
import json
import py_compile
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
DOCS = REPO / "docs"
errors: list[str] = []
warns: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warns.append(msg)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        err(f"cannot read {path.relative_to(REPO)}: {e}")
        return {}


def extract_str_dict(src: str, name: str) -> dict:
    """Pull a dict-of-strings assignment from a Python file via AST."""
    tree = ast.parse(src)
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == name:
                target, value = t.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                target, value = node.target.id, node.value
        if target is None or value is None:
            continue
        if not isinstance(value, ast.Dict):
            continue
        out = {}
        for k, v in zip(value.keys, value.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                if isinstance(k.value, str) and isinstance(v.value, str):
                    out[k.value] = v.value
        return out
    return {}


def extract_fallback_contracts(src: str) -> dict:
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_FALLBACK" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and k.value == "contracts" and isinstance(v, ast.Dict):
                out = {}
                for ck, cv in zip(v.keys, v.values):
                    if isinstance(ck, ast.Constant) and isinstance(cv, ast.Constant):
                        out[ck.value] = cv.value
                return out
    return {}


SKIP = ("_r5", "_v2", "_v4R3")


def canonical(state_contracts: dict) -> dict:
    return {
        k: v for k, v in state_contracts.items()
        if isinstance(v, str) and len(v) == 64
        and not any(k.endswith(s) for s in SKIP)
    }


def check_hashes() -> None:
    state = load_json(DOCS / "deployment_state.json")
    live = canonical(state.get("contracts") or {})
    if not live:
        err("deployment_state.json has no contracts")
        return
    assets = state.get("assets") or {}

    bundle = load_json(REPO / "network" / "testnet.json")
    bcontracts = bundle.get("contracts") or {}
    for name, h in live.items():
        if name in bcontracts and bcontracts[name] != h:
            err(f"network/testnet.json {name} stale: {bcontracts[name][:16]} != {h[:16]}")
        snake_map = {
            "VaultEngineV3": "vault_engine",
            "FaucetContract": "faucet",
            "PrivacyMixer": "privacy_mixer",
            "VaultChat": "vault_chat",
            "Governor": "governor",
            "GovernanceVault": "governance_vault",
            "SavingsRate": "savings_rate",
            "FlashLoan": "flash_loan",
            "PeerLoan": "peer_loan",
            "SyndicatePool": "syndicate_pool",
            "SealedBidAuction": "sealed_bid_auction",
            "AssetVault": "asset_vault",
            "TreasuryVault": "treasury_vault",
            "XelisVaultMiner": "miner",
        }
        sk = snake_map.get(name)
        if sk and sk in bcontracts and bcontracts[sk] != h:
            err(f"network/testnet.json {sk} stale: {bcontracts[sk][:16]} != {h[:16]}")
    if bundle.get("vlt_asset") and assets.get("VLT") and bundle["vlt_asset"] != assets["VLT"]:
        err("network/testnet.json vlt_asset mismatch")
    if bundle.get("xusd_asset") and assets.get("XUSD") and bundle["xusd_asset"] != assets["XUSD"]:
        err("network/testnet.json xusd_asset mismatch")

    proto_src = (SCRIPTS / "protocol.py").read_text()
    proto = extract_str_dict(proto_src, "CONTRACT_HASHES") or extract_str_dict(
        proto_src, "_CONTRACT_HASHES_FALLBACK")
    for name, h in live.items():
        if name in proto and proto[name] != h:
            err(f"protocol.CONTRACT_HASHES[{name}] stale")

    backend_src = (SCRIPTS / "cli_backend.py").read_text()
    fb = extract_fallback_contracts(backend_src)
    for name, h in live.items():
        if name in fb and fb[name] != h:
            err(f"cli_backend._FALLBACK[{name}] stale")

    idx_src = (SCRIPTS / "airdrop_offchain_indexer.py").read_text()
    idx = extract_str_dict(idx_src, "CONTRACT_HASHES")
    for name, h in live.items():
        if name in idx and idx[name] != h:
            err(f"airdrop_offchain_indexer.CONTRACT_HASHES[{name}] stale")


def check_chunks() -> None:
    cmap = load_json(DOCS / "entry_chunk_ids.json")
    if not cmap:
        return
    sys.path.insert(0, str(SCRIPTS))
    try:
        from protocol import entry_id, _ENTRY_ALIASES
        from cli_backend import CHUNKS
    except Exception as e:
        err(f"import protocol/cli_backend failed: {e}")
        return

    for contract, fns in CHUNKS.items():
        key = _ENTRY_ALIASES.get(contract, contract)
        table = cmap.get(key) or cmap.get(contract)
        if not table:
            warn(f"CHUNKS[{contract}] has no entry_chunk_ids.json table")
            continue
        by_name = {
            info["name"]: int(cid)
            for cid, info in table.items()
            if isinstance(info, dict) and "name" in info
        }
        for fn, cid in fns.items():
            if fn not in by_name:
                err(f"CHUNKS[{contract}].{fn}={cid} not in chunk map")
            elif by_name[fn] != cid:
                err(f"CHUNKS[{contract}].{fn}={cid} map says {by_name[fn]}")

    probes = [
        ("PSM", "mint"),
        ("VaultEngineV3", "deposit"),
        ("PrivacyMixer", "deposit"),
        ("VaultChat", "register_session"),
        ("FaucetContract", "distribute"),
        ("AirdropTracker", "record_manual_attribution"),
        ("StakedOracle", "submit_price"),
        ("XelisVaultMiner", "register_miner"),
    ]
    for c, fn in probes:
        try:
            n = entry_id(c, fn)
            if not isinstance(n, int):
                err(f"entry_id({c},{fn}) returned {n!r}")
        except Exception as e:
            err(f"entry_id({c}, {fn}): {e}")


def check_versions() -> None:
    ver = {}
    vfile = REPO / "VERSION"
    if vfile.exists():
        for line in vfile.read_text().splitlines():
            if "=" in line:
                k, val = line.split("=", 1)
                ver[k.strip()] = val.strip()
    proto = ver.get("PROTOCOL_VERSION", "")
    readme = (REPO / "README.md").read_text()
    if proto and f"v{proto}" not in readme and proto not in readme:
        warn(f"README.md does not mention PROTOCOL_VERSION {proto}")
    inst = (REPO / "install").read_text()
    if re.search(r'VERSION="7\.0"', inst):
        err('install still hardcodes VERSION="7.0"')
    ps1 = (REPO / "install.ps1").read_text()
    if re.search(r'\$VERSION = "7\.0"', ps1):
        err('install.ps1 still hardcodes VERSION = "7.0"')
    if "relayer_daemon.py" in inst:
        err("install launcher xvault-relayer still points at obsolete relayer_daemon.py")
    if "relayer_daemon.py" in ps1:
        err("install.ps1 xvault-relayer still points at obsolete relayer_daemon.py")
    for bat in (REPO / "bin").glob("*.bat"):
        txt = bat.read_text()
        if "C:\\Users\\Ael" in txt:
            err(f"{bat.name} hardcodes C:\\Users\\Ael path")


def check_syntax() -> None:
    skip = set()
    for py in list(SCRIPTS.glob("*.py")) + list((REPO / "deploy").glob("*.py")) + list((REPO / "tests").glob("*.py")):
        if py.name in skip:
            continue
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as e:
            err(f"syntax {py.relative_to(REPO)}: {e.msg}")


def check_entry_ids_header() -> None:
    p = DOCS / "ENTRY_IDS.md"
    if not p.exists():
        return
    head = p.read_text()[:800]
    if "NOT" not in head and "not for invoke" not in head.lower() and "compiled chunk" not in head.lower():
        warn("docs/ENTRY_IDS.md header does not warn that IDs are source-order, not invoke ids")


def main() -> int:
    check_hashes()
    check_chunks()
    check_versions()
    check_syntax()
    check_entry_ids_header()
    for w in warns:
        print(f"WARN  {w}")
    for e in errors:
        print(f"FAIL  {e}")
    print(f"{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
