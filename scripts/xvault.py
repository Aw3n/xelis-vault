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
            ("View all vaults (liquidation)", "all"),
            ("Back", None),
        ], "Deposit XEL, borrow xUSD, earn")
        if choice is None or choice is None:
            break
        info_box("Coming Soon", [
            "This feature will be available once",
            "contracts are deployed on testnet.",
            "",
            "Expected: August 25, 2026",
            "",
            "Follow @xelisvault for updates",
        ])

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
        info_box("Coming Soon", [
            "This feature will be available once",
            "contracts are deployed on testnet.",
            "",
            "Expected: August 25, 2026",
        ])

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
        info_box("Coming Soon", [
            "This feature will be available once",
            "contracts are deployed on testnet.",
            "",
            "Expected: August 25, 2026",
        ])

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
        info_box("Coming Soon", [
            "This feature will be available once",
            "contracts are deployed on testnet.",
            "",
            "Expected: August 25, 2026",
        ])

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
    print(f"\n{C.CYAN}{C.BOLD}Protocol Statistics{C.RESET}\n")
    print(f"  {C.GRAY}{'=' * 56}{C.RESET}")
    stats = [
        ("Oracle", [
            "XEL/USD price:     --",
            "Active miners:     --",
            "Last aggregation:  --",
            "Circuit breaker:   --",
        ]),
        ("VaultEngine", [
            "Total vaults:      --",
            "Total collateral:  --",
            "Total borrowed:    --",
            "Redemption queue:  --",
        ]),
        ("xUSD", [
            "Total supply:      --",
            "Peg deviation:     --",
        ]),
        ("AMM Pools", [
            "VLT/XEL reserve:   --",
            "xUSD/XEL reserve:  --",
            "24h volume:        --",
        ]),
    ]
    for section, lines in stats:
        print(f"\n  {C.BOLD}{section}:{C.RESET}")
        for line in lines:
            print(f"    {C.CYAN}{line}{C.RESET}")
    print(f"\n  {C.GRAY}{'=' * 56}{C.RESET}")
    print(f"\n{C.DIM}  Press Enter to go back...{C.RESET}")
    read_key()

def screen_settings(client):
    while True:
        choice = menu("Settings", [
            ("Configure RPC & Wallet URLs", "rpc"),
            ("Set your address", "address"),
            ("Configure contract addresses", "contracts"),
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
        elif choice == "address":
            client.cfg.data["miner_address"] = text_input("Your XELIS address", client.cfg.get("miner_address"))
            client.cfg.save()
            info_box("Saved", ["Address saved."])
        elif choice == "contracts":
            for key in ["staked_oracle", "miner", "vlt_token", "vlt_asset", "xusd",
                         "vault_engine", "psm", "vault_swap", "governance_vault"]:
                current = client.contracts.get(key, "")
                val = text_input(f"{key}", current[:20] + "..." if len(current) > 20 else current)
                if val:
                    client.cfg.data["contracts"][key] = val
            client.cfg.save()
            info_box("Saved", ["Contract addresses saved."])
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

    if choice == "create":
        name = text_input("Wallet name", "xelis-vault")
        password = text_input("Password", "", password=True)
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
                    [str(wallet_bin), "create-wallet", "--name", name,
                     "--password", password, "--data-dir", str(WALLET_DIR)],
                    capture_output=True, text=True, timeout=30,
                    shell=(os.name == "nt")
                )
                output = result.stdout + result.stderr
                info_box("Wallet Created", [output[:500] if output else "Wallet created successfully."])
            except Exception as e:
                info_box("Error", [f"Failed: {e}"])
    elif choice == "import":
        seed = text_input("Enter your seed phrase", "", password=True)
        name = text_input("Wallet name", "xelis-vault")
        password = text_input("Password", "", password=True)
        if wallet_bin:
            try:
                result = subprocess.run(
                    [str(wallet_bin), "import-wallet", "--seed", seed,
                     "--name", name, "--password", password,
                     "--data-dir", str(WALLET_DIR)],
                    capture_output=True, text=True, timeout=30,
                    shell=(os.name == "nt")
                )
                info_box("Wallet Imported", ["Wallet imported successfully."])
            except Exception as e:
                info_box("Error", [f"Failed: {e}"])

    client_cfg = Config()
    client_cfg.save()
    info_box("Setup Complete", [
        "Wallet setup complete!",
        "",
        "Next: configure your address in Settings.",
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

def main():
    cfg = Config()
    client = XelisClient(cfg)

    if not CONFIG_PATH.exists():
        wallet_setup()

    check_contracts(client)

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    while True:
        clear()
        print(BANNER)
        topo = client.get_topoheight()
        addr = cfg.get("miner_address") or "(not set)"
        print(f"\n{C.GRAY}{'=' * 60}{C.RESET}")
        print(f"{C.DIM}  Topo: {topo}  |  {addr[:25]}...{C.RESET}")
        print(f"{C.GRAY}{'=' * 60}{C.RESET}")

        choice = menu("XELIS Vault — Main Menu", [
            ("Dashboard          — Overview & balance", "dashboard"),
            ("Vault              — Deposit, borrow, repay", "vault"),
            ("Swap               — Trade XEL, xUSD, VLT", "swap"),
            ("Governance         — Stake, vote, propose", "governance"),
            ("Mixer              — Private transfers", "mixer"),
            ("Chat               — Encrypted messaging", "chat"),
            ("🪂 Airdrop          — Points, leaderboard, claim", "airdrop"),
            ("Stats              — Protocol statistics", "stats"),
            ("Settings           — Configure", "settings"),
            ("Exit", None),
        ])

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

if __name__ == "__main__":
    main()
