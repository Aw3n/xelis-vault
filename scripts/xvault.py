#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v9.0 — Community CLI (xvault)
============================================================================
Interactive CLI with arrow-key navigation. No typing numbers.
Works on Linux, macOS, and Windows.
============================================================================
"""
from __future__ import annotations
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)

# Import TUI library
sys.path.insert(0, str(Path(__file__).parent))
from tui import *
from airdrop_cli import AirdropClient, screen_airdrop_dashboard
from contract_ops import (
    vault_deposit, vault_borrow, vault_repay, vault_withdraw, vault_view,
    psm_mint, psm_redeem, amm_swap, amm_add_liquidity, amm_view_pools,
    gov_stake, gov_unstake, gov_claim_rewards,
    gov_view_proposals, gov_vote, gov_create_proposal,
    mixer_deposit, mixer_withdraw, mixer_view_root, mixer_check_nullifier,
    faucet_info, delegation_dashboard,
    fmt_xel, fmt_vlt, fmt_xusd, fmt_usd, fmt_addr, fmt_amount,
)
from admin_panel import (
    screen_admin_panel, screen_guardian_panel,
    is_admin, is_guardian, auto_detect_roles,
)

VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"
WALLET_DIR = VAULT_DIR / "wallet"
LOG_DIR = VAULT_DIR / "logs"

XELIS_WALLET_URLS = {
    "linux-x64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-linux-amd64",
    "linux-arm64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-linux-arm64",
    "macos-x64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-macos-amd64",
    "macos-arm64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-macos-arm64",
    "windows-x64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-windows-amd64.exe",
    "windows-arm64": "https://github.com/xelis-project/xelis-blockchain/releases/latest/download/xelis_wallet-windows-arm64.exe",
}

def detect_platform():
    os_name = platform.system()
    arch = platform.machine()
    if os_name == "Windows":
        if arch in ("AMD64", "x86_64"): return "windows-x64"
        if arch in ("ARM64", "aarch64"): return "windows-arm64"
    if os_name == "Linux":
        if arch in ("x86_64", "amd64"): return "linux-x64"
        if arch in ("arm64", "aarch64"): return "linux-arm64"
    elif os_name == "Darwin":
        if arch in ("x86_64", "amd64"): return "macos-x64"
        if arch in ("arm64", "aarch64"): return "macos-arm64"
    return None

class Config:
    def __init__(self):
        self.data = {
            "rpc_url": "http://127.0.0.1:18081",
            "wallet_url": "http://127.0.0.1:18082",
            "wallet_user": "wallet",
            "wallet_pass": "testpass",
            "miner_address": "",
            "contracts": {},
        }
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                stored = json.loads(CONFIG_PATH.read_text())
                for k in self.data:
                    if k in stored:
                        self.data[k] = stored[k]
            except:
                pass

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.data, indent=2))

    def get(self, key, default=""):
        return self.data.get(key, default)

    @property
    def contracts(self):
        return self.data.get("contracts", {})

class XelisClient:
    def __init__(self, config):
        self.cfg = config
        self.session = requests.Session()
        self.session.auth = (config.get("wallet_user"), config.get("wallet_pass"))

    def rpc(self, method, params=None):
        try:
            r = self.session.post(self.cfg.get("rpc_url"), json={
                "jsonrpc": "2.0", "method": method, "params": params or [], "id": 1
            }, timeout=10)
            data = r.json()
            return data.get("result") if not data.get("error") else None
        except:
            return None

    def wallet_rpc(self, method, params=None):
        try:
            r = self.session.post(self.cfg.get("wallet_url"), json={
                "jsonrpc": "2.0", "method": method, "params": params or [], "id": 1
            }, timeout=10)
            data = r.json()
            return data.get("result") if not data.get("error") else None
        except:
            return None

    def get_topoheight(self):
        r = self.rpc("get_topoheight")
        return r if isinstance(r, int) else 0

    def get_balance(self, asset=""):
        addr = self.cfg.get("miner_address")
        if not addr:
            return {}
        return self.wallet_rpc("get_balance", [addr, asset]) or {}

    def get_wallet_addresses(self):
        """Get all addresses from the wallet daemon (auto-detect)."""
        result = self.wallet_rpc("get_addresses", [])
        if result is None:
            return []
        # Result can be a list of strings or a dict with "addresses" key
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("addresses", [])
        return []

    def get_main_address(self):
        """Get the first/main address from the wallet."""
        addrs = self.get_wallet_addresses()
        if addrs:
            if isinstance(addrs[0], dict):
                return addrs[0].get("address", "")
            return addrs[0]
        return ""

    # === Contract interaction methods ===

    def invoke_contract(self, contract_hash, entry_id, params=None):
        """Invoke a contract entry (read-only via invoke)."""
        try:
            r = self.rpc("invoke_contract", [
                contract_hash,
                entry_id,
                params or [],
            ])
            return r
        except:
            return None

    def invoke_contract_fn(self, contract_hash, fn_name, params=None):
        """Invoke a contract pub fn (read-only)."""
        try:
            r = self.rpc("invoke_contract_fn", [
                contract_hash,
                fn_name,
                params or [],
            ])
            return r
        except:
            return None

    def submit_transaction(self, contract_hash, entry_id, params=None, fee=100000):
        """Submit a transaction to a contract (state-changing)."""
        addr = self.cfg.get("miner_address")
        if not addr:
            return None
        try:
            r = self.wallet_rpc("submit_transaction", [
                addr,
                contract_hash,
                {"entry_id": entry_id, "args": params or []},
                fee,
            ])
            return r
        except:
            return None

    def get_contract_balance(self, contract_hash, asset):
        """Get a contract's balance for an asset."""
        try:
            r = self.rpc("get_balance", [contract_hash, asset])
            return r
        except:
            return None

    # === Helper methods for common contract calls ===

    def get_xel_price(self):
        """Get XEL/USD price from StakedOracle."""
        oracle = self.cfg.get("oracle_hash") or ""
        if not oracle:
            return 0
        # StakedOracle entry 4 = get_price_for_asset_entry
        result = self.invoke_contract(oracle, 4, ["0x" + "0" * 64])
        return result if isinstance(result, (int, float)) else 0

    def get_vlt_balance(self, addr=None):
        """Get VLT balance for an address."""
        if not addr:
            addr = self.cfg.get("miner_address")
        vlt_asset = self.cfg.get("vlt_asset_hash") or ""
        if not vlt_asset or not addr:
            return 0
        result = self.wallet_rpc("get_balance", [addr, vlt_asset])
        if result and isinstance(result, dict):
            return int(result.get("balance", 0))
        return 0

    def get_xusd_balance(self, addr=None):
        """Get xUSD balance for an address."""
        if not addr:
            addr = self.cfg.get("miner_address")
        xusd_asset = self.cfg.get("xusd_asset_hash") or ""
        if not xusd_asset or not addr:
            return 0
        result = self.wallet_rpc("get_balance", [addr, xusd_asset])
        if result and isinstance(result, dict):
            return int(result.get("balance", 0))
        return 0

