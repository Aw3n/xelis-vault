#!/usr/bin/env python3
"""
Cutover v11 -> v12: upgrades every contract in the live ContractRegistry
so the protocol client resolves to the new v12 hashes.

Run AFTER deploy_v12.py has completed all phases (1-13).
Uses ContractRegistry.upgrade (entry 2) — register (entry 3) rejects existing names.
Idempotent: skips names already pointing at the target hash.

Usage: python3 scripts/cutover_registry.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from protocol import Protocol, val_str, val_hash  # noqa: E402

STATE_PATH = REPO / "docs" / "deployment_state.json"
V12_PATH = REPO / "docs" / "deployment_state_v12R_partial_maxsupply0.json"

# ContractRegistry entry IDs (from docs/entry_chunk_ids.json)
ENTRY_REGISTER = 3   # register(name, hash) — rejects existing names
ENTRY_UPGRADE = 2    # upgrade(name, new_hash) — updates existing registration


def main():
    v11 = json.loads(STATE_PATH.read_text())
    v12 = json.loads(V12_PATH.read_text())

    p = Protocol()
    reg = p.resolve("ContractRegistry")

    print(f"Registry contract: {reg}")
    print(f"{'Name':<24} {'v11 (old)':<16} {'v12 (new)':<16} {'Action'}")
    print("-" * 80)

    # Upgrade every name that exists in BOTH states and differs.
    for name in sorted(v12["contracts"]):
        h11 = v11["contracts"].get(name)
        h12 = v12["contracts"][name]
        if h11 == h12:
            continue
        cur = p.daemon.read_key(reg, f"cur_{name}")
        if cur == h12:
            print(f"{name:<24} {str(h11)[:14]}…  {str(h12)[:14]}…  SKIP (already v12)")
            continue
        try:
            tx = p.invoke("ContractRegistry", ENTRY_UPGRADE,
                          [val_str(name), val_hash(h12)])
            print(f"{name:<24} {str(h11)[:14]}…  {str(h12)[:14]}…  UPGRADED {tx[:12]}…")
        except Exception as e:
            print(f"{name:<24} {str(h11)[:14]}…  {str(h12)[:14]}…  FAILED: {e}")

    # Assets (VLT, XUSD) — registered under cur_asset_<name>
    for name in ["VLT", "XUSD"]:
        a11 = v11.get("assets", {}).get(name)
        a12 = v12.get("assets", {}).get(name)
        if a11 == a12:
            continue
        cur = p.daemon.read_key(reg, f"cur_asset_{name}")
        if cur == a12:
            print(f"asset {name:<20} SKIP (already v12)")
            continue
        try:
            tx = p.invoke("ContractRegistry", ENTRY_UPGRADE,
                          [val_str(name), val_hash(a12)])
            print(f"asset {name:<20} UPGRADED {tx[:12]}…")
        except Exception as e:
            print(f"asset {name:<20} FAILED: {e}")

    print("\nCutover complete.")


if __name__ == "__main__":
    main()