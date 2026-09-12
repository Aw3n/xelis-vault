#!/usr/bin/env python3
"""Regenerate network/testnet.json from docs/deployment_state.json.

Keeps both CamelCase (protocol.py) and snake_case (CLI) keys so every
consumer resolves the same live hashes. Skips alias keys (*_r5, *_v2, …).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "docs" / "deployment_state.json"
OUT = REPO / "network" / "testnet.json"

# Canonical live names -> CLI snake_case aliases
SNAKE = {
    "ContractRegistry": "contract_registry",
    "ComplianceModule": "compliance_module",
    "VLTToken": "vlt_token",
    "xUSD": "xusd",
    "FaucetContract": "faucet",
    "XelisVaultMiner": "miner",
    "StakedOracle": "staked_oracle",
    "MinerPool": "miner_pool",
    "InterestRateModel": "interest_rate_model",
    "VaultEngineV3": "vault_engine",
    "SavingsRate": "savings_rate",
    "FlashLoan": "flash_loan",
    "FlashCallback": "flash_callback",
    "VaultSwapV2": "vault_swap",
    "PSM": "psm",
    "LendingMarket": "lending_market",
    "PeerLoan": "peer_loan",
    "SyndicatePool": "syndicate_pool",
    "SealedBidAuction": "sealed_bid_auction",
    "PrivacyMixer": "privacy_mixer",
    "AssetVault": "asset_vault",
    "TreasuryVault": "treasury_vault",
    "RevenueShare": "revenue_share",
    "Payroll": "payroll",
    "GovernanceVault": "governance_vault",
    "Timelock": "timelock",
    "GuardianMultisig": "guardian_multisig",
    "Governor": "governor",
    "OracleGovernance": "oracle_governance",
    "VaultChat": "vault_chat",
    "FounderVesting": "foundervesting",
    "FounderVesting4y": "founder_vesting_4y",
    "FounderVesting10y": "founder_vesting_10y",
    "FeeDistributor": "fee_distributor",
    "MinerDelegation": "miner_delegation",
    "AirdropTracker": "airdrop_tracker",
}

SKIP_SUFFIXES = ("_r5", "_v2", "_v4R3")


def canonical_contracts(raw: dict) -> dict:
    out = {}
    for name, h in raw.items():
        if not isinstance(h, str) or len(h) != 64:
            continue
        if any(name.endswith(s) for s in SKIP_SUFFIXES):
            continue
        out[name] = h
    return out


def build(state: dict) -> dict:
    contracts = canonical_contracts(state.get("contracts") or {})
    bundle_contracts = {}
    for camel, h in contracts.items():
        bundle_contracts[camel] = h
        snake = SNAKE.get(camel)
        if snake:
            bundle_contracts[snake] = h
    assets = state.get("assets") or {}
    return {
        "network": "testnet",
        "version": "v12R",
        "updated": date.today().isoformat(),
        "source": "docs/deployment_state.json",
        "contracts": bundle_contracts,
        "vlt_asset": assets.get("VLT", ""),
        "xusd_asset": assets.get("XUSD", ""),
        "oracle_feed_id": 0,
    }


def main() -> int:
    if not STATE.exists():
        print(f"missing {STATE}", file=sys.stderr)
        return 1
    state = json.loads(STATE.read_text())
    bundle = build(state)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, indent=2) + "\n")
    n = len({k: v for k, v in bundle["contracts"].items() if k[:1].isupper() or k[:1].islower() and k[0].isupper()})
    camel = sum(1 for k in bundle["contracts"] if k[:1].isupper() or k.startswith("xUSD"))
    print(f"wrote {OUT} ({camel} canonical hashes, {len(bundle['contracts'])} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