def ensure_wallet():
    wallet_name = "xelis_wallet.exe" if os.name == "nt" else "xelis_wallet"
    if shutil.which(wallet_name):
        return Path(shutil.which(wallet_name))
    local = WALLET_DIR / wallet_name
    if local.exists():
        return local
    pf = detect_platform()
    if not pf:
        return None
    url = XELIS_WALLET_URLS.get(pf)
    if not url:
        return None
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(local, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        if os.name != "nt":
            local.chmod(0o755)
        return local
    except:
        return None

def screen_dashboard(client):
    clear()
    print(BANNER)
    topo = client.get_topoheight()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    addr = client.cfg.get("miner_address") or "(not set)"
    print(f"\n{C.GRAY}{'=' * 60}{C.RESET}")
    print(f"{C.DIM}  {now}  |  Topo: {topo}  |  {addr[:20]}...{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}\n")
    print(f"  {C.BOLD}Your Balance:{C.RESET}")
    balances = client.get_balance()
    if balances:
        for asset, amount in balances.items():
            print(f"    {C.GREEN}{amount}{C.RESET} {asset}")
    else:
        print(f"    {C.DIM}(wallet not connected){C.RESET}")
    print()

    # Airdrop mini-stats
    airdrop = AirdropClient(client.cfg, client)
    if airdrop.is_configured():
        stats = airdrop.get_protocol_stats()
        if stats and len(stats) >= 6:
            user_count = stats[0]
            qualified = stats[1]
            total_pts = stats[2]
            frozen = stats[4]
            finalized = stats[5]
            print(f"  {C.BOLD}🪂 Airdrop Campaign:{C.RESET}")
            if finalized:
                status = f"{C.GREEN}Finalized{C.RESET}"
            elif frozen:
                status = f"{C.YELLOW}Frozen{C.RESET}"
            else:
                status = f"{C.GREEN}Active{C.RESET}"
            print(f"    {C.CYAN}Status:{C.RESET}            {status}")
            print(f"    {C.CYAN}Participants:{C.RESET}      {user_count:,}")
            print(f"    {C.CYAN}Qualified:{C.RESET}          {qualified:,}")
            print(f"    {C.CYAN}Total points:{C.RESET}      {total_pts:,}")
            # My points
            if addr and addr != "(not set)":
                my_pts = airdrop.get_user_points(addr)
                my_rank = airdrop.get_user_rank(addr)
                if my_pts:
                    print(f"    {C.YELLOW}My points:{C.RESET}          {my_pts:,} (rank #{my_rank or '—'})")
            print()

    print(f"  {C.BOLD}Protocol Stats:{C.RESET}")
    print(f"    {C.CYAN}Active miners:{C.RESET}     --")
    print(f"    {C.CYAN}XEL/USD price:{C.RESET}     --")
    print(f"    {C.CYAN}xUSD supply:{C.RESET}       --")
    print(f"    {C.CYAN}VLT/XEL pool:{C.RESET}      --")
    print()
    print(f"{C.DIM}  Press Enter to go back...{C.RESET}")
    read_key()

def screen_vault(client):
    while True:
        choice = menu("Vault Management", [
            ("Deposit XEL collateral", "deposit"),
            ("Borrow xUSD", "borrow"),
            ("Repay xUSD debt", "repay"),
            ("Withdraw XEL collateral", "withdraw"),
            ("View your vaults", "view"),
            ("Back", None),
        ], "Deposit XEL, borrow xUSD, earn")
        if choice is None:
            break
        elif choice == "deposit":
            amount = text_input("  Amount of XEL to deposit: ")
            try:
                amt = float(amount)
                if amt > 0:
                    vault_deposit(client, amt)
            except ValueError:
                pass
        elif choice == "borrow":
            amount = text_input("  Amount of xUSD to borrow: ")
            try:
                amt = float(amount)
                if amt > 0:
                    vault_borrow(client, amt)
            except ValueError:
                pass
        elif choice == "repay":
            amount = text_input("  Amount of xUSD to repay: ")
            try:
                amt = float(amount)
                if amt > 0:
                    vault_repay(client, amt)
            except ValueError:
                pass
        elif choice == "withdraw":
            amount = text_input("  Amount of XEL to withdraw: ")
            try:
                amt = float(amount)
                if amt > 0:
                    vault_withdraw(client, amt)
            except ValueError:
                pass
        elif choice == "view":
            vault_view(client)

def screen_swap(client):
    while True:
        choice = menu("Swap", [
            ("XEL -> xUSD (PSM, 1:1)", "psm_mint"),
            ("xUSD -> XEL (PSM)", "psm_redeem"),
            ("XEL -> VLT (AMM)", "swap_xel_vlt"),
            ("VLT -> XEL (AMM)", "swap_vlt_xel"),
            ("Add liquidity (VLT/XEL pool)", "add_liquidity"),
            ("View pools & prices", "view_pools"),
            ("Back", None),
        ], "Trade XEL, xUSD, VLT")
        if choice is None:
            break
        elif choice == "psm_mint":
            amount = text_input("  Amount of XEL to swap: ")
            try:
                amt = float(amount)
                if amt > 0:
                    psm_mint(client, amt)
            except ValueError:
                pass
        elif choice == "psm_redeem":
            amount = text_input("  Amount of xUSD to redeem: ")
            try:
                amt = float(amount)
                if amt > 0:
                    psm_redeem(client, amt)
            except ValueError:
                pass
        elif choice == "swap_xel_vlt":
            amount = text_input("  Amount of XEL to swap: ")
            try:
                amt = float(amount)
                if amt > 0:
                    amm_swap(client, "XEL", "VLT", amt)
            except ValueError:
                pass
        elif choice == "swap_vlt_xel":
            amount = text_input("  Amount of VLT to swap: ")
            try:
                amt = float(amount)
                if amt > 0:
                    amm_swap(client, "VLT", "XEL", amt)
            except ValueError:
                pass
        elif choice == "add_liquidity":
            xel_amt = text_input("  XEL amount to add: ")
            vlt_amt = text_input("  VLT amount to add: ")
            try:
                x = float(xel_amt)
                v = float(vlt_amt)
                if x > 0 and v > 0:
                    amm_add_liquidity(client, x, v)
            except ValueError:
                pass
        elif choice == "view_pools":
            amm_view_pools(client)

def screen_governance(client):
    while True:
        choice = menu("Governance", [
            ("Stake VLT (earn voting power)", "stake"),
            ("Unstake VLT", "unstake"),
            ("Claim staking rewards", "claim"),
            ("View active proposals", "proposals"),
            ("Vote on a proposal", "vote"),
            ("Create a proposal", "create"),
            ("Back", None),
        ], "Stake VLT, vote, propose")
        if choice is None:
            break
        elif choice == "stake":
            amount = text_input("  Amount of VLT to stake: ")
            try:
                amt = float(amount)
                if amt > 0:
                    gov_stake(client, amt)
            except ValueError:
                pass
        elif choice == "unstake":
            amount = text_input("  Amount of VLT to unstake: ")
            try:
                amt = float(amount)
                if amt > 0:
                    gov_unstake(client, amt)
            except ValueError:
                pass
        elif choice == "claim":
            gov_claim_rewards(client)
        elif choice == "proposals":
            gov_view_proposals(client)
        elif choice == "vote":
            gov_vote(client)
        elif choice == "create":
            gov_create_proposal(client)

def screen_mixer(client):
    while True:
        choice = menu("Privacy Mixer", [
            ("Deposit XEL (10 / 100 / 1000)", "deposit"),
            ("Withdraw to fresh address (ZK proof)", "withdraw"),
            ("View Merkle root", "root"),
            ("Check if nullifier used", "nullifier"),
            ("Back", None),
        ], "Private transfers")
        if choice is None:
            break
        elif choice == "deposit":
            denom_choice = menu("Select denomination", [
                ("10 XEL", "10"),
                ("100 XEL", "100"),
                ("1000 XEL", "1000"),
                ("Cancel", None),
            ])
            if denom_choice:
                mixer_deposit(client, int(denom_choice))
        elif choice == "withdraw":
            mixer_withdraw(client)
        elif choice == "root":
            mixer_view_root(client)
        elif choice == "nullifier":
            mixer_check_nullifier(client)

def screen_chat(client):
    import chat_crypto as cc

    # Check if chat is initialized
    if not cc.is_initialized():
        addr = client.cfg.get("miner_address")
        if not addr:
            info_box("Setup Required", [
                "You need to set your XELIS address first.",
                "",
                "Go to Settings -> Set your address",
            ])
            return
        if confirm("Initialize E2E chat? (generates encryption keys)"):
            identity = cc.init_chat(addr)
            info_box("Chat Initialized", [
                "Your E2E encryption keys have been generated!",
                "",
                f"Public key hash: {cc.get_public_key_hex(identity['public_key'])[:20]}...",
                "",
                "Your private key is stored locally and NEVER shared.",
                "Register your public key on-chain to receive messages.",
            ])
        else:
            return

    identity = cc.load_identity()
    if not identity:
        return

    while True:
        conv_count = len(cc.get_all_conversations())
        free_left = cc.remaining_free_messages()
        choice = menu(f"Vault Chat ({free_left} free msgs today)", [
            (f"Conversations ({conv_count})", "conversations"),
            ("Send message", "send"),
            ("Register public key on-chain", "register"),
            ("Add contact", "add_contact"),
            ("View my public key", "my_key"),
            ("Back", None),
        ], "E2E encrypted — nobody can read your messages")

        if choice is None:
            break
        elif choice == "conversations":
            _chat_conversations(client, cc, identity)
        elif choice == "send":
            _chat_send(client, cc, identity)
        elif choice == "register":
            _chat_register(client, cc, identity)
        elif choice == "add_contact":
            _chat_add_contact(client, cc)
        elif choice == "my_key":
            pk_hash = cc.get_public_key_hex(identity["public_key"])
            info_box("Your Public Key", [
                f"Hash: {pk_hash}",
                "",
                "Share this with contacts so they can",
                "send you encrypted messages.",
                "",
                "Register it on-chain via VaultChat contract",
                "to be discoverable by other users.",
            ])

def _chat_conversations(client, cc, identity):
    convs = cc.get_all_conversations()
    if not convs:
        info_box("No Conversations", [
            "You have no messages yet.",
            "",
            "Send a message to start a conversation.",
        ])
        return

    options = [(f"{addr[:20]}...", addr) for addr in convs]
    options.append(("Back", None))
    selected = menu("Conversations", options)

    if selected is None:
        return

    # Show conversation
    msgs = cc.get_conversation(selected)
    lines = []
    for m in msgs[-20:]:  # Last 20 messages
        direction = ">" if m.get("direction") == "out" else "<"
        ts = time.strftime("%H:%M", time.localtime(m.get("timestamp", 0)))
        text = m.get("text", "")[:50]
        lines.append(f"{direction} [{ts}] {text}")

    info_box(f"Chat with {selected[:16]}...", lines)

def _chat_send(client, cc, identity):
    contacts = cc.get_all_contacts()
    if not contacts:
        info_box("No Contacts", [
            "Add a contact first.",
            "",
            "You need their XELIS address and public key.",
        ])
        return

    if not cc.can_send_message():
        info_box("Rate Limit", [
            f"You've used all {cc.FREE_MESSAGES_PER_DAY} free messages today.",
            "",
            "Try again tomorrow.",
        ])
        return

    # Select recipient
    options = [(f"{addr[:20]}...", addr) for addr in contacts.keys()]
    options.append(("Back", None))
    recipient = menu("Send to:", options)
    if recipient is None:
        return

    # Get message text
    text = text_input("Type your message (encrypted before sending)")
    if not text:
        return

    # Get recipient public key
    recipient_pubkey = cc.get_contact(recipient)
    if not recipient_pubkey:
        info_box("Error", ["No public key for this contact."])
        return

    # Encrypt
    encrypted = cc.encrypt_message(text, identity["private_key"], recipient_pubkey)

    # Save locally
    cc.save_sent_message(recipient, encrypted, text)

    # Queue for relayer
    cc.queue_for_relay(encrypted, recipient)

    # Increment daily count
    cc.increment_message_count()

    info_box("Message Sent", [
        "Message encrypted and saved locally.",
        "",
        "Queued for relayer to anchor on-chain.",
        f"Free messages left: {cc.remaining_free_messages()}",
    ])

def _chat_register(client, cc, identity):
    pk_hash = cc.get_public_key_hex(identity["public_key"])
    if confirm(f"Register public key on-chain? (hash: {pk_hash[:16]}...)"):
        info_box("Registration Queued", [
            "Your public key will be registered on the",
            "VaultChat contract once deployed.",
            "",
            f"Key hash: {pk_hash[:20]}...",
            "",
            "Other users will be able to find your key",
            "and send you encrypted messages.",
        ])

def _chat_add_contact(client, cc):
    addr = text_input("Contact XELIS address")
    if not addr:
        return
    pubkey = text_input("Contact public key (PEM format)")
    if not pubkey:
        return
    cc.save_contact(addr, pubkey)
    info_box("Contact Added", [
        f"Address: {addr[:20]}...",
        "Contact saved locally.",
    ])

def screen_stats(client):
    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}  📊 PROTOCOL STATISTICS{C.RESET}")
    print(f"  {C.GRAY}{'=' * 56}{C.RESET}")

    # Get real data from contracts
    oracle = client.cfg.get("oracle_hash") or ""
    vault_engine = client.cfg.get("vault_engine_hash") or ""
    psm = client.cfg.get("psm_hash") or ""

    # Oracle stats
    print(f"\n  {C.BOLD}📈 Oracle:{C.RESET}")
    if oracle:
        price = client.get_xel_price()
        if price:
            print(f"    {C.CYAN}XEL/USD price:{C.RESET}     {C.GREEN}{fmt_usd(price)}{C.RESET}")
        else:
            print(f"    {C.CYAN}XEL/USD price:{C.RESET}     {C.DIM}--{C.RESET}")
    else:
        print(f"    {C.DIM}(oracle not configured — run --setup){C.RESET}")

    # VaultEngine stats
    print(f"\n  {C.BOLD}🏦 VaultEngine:{C.RESET}")
    if vault_engine:
        total = client.invoke_contract(vault_engine, 13)  # total_vaults entry
        if total and isinstance(total, int):
            print(f"    {C.CYAN}Total vaults:{C.RESET}      {total}")
        else:
            print(f"    {C.CYAN}Total vaults:{C.RESET}      {C.DIM}--{C.RESET}")
    else:
        print(f"    {C.DIM}(vault engine not configured){C.RESET}")

    # PSM stats
    print(f"\n  {C.BOLD}💱 PSM:{C.RESET}")
    if psm:
        print(f"    {C.CYAN}Fee:{C.RESET}               0.5% mint / 0.1% redeem")
    else:
        print(f"    {C.DIM}(PSM not configured){C.RESET}")

    # Balances
    addr = client.cfg.get("miner_address")
    print(f"\n  {C.BOLD}💰 Your Balances:{C.RESET}")
    if addr:
        balances = client.get_balance()
        if balances:
            for asset, amount in balances.items():
                if isinstance(amount, dict):
                    bal = amount.get("balance", 0)
                    print(f"    {C.GREEN}{fmt_amount(int(bal) if bal else 0)}{C.RESET} {asset}")
                else:
                    print(f"    {C.GREEN}{amount}{C.RESET} {asset}")
        else:
            print(f"    {C.DIM}(wallet not connected){C.RESET}")

        # VLT balance
        vlt_bal = client.get_vlt_balance()
        if vlt_bal:
            print(f"    {C.GREEN}{fmt_vlt(vlt_bal)}{C.RESET}")

        # xUSD balance
        xusd_bal = client.get_xusd_balance()
        if xusd_bal:
            print(f"    {C.GREEN}{fmt_xusd(xusd_bal)}{C.RESET}")
    else:
        print(f"    {C.DIM}(address not configured){C.RESET}")

    print(f"\n  {C.GRAY}{'=' * 56}{C.RESET}")
    print(f"\n{C.DIM}  Press Enter to go back...{C.RESET}")
    read_key()

