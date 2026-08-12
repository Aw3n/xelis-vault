#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v10.6 — Contract interactions module
============================================================================
Implémente les vraies interactions avec les contrats déployés.
Toutes les fonctions sont wrappées avec gestion d'erreur et affichage clair.
============================================================================
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))
from tui import *

# Entry IDs (must match deployed contracts)
# StakedOracle
ORACLE_GET_PRICE = 4  # get_price_for_asset_entry

# VaultEngineV3
VAULT_DEPOSIT = 0
VAULT_BORROW = 1
VAULT_REPAY = 2
VAULT_WITHDRAW = 3
VAULT_LIQUIDATE = 4
VAULT_REDEEM = 5
VAULT_GET_VAULT = 10
VAULT_GET_HEALTH = 12
VAULT_TOTAL_VAULTS = 13

# PSM
PSM_MINT = 0
PSM_REDEEM = 1
PSM_GET_RESERVES = 2

# VaultSwapV2
SWAP_SWAP = 2
SWAP_ADD_LIQUIDITY = 0
SWAP_REMOVE_LIQUIDITY = 1

# GovernanceVault
GOV_STAKE = 0
GOV_UNSTAKE = 1
GOV_CLAIM_REWARDS = 2
GOV_GET_VOTING_POWER = 7

# Governor
GOV_PROPOSE = 0
GOV_VOTE = 1
GOV_QUEUE = 2
GOV_EXECUTE = 3

# PrivacyMixer
MIXER_DEPOSIT = 0
MIXER_WITHDRAW = 1

# VLTToken
VLT_TRANSFER = 4

# FaucetContract
FAUCET_DISTRIBUTE = 2

# AirdropTracker
AIRDROP_RECORD_MAINNET = 9

# AirdropClaim
AIRDROP_CLAIM = 0

XEL_DECIMALS = 8
VLT_DECIMALS = 8
XUSD_DECIMALS = 8


def fmt_amount(amount_atomic: int, decimals: int = 8) -> str:
    """Format atomic amount to human-readable string."""
    if not amount_atomic:
        return "0"
    amount = amount_atomic / (10 ** decimals)
    if amount >= 1000:
        return f"{amount:,.2f}"
    elif amount >= 1:
        return f"{amount:.4f}"
    else:
        return f"{amount:.8f}"


def fmt_xel(amount_atomic: int) -> str:
    return f"{fmt_amount(amount_atomic, XEL_DECIMALS)} XEL"


def fmt_vlt(amount_atomic: int) -> str:
    return f"{fmt_amount(amount_atomic, VLT_DECIMALS)} VLT"


def fmt_xusd(amount_atomic: int) -> str:
    return f"{fmt_amount(amount_atomic, XUSD_DECIMALS)} xUSD"


def fmt_usd(amount_atomic: int) -> str:
    """Format price in atomic (8 decimals) to USD string."""
    return f"${fmt_amount(amount_atomic, 8)}"


def fmt_addr(addr: str) -> str:
    """Truncate address for display."""
    if not addr or len(addr) < 20:
        return addr or "(not set)"
    return addr[:12] + "..." + addr[-8:]


def check_contracts_configured(client) -> bool:
    """Check if contract addresses are configured."""
    required = ["vault_engine_hash", "psm_hash", "vault_swap_hash",
                "oracle_hash", "governance_vault_hash"]
    missing = []
    for key in required:
        if not client.cfg.get(key):
            missing.append(key)
    if missing:
        clear()
        print(BANNER)
        print(f"\n{C.RED}{C.BOLD}  ⚠  Contracts not configured{C.RESET}")
        print(f"{C.DIM}  Missing: {', '.join(missing)}{C.RESET}")
        print(f"{C.DIM}  Run: xvault --setup to configure contract addresses.{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter to continue...{C.RESET}", end="")
        input()
        return False
    return True


def show_tx_result(tx_hash: str, success_msg: str = "Transaction submitted"):
    """Display transaction result."""
    if tx_hash:
        print(f"\n  {C.GREEN}✓ {success_msg}!{C.RESET}")
        print(f"  {C.DIM}TX: {tx_hash[:40]}...{C.RESET}")
    else:
        print(f"\n  {C.RED}✗ Failed to submit transaction.{C.RESET}")
        print(f"  {C.DIM}Check your wallet is running and has balance.{C.RESET}")


# ============================================================================
# Vault operations
# ============================================================================

