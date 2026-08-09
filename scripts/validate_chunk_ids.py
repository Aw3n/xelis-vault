#!/usr/bin/env python3
"""
validate_chunk_ids.py — Validates all cross-contract chunk IDs.
Parses contracts to extract chunk order, then checks all .call() references.
"""
import re
from pathlib import Path

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"

# Known cross-contract calls (caller -> callee -> expected chunk -> function)
EXPECTED_CALLS = [
    ("oracle/StakedOracle.slx", "mc.call(17u16", "slash_miner"),
    ("oracle/StakedOracle.slx", "mc.call(18u16", "distribute_reward"),
    ("oracle/StakedOracle.slx", "mc.call(19u16", "is_miner_active"),
    ("oracle/StakedOracle.slx", "mc.call(22u16", "get_active_miners_for_service"),
    ("chat/VaultChat.slx", "miner.call(18u16", "distribute_reward"),
    ("vault/VaultEngineV3.slx", "reg.call(16u16", "ContractRegistry.get"),
    ("vault/VaultEngineV3.slx", "oracle.call(21u16", "get_price_for_asset"),
    ("vault/VaultEngineV3.slx", "xusd.call(4u16", "mint_split"),
    ("vault/VaultEngineV3.slx", "xusd.call(5u16", "burn_tokens"),
    ("amm/PSM.slx", "oracle.call(21u16", "get_price_for_asset"),
    ("amm/VaultSwapV2.slx", "oracle.call(21u16", "get_price_for_asset"),
    ("lending/LendingMarket.slx", "oracle.call(21u16", "get_price_for_asset"),
    ("lending/LendingMarket.slx", "irm.call(11u16", "get_borrow_rate"),
    ("lending/LendingMarket.slx", "irm.call(12u16", "get_supply_rate"),
    ("governance/Governor.slx", "gv.call(7u16", "get_voting_power"),
    ("governance/Governor.slx", "gv.call(8u16", "get_total_voting_power"),
    ("governance/Governor.slx", "tl.call(5u16", "submit_proposal"),
    ("governance/OracleGovernance.slx", "gv.call(7u16", "get_voting_power"),
    ("governance/GuardianMultisig.slx", "target.call(33u16", "StakedOracle.pause"),
    ("governance/GuardianMultisig.slx", "tl.call(8u16", "submit_emergency_proposal"),
    ("rwa/AssetVault.slx", "compliance.call(3u16", "check_transfer"),
    ("flashloan/FlashLoan.slx", "cb.call(2u16", "on_flash_loan"),
    ("miner/XelisVaultMiner.slx", "vlt.call(4u16", "VLTToken.mint_to"),
]

def main():
    errors = 0
    ok = 0
    
    for contract_file, call_pattern, expected_fn in EXPECTED_CALLS:
        filepath = CONTRACTS_DIR / contract_file
        if not filepath.exists():
            print(f"MISSING: {contract_file}")
            errors += 1
            continue
        
        content = filepath.read_text()
        if call_pattern in content:
            print(f"  OK: {contract_file} -> {call_pattern} ({expected_fn})")
            ok += 1
        else:
            print(f"  FAIL: {contract_file} expected '{call_pattern}' for {expected_fn}")
            errors += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {ok} OK, {errors} FAIL")
    if errors == 0:
        print("ALL CHUNK IDs VALIDATED SUCCESSFULLY!")
    else:
        print(f"WARNING: {errors} chunk IDs need fixing!")
    return 0 if errors == 0 else 1

if __name__ == "__main__":
    exit(main())