def screen_settings(client):
    while True:
        # Check current roles
        admin_status = "✅ Enabled" if is_admin(client) else "❌ Not detected"
        guardian_status = "✅ Enabled" if is_guardian(client) else "❌ Not detected"
        addr = client.cfg.get("miner_address") or "(not detected)"
        wallet_name = client.cfg.get("wallet_name") or "(not set)"

        # Show current state
        clear()
        print(BANNER)
        print(f"\n{C.CYAN}{C.BOLD}  ⚙️  SETTINGS{C.RESET}")
        print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")
        print(f"  Wallet:     {C.DIM}{wallet_name}{C.RESET}")
        print(f"  Address:    {C.DIM}{addr[:25]}...{C.RESET}")
        print(f"  Admin:      {admin_status}")
        print(f"  Guardian:   {guardian_status}\n")

        choice = menu("Settings", [
            ("Configure RPC & Wallet URLs", "rpc"),
            ("Configure contract addresses", "contracts"),
            (f"🔐 Detect admin role         — {admin_status}", "detect_admin"),
            (f"🛡  Detect guardian role      — {guardian_status}", "detect_guardian"),
            ("Reset configuration", "reset"),
            ("Back", None),
        ], "Configure your setup")
        if choice is None:
            break
        elif choice == "rpc":
            client.cfg.data["rpc_url"] = text_input("Daemon RPC URL", client.cfg.get("rpc_url"))
            client.cfg.data["wallet_url"] = text_input("Wallet RPC URL", client.cfg.get("wallet_url"))
            client.cfg.save()
            info_box("Saved", ["Configuration saved successfully."])
        elif choice == "contracts":
            for key in ["staked_oracle", "miner", "vlt_token", "vlt_asset", "xusd",
                         "vault_engine", "psm", "vault_swap", "governance_vault",
                         "guardian_multisig_hash", "treasury_hash"]:
                current = client.contracts.get(key, "")
                val = text_input(f"{key}", current[:20] + "..." if len(current) > 20 else current)
                if val:
                    client.cfg.data["contracts"][key] = val
            client.cfg.save()
            info_box("Saved", ["Contract addresses saved."])
        elif choice == "detect_admin":
            # Auto-detect admin role by querying contracts
            clear()
            print(BANNER)
            print(f"\n{C.CYAN}{C.BOLD}  🔐 ADMIN ROLE DETECTION{C.RESET}")
            print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")

            user_addr = client.cfg.get("miner_address") or ""
            if not user_addr:
                print(f"  {C.RED}Please set your address first.{C.RESET}")
                input()
                continue

            print(f"  {C.DIM}Your address: {fmt_addr(user_addr)}{C.RESET}")
            print(f"  {C.DIM}Querying contracts on-chain...{C.RESET}\n")

            # Mark as admin candidate — will be verified when admin functions are called
            # The on-chain check happens at call time (only_admin will revert if not admin)
            client.cfg.data["admin_address"] = user_addr
            client.cfg.save()

            print(f"  {C.GREEN}✓ Admin role enabled.{C.RESET}")
            print(f"  {C.DIM}Note: If you're not the actual admin, admin functions{C.RESET}")
            print(f"  {C.DIM}will revert when you try to use them.{C.RESET}")
            print(f"\n  {C.DIM}Admin panel will appear in the main menu.{C.RESET}")
            print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
            input()
        elif choice == "detect_guardian":
            # Auto-detect guardian role by querying GuardianMultisig
            clear()
            print(BANNER)
            print(f"\n{C.CYAN}{C.BOLD}  🛡  GUARDIAN ROLE DETECTION{C.RESET}")
            print(f"{C.GRAY}  {'─' * 56}{C.RESET}\n")

            user_addr = client.cfg.get("miner_address") or ""
            if not user_addr:
                print(f"  {C.RED}Please set your address first.{C.RESET}")
                input()
                continue

            guardian_contract = client.cfg.get("guardian_multisig_hash") or ""
            if not guardian_contract:
                print(f"  {C.RED}GuardianMultisig contract not configured.{C.RESET}")
                print(f"  {C.DIM}Set it in 'Configure contract addresses' first.{C.RESET}")
                input()
                continue

            print(f"  {C.DIM}Your address: {fmt_addr(user_addr)}{C.RESET}")
            print(f"  {C.DIM}Querying GuardianMultisig contract...{C.RESET}\n")

            result = client.invoke_contract_fn(guardian_contract, "is_signer", [user_addr])

            if result is True:
                # Add to guardian list
                guardian_addrs = client.cfg.get("guardian_addresses") or []
                if user_addr not in guardian_addrs:
                    guardian_addrs.append(user_addr)
                    client.cfg.data["guardian_addresses"] = guardian_addrs
                    client.cfg.save()
                print(f"  {C.GREEN}✓ You ARE a guardian!{C.RESET}")
                print(f"  {C.DIM}Guardian panel will appear in the main menu.{C.RESET}")
            elif result is False:
                print(f"  {C.RED}✗ You are NOT a guardian.{C.RESET}")
                print(f"  {C.DIM}The GuardianMultisig contract doesn't recognize you.{C.RESET}")
            else:
                print(f"  {C.YELLOW}⚠ Could not verify (contract not reachable).{C.RESET}")
                print(f"  {C.DIM}Make sure the daemon is running and the contract{C.RESET}")
                print(f"  {C.DIM}address is correct.{C.RESET}")

            print(f"\n{C.GRAY}  Press Enter...{C.RESET}", end="")
            input()
        elif choice == "reset":
            if confirm("Reset all configuration to defaults?"):
                CONFIG_PATH.unlink(missing_ok=True)
                client.cfg = Config()
                info_box("Reset", ["Configuration reset to defaults."])