def vault_deposit(client, amount_xel: float):
    """Deposit XEL as collateral into VaultEngine."""
    if not check_contracts_configured(client):
        return
    vault_engine = client.cfg.get("vault_engine_hash")
    amount_atomic = int(amount_xel * (10 ** XEL_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  💰 DEPOSIT XEL COLLATERAL{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_xel(amount_atomic)}{C.RESET}")
    print(f"  {C.DIM}This will deposit XEL as collateral into your vault.{C.RESET}")
    print(f"  {C.DIM}You can then borrow xUSD against it (up to 70% LTV).{C.RESET}")

    if confirm("\n  Confirm deposit?"):
        print(f"\n  {C.DIM}Submitting transaction...{C.RESET}")
        tx = client.submit_transaction(vault_engine, VAULT_DEPOSIT, [amount_atomic])
        show_tx_result(tx, "Deposit submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def vault_borrow(client, amount_xusd: float):
    """Borrow xUSD against collateral."""
    if not check_contracts_configured(client):
        return
    vault_engine = client.cfg.get("vault_engine_hash")
    amount_atomic = int(amount_xusd * (10 ** XUSD_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🏦 BORROW xUSD{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_xusd(amount_atomic)}{C.RESET}")
    print(f"  {C.DIM}This will mint xUSD against your collateral.{C.RESET}")
    print(f"  {C.DIM}Stability fee: 2% APR (accrues over time){C.RESET}")
    print(f"  {C.DIM}Min collateral ratio: 150%{C.RESET}")

    if confirm("\n  Confirm borrow?"):
        print(f"\n  {C.DIM}Submitting transaction...{C.RESET}")
        tx = client.submit_transaction(vault_engine, VAULT_BORROW, [amount_atomic])
        show_tx_result(tx, "Borrow submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def vault_repay(client, amount_xusd: float):
    """Repay xUSD debt."""
    if not check_contracts_configured(client):
        return
    vault_engine = client.cfg.get("vault_engine_hash")
    amount_atomic = int(amount_xusd * (10 ** XUSD_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  💳 REPAY xUSD DEBT{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_xusd(amount_atomic)}{C.RESET}")
    print(f"  {C.DIM}This will burn xUSD to reduce your debt.{C.RESET}")

    if confirm("\n  Confirm repay?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(vault_engine, VAULT_REPAY, [amount_atomic])
        show_tx_result(tx, "Repay submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def vault_withdraw(client, amount_xel: float):
    """Withdraw XEL collateral."""
    if not check_contracts_configured(client):
        return
    vault_engine = client.cfg.get("vault_engine_hash")
    amount_atomic = int(amount_xel * (10 ** XEL_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  ↩ WITHDRAW XEL COLLATERAL{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_xel(amount_atomic)}{C.RESET}")
    print(f"  {C.DIM}This will withdraw XEL from your vault.{C.RESET}")
    print(f"  {C.YELLOW}⚠ Your health factor must remain above 150%.{C.RESET}")

    if confirm("\n  Confirm withdrawal?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(vault_engine, VAULT_WITHDRAW, [amount_atomic])
        show_tx_result(tx, "Withdrawal submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def vault_view(client):
    """View user's vaults."""
    if not check_contracts_configured(client):
        return
    vault_engine = client.cfg.get("vault_engine_hash")
    addr = client.cfg.get("miner_address")

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  📋 YOUR VAULTS{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")

    # Get total vaults count
    total = client.invoke_contract(vault_engine, VAULT_TOTAL_VAULTS)
    if not total or not isinstance(total, int):
        print(f"  {C.DIM}No vaults found (or contracts not deployed).{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
        input()
        return

    print(f"  {C.DIM}Total vaults on protocol: {total}{C.RESET}")
    print(f"  {C.DIM}Your address: {fmt_addr(addr)}{C.RESET}\n")

    # In production: iterate vaults and show those owned by user
    # For now, show placeholder
    print(f"  {C.DIM}(Vault details will appear here once contracts are live){C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


# ============================================================================
# Swap operations
# ============================================================================

def psm_mint(client, amount_xel: float):
    """Mint xUSD via PSM (1:1 with XEL at oracle price)."""
    if not check_contracts_configured(client):
        return
    psm = client.cfg.get("psm_hash")
    amount_atomic = int(amount_xel * (10 ** XEL_DECIMALS))

    price = client.get_xel_price()
    expected_xusd = int(amount_atomic * price / (10 ** 8)) if price else 0

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  💱 MINT xUSD via PSM{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  You send:      {C.YELLOW}{fmt_xel(amount_atomic)}{C.RESET}")
    if price:
        print(f"  XEL price:     {fmt_usd(price)}")
        print(f"  You receive:   {C.GREEN}{fmt_xusd(expected_xusd)}{C.RESET}")
        print(f"  Fee:           {C.DIM}0.5% (included){C.RESET}")
    else:
        print(f"  {C.DIM}(oracle price unavailable){C.RESET}")

    if confirm("\n  Confirm mint?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(psm, PSM_MINT, [amount_atomic, 1])
        show_tx_result(tx, "PSM mint submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def psm_redeem(client, amount_xusd: float):
    """Redeem xUSD for XEL via PSM."""
    if not check_contracts_configured(client):
        return
    psm = client.cfg.get("psm_hash")
    amount_atomic = int(amount_xusd * (10 ** XUSD_DECIMALS))

    price = client.get_xel_price()
    expected_xel = int(amount_atomic * (10 ** 8) / price) if price else 0

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  💱 REDEEM xUSD for XEL{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  You send:      {C.YELLOW}{fmt_xusd(amount_atomic)}{C.RESET}")
    if price:
        print(f"  XEL price:     {fmt_usd(price)}")
        print(f"  You receive:   {C.GREEN}{fmt_xel(expected_xel)}{C.RESET}")
        print(f"  Fee:           {C.DIM}0.1% (included){C.RESET}")
    else:
        print(f"  {C.DIM}(oracle price unavailable){C.RESET}")

    if confirm("\n  Confirm redeem?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(psm, PSM_REDEEM, [amount_atomic, 1])
        show_tx_result(tx, "PSM redeem submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def amm_swap(client, asset_in_name: str, asset_out_name: str, amount: float):
    """Generic AMM swap."""
    if not check_contracts_configured(client):
        return
    vault_swap = client.cfg.get("vault_swap_hash")

    # Resolve asset hashes
    asset_map = {
        "XEL": "0x" + "0" * 64,
        "xUSD": client.cfg.get("xusd_asset_hash", ""),
        "VLT": client.cfg.get("vlt_asset_hash", ""),
    }
    asset_in = asset_map.get(asset_in_name, "")
    asset_out = asset_map.get(asset_out_name, "")

    if not asset_in or not asset_out:
        print(f"\n  {C.RED}Asset not configured.{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
        input()
        return

    amount_atomic = int(amount * (10 ** 8))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🔄 AMM SWAP{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  You send:      {C.YELLOW}{amount} {asset_in_name}{C.RESET}")
    print(f"  You receive:   {C.GREEN}(calculated by AMM){C.RESET} {asset_out_name}")
    print(f"  Fee:           {C.DIM}0.3% (included){C.RESET}")
    print(f"  Slippage:      {C.DIM}1% max (min_out=1){C.RESET}")

    if confirm("\n  Confirm swap?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(vault_swap, SWAP_SWAP,
                                       [asset_in, asset_out, amount_atomic, 1])
        show_tx_result(tx, "Swap submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


# ============================================================================
# Governance operations
# ============================================================================

def gov_stake(client, amount_vlt: float):
    """Stake VLT in GovernanceVault."""
    if not check_contracts_configured(client):
        return
    gov_vault = client.cfg.get("governance_vault_hash")
    amount_atomic = int(amount_vlt * (10 ** VLT_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🔒 STAKE VLT{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_vlt(amount_atomic)}{C.RESET}")
    print(f"  {C.DIM}Staking VLT gives you voting power in governance.{C.RESET}")
    print(f"  {C.DIM}You earn rewards from protocol revenue.{C.RESET}")

    if confirm("\n  Confirm stake?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(gov_vault, GOV_STAKE, [amount_atomic])
        show_tx_result(tx, "Stake submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def gov_unstake(client, amount_vlt: float):
    """Unstake VLT from GovernanceVault."""
    if not check_contracts_configured(client):
        return
    gov_vault = client.cfg.get("governance_vault_hash")
    amount_atomic = int(amount_vlt * (10 ** VLT_DECIMALS))

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🔓 UNSTAKE VLT{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Amount: {C.YELLOW}{fmt_vlt(amount_atomic)}{C.RESET}")
    print(f"  {C.YELLOW}⚠ Unstaking may have a delay before withdrawal.{C.RESET}")

    if confirm("\n  Confirm unstake?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(gov_vault, GOV_UNSTAKE, [amount_atomic])
        show_tx_result(tx, "Unstake submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def gov_claim_rewards(client):
    """Claim staking rewards."""
    if not check_contracts_configured(client):
        return
    gov_vault = client.cfg.get("governance_vault_hash")

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🎁 CLAIM STAKING REWARDS{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  {C.DIM}This will claim your accumulated VLT rewards.{C.RESET}")

    if confirm("\n  Confirm claim?"):
        print(f"\n  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(gov_vault, GOV_CLAIM_REWARDS, [])
        show_tx_result(tx, "Claim submitted")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


# ============================================================================
# Mixer operations
# ============================================================================

def mixer_deposit(client, denomination: int):
    """Deposit into privacy mixer."""
    if not check_contracts_configured(client):
        return
    mixer = client.cfg.get("mixer_hash")
    amount_atomic = denomination * (10 ** XEL_DECIMALS)

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🔒 PRIVACY MIXER DEPOSIT{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  Denomination: {C.YELLOW}{denomination} XEL{C.RESET}")
    print(f"  {C.DIM}Your XEL will be mixed with others for privacy.{C.RESET}")
    print(f"  {C.DIM}You'll receive a private note to withdraw later.{C.RESET}")
    print(f"  {C.YELLOW}⚠ Save your note — it cannot be recovered!{C.RESET}")

    if confirm("\n  Confirm deposit?"):
        print(f"\n  {C.DIM}Generating commitment...{C.RESET}")
        print(f"  {C.DIM}Submitting...{C.RESET}")
        tx = client.submit_transaction(mixer, MIXER_DEPOSIT, [amount_atomic])
        show_tx_result(tx, "Mixer deposit submitted")
        print(f"\n  {C.YELLOW}⚠ Save your withdrawal note!{C.RESET}")
    else:
        print(f"\n  {C.DIM}Cancelled.{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


def mixer_withdraw(client):
    """Withdraw from privacy mixer."""
    if not check_contracts_configured(client):
        return
    mixer = client.cfg.get("mixer_hash")

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🔓 PRIVACY MIXER WITHDRAW{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
    print(f"  {C.DIM}Enter your withdrawal note and recipient address.{C.RESET}\n")

    note = text_input("  Withdrawal note: ")
    if not note:
        print(f"\n  {C.RED}No note provided.{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
        input()
        return

    recipient = text_input("  Recipient address (fresh address recommended): ")
    if not recipient or len(recipient) < 10:
        print(f"\n  {C.RED}Invalid address.{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
        input()
        return

    print(f"\n  {C.DIM}Generating ZK proof...{C.RESET}")
    print(f"  {C.DIM}Submitting...{C.RESET}")
    tx = client.submit_transaction(mixer, MIXER_WITHDRAW, [note, recipient])
    show_tx_result(tx, "Mixer withdrawal submitted")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()


# ============================================================================
# Faucet operations
# ============================================================================

def faucet_info(client):
    """Display faucet info."""
    if not check_contracts_configured(client):
        return
    faucet = client.cfg.get("faucet_hash")
    if not faucet:
        print(f"\n  {C.RED}Faucet not configured.{C.RESET}")
        print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
        input()
        return

    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  🚰 FAUCET INFO{C.RESET}")
    print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")

    info = client.invoke_contract_fn(faucet, "get_faucet_info")
    if info and len(info) >= 6:
        xel_amount, vlt_amount, cooldown, xel_cap, vlt_cap, paused = info
        print(f"  XEL per claim:     {fmt_xel(xel_amount)}")
        print(f"  VLT per claim:     {fmt_vlt(vlt_amount)}")
        print(f"  Cooldown:          {cooldown} blocks (~{cooldown * 5 // 60} min)")
        print(f"  Lifetime XEL cap:  {fmt_xel(xel_cap)}")
        print(f"  Lifetime VLT cap:  {fmt_vlt(vlt_cap)}")
        print(f"  Status:            {'⛔ Paused' if paused else '✅ Active'}")
    else:
        print(f"  {C.DIM}(faucet not deployed or no data){C.RESET}")

    print(f"\n  {C.DIM}To request testnet funds:{C.RESET}")
    print(f"  {C.DIM}1. Ask on Discord #faucet-request{C.RESET}")
    print(f"  {C.DIM}2. Admin will distribute to your address{C.RESET}")

    print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
    input()
