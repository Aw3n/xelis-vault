#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v7.0 — Miner Dashboard (xvault-miner)
============================================================================
Interactive TUI dashboard with arrow-key navigation.
Works on Linux, macOS, and Windows.
============================================================================
"""
from __future__ import annotations
import json
import os
import platform
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from tui import *

VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"
LOG_DIR = VAULT_DIR / "logs"
LOG_FILE = LOG_DIR / "miner.log"

class Config:
    def __init__(self):
        self.data = {
            "rpc_url": "http://127.0.0.1:18081",
            "wallet_url": "http://127.0.0.1:18082",
            "wallet_user": "wallet",
            "wallet_pass": "testpass",
            "miner_address": "",
            "miner_endpoint": "",
            "services": "both",
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

def tier_name(rep):
    if rep >= 8000: return "EXCELLENT"
    if rep >= 5000: return "GOOD"
    if rep >= 2000: return "WARNING"
    if rep >= 1000: return "CRITICAL"
    return "BANNED"

def tier_color(tier):
    return {
        "EXCELLENT": C.GREEN, "GOOD": C.CYAN, "WARNING": C.YELLOW,
        "CRITICAL": C.RED, "BANNED": C.RED + C.BOLD,
    }.get(tier, C.GRAY)

def fmt_vlt(val):
    if val == 0: return "0"
    return f"{val / 1e8:.4f}"

def interactive_setup(cfg):
    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}Miner Setup{C.RESET}\n")
    print(f"  {C.GRAY}{'=' * 56}{C.RESET}\n")

    cfg.data["rpc_url"] = text_input("Daemon RPC URL", cfg.get("rpc_url"))
    cfg.data["wallet_url"] = text_input("Wallet RPC URL", cfg.get("wallet_url"))
    cfg.data["miner_address"] = text_input("Your miner address", cfg.get("miner_address"))
    cfg.data["miner_endpoint"] = text_input("Public endpoint URL", cfg.get("miner_endpoint"))

    services = menu("Which services do you want to support?", [
        ("Oracle only (submit prices, earn VLT)", "oracle"),
        ("Chat only (anchor messages, earn VLT)", "chat"),
        ("Both (maximize rewards)", "both"),
    ])
    if services:
        cfg.data["services"] = services

    for key in ["staked_oracle", "miner", "vlt_token", "vlt_asset"]:
        current = cfg.contracts.get(key, "")
        val = text_input(f"{key}", current[:20] + "..." if len(current) > 20 else current)
        if val:
            cfg.data["contracts"][key] = val

    cfg.save()
    info_box("Setup Complete", [
        "Configuration saved!",
        "",
        f"Services: {cfg.get('services')}",
        f"Address:  {cfg.get('miner_address')[:20]}...",
        "",
        "You're ready to mine once contracts are deployed.",
    ])

def render_dashboard(cfg, client):
    clear()
    topo = client.get_topoheight()
    now = datetime.now().strftime("%H:%M:%S")
    addr = cfg.get("miner_address") or "(not set)"
    services = cfg.get("services", "both")

    print(BANNER)
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    print(f"{C.DIM}  {now}  |  Topo: {topo}  |  {platform.system()}/{platform.machine()}{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}\n")

    # Miner Status
    rep = 10000
    tier = tier_name(rep)
    tcolor = tier_color(tier)
    stake = 10000000000
    rewards = 0
    slashed = 0
    active = True
    valid_subs = 0
    total_subs = 0

    status = f"{C.GREEN}● ACTIVE{C.RESET}" if active else f"{C.RED}● INACTIVE{C.RESET}"

    print(f"  {C.CYAN}{C.BOLD}MINER STATUS{C.RESET}")
    print(f"  {C.GRAY}{'- ' * 30}{C.RESET}")
    print(f"  {C.BOLD}Address:{C.RESET}       {addr[:25]}...")
    print(f"  {C.BOLD}Status:{C.RESET}         {status}")
    print(f"  {C.BOLD}Stake:{C.RESET}          {fmt_vlt(stake)} VLT")
    print(f"  {C.BOLD}Reputation:{C.RESET}     {tcolor}{rep}/10000 ({tier}){C.RESET}")
    print(f"                  {progress_bar(rep, 10000, 30)}")
    print(f"  {C.BOLD}Rewards:{C.RESET}         {C.GREEN}{fmt_vlt(rewards)} VLT{C.RESET}")
    print(f"  {C.BOLD}Slashed:{C.RESET}         {C.RED}{fmt_vlt(slashed)} VLT{C.RESET}")
    print(f"  {C.BOLD}Submissions:{C.RESET}     {valid_subs}/{total_subs} valid")
    print()

    # Services
    svc_mask = 3 if services == "both" else (1 if services == "oracle" else 2)
    oracle_on = C.GREEN + "ON" if svc_mask & 1 else C.GRAY + "OFF"
    chat_on = C.GREEN + "ON" if svc_mask & 2 else C.GRAY + "OFF"

    print(f"  {C.MAGENTA}{C.BOLD}SERVICES{C.RESET}")
    print(f"  {C.GRAY}{'- ' * 30}{C.RESET}")
    print(f"  {C.BOLD}Oracle:{C.RESET}  {oracle_on}{C.RESET}   {C.BOLD}Chat:{C.RESET}  {chat_on}{C.RESET}")
    print()

    # Protocol Stats
    print(f"  {C.BLUE}{C.BOLD}PROTOCOL STATS{C.RESET}")
    print(f"  {C.GRAY}{'- ' * 30}{C.RESET}")
    print(f"  {C.BOLD}Total miners:{C.RESET}     --")
    print(f"  {C.BOLD}Total staked:{C.RESET}     -- VLT")
    print(f"  {C.BOLD}Budget:{C.RESET}           -- VLT distributed")
    print(f"  {C.BOLD}Budget factor:{C.RESET}    --")
    print(f"  {C.BOLD}Base reward:{C.RESET}      -- VLT/submission")
    print()

    # Price Feeds
    print(f"  {C.YELLOW}{C.BOLD}PRICE FEEDS{C.RESET}")
    print(f"  {C.GRAY}{'- ' * 30}{C.RESET}")
    print(f"  {C.DIM}(no feeds configured){C.RESET}")
    print()

    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    print(f"{C.DIM}  q Quit  r Refresh  s Setup  c Compound{C.RESET}")

def check_contracts(cfg):
    if not cfg.contracts.get("staked_oracle") or not cfg.contracts.get("miner"):
        clear()
        print(BANNER)
        print(f"\n{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"{C.YELLOW}  !  CONTRACTS NOT YET DEPLOYED{C.RESET}")
        print(f"{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"\n{C.BOLD}The smart contracts are not yet deployed.{C.RESET}")
        print(f"{C.DIM}Expected deployment: August 25, 2026{C.RESET}\n")
        print(f"The dashboard is installed and ready, but cannot")
        print(f"connect to the protocol until addresses are set.\n")
        print(f"{C.CYAN}Once contracts are deployed:{C.RESET}")
        print(f"  1. Run: xvault-miner --setup")
        print(f"  2. Enter contract addresses")
        print(f"  3. Start mining: xvault-miner --miner\n")
        print(f"{C.DIM}Follow @xelisvault for announcements{C.RESET}")
        print(f"{C.DIM}Discord: https://discord.gg/UHpYAWbG{C.RESET}\n")

        choice = menu("What do you want to do?", [
            ("Run setup now", "setup"),
            ("View dashboard (demo data)", "demo"),
            ("Exit", None),
        ])

        if choice == "setup":
            return "setup"
        elif choice == "demo":
            return "demo"
        else:
            sys.exit(0)
    return "live"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="XELIS Vault Miner Dashboard")
    parser.add_argument("--rpc", help="Daemon RPC URL")
    parser.add_argument("--wallet-url", help="Wallet RPC URL")
    parser.add_argument("--miner", action="store_true", help="Start mining")
    parser.add_argument("--services", choices=["oracle", "chat", "both"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("-y", "--yes", action="store_true")
    args = parser.parse_args()

    cfg = Config()

    if args.rpc: cfg.data["rpc_url"] = args.rpc
    if args.wallet_url: cfg.data["wallet_url"] = args.wallet_url
    if args.services: cfg.data["services"] = args.services

    if args.setup:
        interactive_setup(cfg)
        return

    # Check contracts
    mode = check_contracts(cfg)
    if mode == "setup":
        interactive_setup(cfg)
        return

    client = XelisClient(cfg)

    running = [True]
    def on_signal(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    hide_cursor()
    try:
        while running[0]:
            render_dashboard(cfg, client)
            # Wait for key with timeout (refresh every 5s)
            # In demo mode, just wait for any key
            key = read_key()
            if key in ("Q", "CTRL_C", "CTRL_D"):
                break
            elif key == "S":
                show_cursor()
                interactive_setup(cfg)
                hide_cursor()
            elif key == "R":
                continue  # Refresh
            elif key == "C":
                # Toggle compound
                pass
    finally:
        show_cursor()
        clear()
        print(f"\n{C.CYAN}{C.BOLD}Shutting down... Goodbye!{C.RESET}\n")

if __name__ == "__main__":
    main()