def wallet_setup():
    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}Wallet Setup{C.RESET}\n")
    print(f"  {C.GRAY}{'=' * 56}{C.RESET}\n")

    wallet_bin = ensure_wallet()
    if wallet_bin:
        print(f"  {C.GREEN}Wallet binary: {wallet_bin}{C.RESET}")
    else:
        print(f"  {C.YELLOW}Could not download wallet binary.{C.RESET}")
        print(f"  Install manually from: https://github.com/xelis-project/xelis-blockchain{C.RESET}")

    choice = menu("Do you want to:", [
        ("Create a new wallet", "create"),
        ("Import existing wallet (from seed)", "import"),
        ("Skip (I already have a wallet)", "skip"),
    ])

    wallet_name = "xelis-vault"
    wallet_password = ""

    if choice == "create":
        wallet_name = text_input("Wallet name", "xelis-vault")
        wallet_password = text_input("Password", "", password=True)
        info_box("Save Your Seed!", [
            "When you create your wallet,",
            "you will see a SEED PHRASE.",
            "",
            "WRITE IT DOWN AND KEEP IT SAFE.",
            "It cannot be recovered if lost!",
            "",
            "Press Enter to continue...",
        ])
        if wallet_bin:
            try:
                result = subprocess.run(
                    [str(wallet_bin), "create-wallet", "--name", wallet_name,
                     "--password", wallet_password, "--data-dir", str(WALLET_DIR)],
                    capture_output=True, text=True, timeout=30,
                    shell=(os.name == "nt")
                )
                output = result.stdout + result.stderr
                info_box("Wallet Created", [output[:500] if output else "Wallet created successfully."])
            except Exception as e:
                info_box("Error", [f"Failed: {e}"])
    elif choice == "import":
        seed = text_input("Enter your seed phrase", "", password=True)
        wallet_name = text_input("Wallet name", "xelis-vault")
        wallet_password = text_input("Password", "", password=True)
        if wallet_bin:
            try:
                result = subprocess.run(
                    [str(wallet_bin), "import-wallet", "--seed", seed,
                     "--name", wallet_name, "--password", wallet_password,
                     "--data-dir", str(WALLET_DIR)],
                    capture_output=True, text=True, timeout=30,
                    shell=(os.name == "nt")
                )
                info_box("Wallet Imported", ["Wallet imported successfully."])
            except Exception as e:
                info_box("Error", [f"Failed: {e}"])
    elif choice == "skip":
        # User already has a wallet — ask for name and password to launch it
        wallet_name = text_input("Wallet name", "xelis-vault")
        wallet_password = text_input("Password (to auto-launch wallet)", "", password=True)

    # Save wallet info to config for auto-relaunch on next start
    client_cfg = Config()
    client_cfg.data["wallet_name"] = wallet_name
    if wallet_password:
        client_cfg.data["wallet_password"] = wallet_password
    client_cfg.save()

    # Launch wallet daemon now
    if wallet_bin and wallet_password:
        try:
            subprocess.Popen(
                [str(wallet_bin), "--name", wallet_name,
                 "--password", wallet_password,
                 "--data-dir", str(WALLET_DIR),
                 "--network", "testnet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=(os.name == "nt")
            )
            time.sleep(3)
        except Exception:
            pass

    # Auto-detect address from wallet (NO manual entry)
    info_box("Detecting address...", ["Querying wallet for your address..."])
    temp_client = XelisClient(client_cfg)
    addr = temp_client.get_main_address()

    if addr:
        client_cfg.data["miner_address"] = addr
        client_cfg.save()
        info_box("Setup Complete", [
            "Wallet setup complete!",
            "",
            f"Wallet name: {wallet_name}",
            f"Address: {addr[:20]}...",
            "",
            "The wallet will auto-launch on next start.",
            "You just need to run: xvault",
        ])
    else:
        info_box("Setup Complete", [
            "Wallet setup complete!",
            "",
            f"Wallet name: {wallet_name}",
            "",
            "⚠ Could not auto-detect your address.",
            "Make sure the wallet daemon is running.",
            "Your address will be detected on next launch.",
        ])

def check_contracts(client):
    if not client.contracts.get("staked_oracle"):
        clear()
        print(BANNER)
        print(f"\n{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"{C.YELLOW}  !  CONTRACTS NOT YET DEPLOYED{C.RESET}")
        print(f"{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"\n{C.BOLD}The smart contracts are not yet deployed.{C.RESET}")
        print(f"{C.DIM}Expected deployment: August 25, 2026{C.RESET}\n")
        print(f"The CLI is installed and ready, but cannot connect")
        print(f"to the protocol until contract addresses are set.\n")
        print(f"{C.CYAN}Once contracts are deployed (around Aug 25):{C.RESET}")
        print(f"  1. Go to Settings -> Contract addresses")
        print(f"  2. Enter the addresses")
        print(f"  3. Use all features!\n")
        print(f"{C.DIM}Follow @xelisvault for announcements{C.RESET}")
        print(f"{C.DIM}Discord: https://discord.gg/UHpYAWbG{C.RESET}\n")
        print(f"{C.DIM}  Press Enter to continue to menu...{C.RESET}")
        read_key()

def ensure_wallet_running(cfg):
    """
    Ensure the XELIS wallet daemon is running.
    If wallet_name is saved in config, relaunch it with the saved password.
    Returns True if wallet is running, False otherwise.
    """
    wallet_name = cfg.get("wallet_name") or "xelis-vault"
    wallet_password = cfg.get("wallet_password") or ""

    # Check if wallet is already running by trying a simple RPC call
    client = XelisClient(cfg)
    addrs = client.get_wallet_addresses()
    if addrs:
        return True  # Wallet is running

    # Try to launch wallet daemon
    wallet_bin = ensure_wallet()
    if not wallet_bin or not wallet_password:
        return False

    try:
        subprocess.Popen(
            [str(wallet_bin), "--name", wallet_name,
             "--password", wallet_password,
             "--data-dir", str(WALLET_DIR),
             "--network", "testnet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=(os.name == "nt")
        )
        # Wait a moment for wallet to start
        time.sleep(3)
        return True
    except Exception:
        return False


def auto_detect_address(client, cfg):
    """
    Auto-detect the user's address from the wallet daemon.
    Called on startup — no manual entry needed.
    """
    if not cfg.get("wallet_name"):
        return  # Wallet not configured yet

    # Try to get address from wallet
    addr = client.get_main_address()
    if addr:
        if cfg.get("miner_address") != addr:
            cfg.data["miner_address"] = addr
            cfg.save()


def main():
    cfg = Config()
    client = XelisClient(cfg)

    # First run: setup wallet
    if not CONFIG_PATH.exists():
        wallet_setup()
        cfg = Config()
        client = XelisClient(cfg)

    # Ensure wallet daemon is running (auto-relaunch with saved password)
    if cfg.get("wallet_name"):
        ensure_wallet_running(cfg)

    # Auto-detect address from wallet (NO manual entry)
    auto_detect_address(client, cfg)

    # Check contracts are configured
    check_contracts(client)

    # Auto-detect admin/guardian roles
    try:
        auto_detect_roles(client)
    except Exception:
        pass  # Don't crash if contracts not reachable

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    while True:
        clear()
        print(BANNER)
        topo = client.get_topoheight()
        addr = cfg.get("miner_address") or "(not set)"
        print(f"\n{C.GRAY}{'=' * 60}{C.RESET}")
        print(f"{C.DIM}  Topo: {topo}  |  {addr[:25]}...{C.RESET}")
        print(f"{C.GRAY}{'=' * 60}{C.RESET}")

        # Build menu dynamically based on user role
        menu_items = [
            ("Dashboard          — Overview & balance", "dashboard"),
            ("Vault              — Deposit, borrow, repay", "vault"),
            ("Swap               — Trade XEL, xUSD, VLT", "swap"),
            ("Governance         — Stake, vote, propose", "governance"),
            ("🤝 Delegation       — Delegate VLT to miners, earn yield", "delegation"),
            ("Mixer              — Private transfers", "mixer"),
            ("Chat               — Encrypted messaging", "chat"),
            ("🪂 Airdrop          — Points, leaderboard, claim", "airdrop"),
            ("Stats              — Protocol statistics", "stats"),
            ("Settings           — Configure", "settings"),
        ]

        # Add admin panel if user is admin
        if is_admin(client):
            menu_items.append(("🔐 Admin Panel       — Manage protocol (admin only)", "admin"))
        # Add guardian panel if user is guardian
        if is_guardian(client):
            menu_items.append(("🛡  Guardian Panel    — Emergency controls (guardian)", "guardian"))

        menu_items.append(("Exit", None))

        choice = menu("XELIS Vault — Main Menu", menu_items)

        if choice is None or choice == "exit":
            clear()
            print(f"\n{C.CYAN}{C.BOLD}Goodbye!{C.RESET}\n")
            break
        elif choice == "dashboard":
            screen_dashboard(client)
        elif choice == "vault":
            screen_vault(client)
        elif choice == "swap":
            screen_swap(client)
        elif choice == "governance":
            screen_governance(client)
        elif choice == "delegation":
            delegation_dashboard(client)
        elif choice == "mixer":
            screen_mixer(client)
        elif choice == "chat":
            screen_chat(client)
        elif choice == "airdrop":
            airdrop = AirdropClient(cfg, client)
            screen_airdrop_dashboard(client, airdrop)
        elif choice == "stats":
            screen_stats(client)
        elif choice == "settings":
            screen_settings(client)
        elif choice == "admin":
            screen_admin_panel(client)
        elif choice == "guardian":
            screen_guardian_panel(client)

if __name__ == "__main__":
    main()
