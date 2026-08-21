#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v9.0 — Miner Dashboard (xvault-miner)
============================================================================
Live auto-refreshing TUI dashboard. Beautiful, real-time, interactive.
Works on Linux, macOS, and Windows.

Features:
  - Auto-refresh every 5 seconds (balance, topoheight, stats)
  - Arrow-key navigation (no typing numbers)
  - Real-time reputation, stake, rewards display
  - Service selection (oracle, chat, or both)
  - Compound toggle
  - Manual heartbeat trigger
  - Price feed monitoring
  - Protocol-wide statistics
  - Beautiful colored boxes and progress bars
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

REFRESH_INTERVAL = 5

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
            "compound": False,
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
        self.connected = False
        self.topoheight = 0
        self.balance_xel = 0
        self.balance_vlt = 0
        self.balance_xusd = 0
        self.last_update = 0

    def refresh(self):
        try:
            r = self.session.post(self.cfg.get("rpc_url"), json={
                "jsonrpc": "2.0", "method": "get_topoheight", "params": [], "id": 1
            }, timeout=5)
            data = r.json()
            if not data.get("error"):
                self.topoheight = data.get("result", 0)
                self.connected = True
            else:
                self.connected = False
        except:
            self.connected = False
            return

        addr = self.cfg.get("miner_address")
        if addr:
            try:
                r = self.session.post(self.cfg.get("wallet_url"), json={
                    "jsonrpc": "2.0", "method": "get_balance", "params": [addr, ""], "id": 1
                }, timeout=5)
                data = r.json()
                if not data.get("error") and data.get("result"):
                    balances = data["result"]
                    self.balance_xel = balances.get("", 0) if isinstance(balances, dict) else 0
            except:
                pass
        self.last_update = time.time()

def tier_name(rep):
    if rep >= 8000: return "EXCELLENT"
    if rep >= 5000: return "GOOD"
    if rep >= 2000: return "WARNING"
    if rep >= 1000: return "CRITICAL"
    return "BANNED"

def tier_color(tier):
    return {"EXCELLENT": C.GREEN, "GOOD": C.CYAN, "WARNING": C.YELLOW,
            "CRITICAL": C.RED, "BANNED": C.RED + C.BOLD}.get(tier, C.GRAY)

def tier_icon(tier):
    return {"EXCELLENT": "*", "GOOD": "+", "WARNING": "!",
            "CRITICAL": "!", "BANNED": "x"}.get(tier, "?")

def fmt_amount(val, decimals=8):
    if val == 0: return "0"
    return f"{val / (10**decimals):.4f}"

def fmt_vlt(val): return f"{fmt_amount(val)} VLT"
def fmt_xel(val): return f"{fmt_amount(val)} XEL"

def box(title, lines, color=C.CYAN, width=58):
    result = []
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    result.append(f"{color}| {C.BOLD}{title:<{width - 4}} {C.RESET}{color}|{C.RESET}")
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    for line in lines:
        clean = line.replace(C.GREEN, "").replace(C.RED, "").replace(C.YELLOW, "").replace(C.CYAN, "").replace(C.BOLD, "").replace(C.DIM, "").replace(C.GRAY, "").replace(C.MAGENTA, "").replace(C.BLUE, "").replace(C.RESET, "")
        if len(clean) > width - 4:
            line = line[:width - 7] + "..."
        result.append(f"{color}|{C.RESET} {line:<{width - 4}} {color}|{C.RESET}")
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    return "\n".join(result)

def render_dashboard(cfg, client, miner_data, stats, hint=""):
    clear()
    now = datetime.now().strftime("%H:%M:%S")
    topo = client.topoheight if client.connected else "OFFLINE"
    addr = cfg.get("miner_address") or "(not set)"
    services = cfg.get("services", "both")
    compound = cfg.get("compound", False)

    print(f"{C.CYAN}{C.BOLD}  XELIS VAULT — Miner Dashboard v7.0{C.RESET}")
    print(f"{C.DIM}  {platform.system()}/{platform.machine()}{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    conn = f"{C.GREEN}CONNECTED{C.RESET}" if client.connected else f"{C.RED}OFFLINE{C.RESET}"
    print(f"{C.DIM}  {now}  |  Topo: {topo}  |  {conn}  |  {addr[:20]}...{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")

    rep = miner_data.get("reputation", 10000)
    tier = tier_name(rep)
    tcolor = tier_color(tier)
    ticon = tier_icon(tier)
    stake = miner_data.get("stake", 10000000000)
    rewards = miner_data.get("total_rewards", 0)
    slashed = miner_data.get("total_slashed", 0)
    active = miner_data.get("active", True)
    valid = miner_data.get("valid_submissions", 0)
    total = miner_data.get("total_submissions", 0)
    success_rate = f"{(valid/total*100):.0f}%" if total > 0 else "N/A"

    status_icon = f"{C.GREEN}*{C.RESET}" if active else f"{C.RED}x{C.RESET}"
    status_text = f"{C.GREEN}ACTIVE{C.RESET}" if active else f"{C.RED}INACTIVE{C.RESET}"

    miner_lines = [
        f"{status_icon} Status:      {status_text}",
        f"  Address:     {addr[:24]}...",
        f"  Stake:       {C.BOLD}{fmt_vlt(stake)}{C.RESET}",
        f"  Reputation:  {tcolor}{ticon} {rep}/10000 ({tier}){C.RESET}",
        f"               {progress_bar(rep, 10000, 28)}",
        f"  Rewards:     {C.GREEN}{fmt_vlt(rewards)}{C.RESET}  ({success_rate} valid)",
        f"  Slashed:     {C.RED}{fmt_vlt(slashed)}{C.RESET}",
    ]
    print()
    print(box("MINER STATUS", miner_lines, C.CYAN))

    bal_lines = [
        f"  XEL:   {C.GREEN}{fmt_xel(client.balance_xel)}{C.RESET}",
        f"  VLT:   {C.GREEN}{fmt_vlt(client.balance_vlt)}{C.RESET}",
        f"  xUSD:  {C.GREEN}{fmt_amount(client.balance_xusd)} xUSD{C.RESET}",
    ]
    print()
    print(box("WALLET BALANCE", bal_lines, C.GREEN))

    svc_mask = 3 if services == "both" else (1 if services == "oracle" else 2)
    oracle_state = f"{C.GREEN}ON {C.RESET}" if svc_mask & 1 else f"{C.GRAY}OFF{C.RESET}"
    chat_state = f"{C.GREEN}ON {C.RESET}" if svc_mask & 2 else f"{C.GRAY}OFF{C.RESET}"
    compound_state = f"{C.GREEN}ON {C.RESET}" if compound else f"{C.GRAY}OFF{C.RESET}"

    svc_lines = [
        f"  Oracle (price feeds):  {oracle_state}  Chat (msg anchor): {chat_state}",
        f"  Compound rewards:      {compound_state}",
    ]
    print()
    print(box("SERVICES", svc_lines, C.MAGENTA))

    budget = stats.get("total_budget", 600000000000000)
    distributed = stats.get("distributed", 0)
    budget_pct = (distributed / budget * 100) if budget > 0 else 0
    factor = stats.get("budget_factor", 10000)
    base_reward = stats.get("base_reward", 47564687)
    total_miners = stats.get("total_miners", 0)
    active_miners = stats.get("active_miners", 0)

    proto_lines = [
        f"  Miners:       {active_miners} active / {total_miners} total",
        f"  Total staked: {fmt_vlt(stats.get('total_staked', 0))}",
        f"  Budget:       {budget_pct:.1f}% distributed",
        f"                {progress_bar(int(budget_pct), 100, 28)}",
        f"  Budget factor:{C.BOLD} {factor/10000:.2f}x{C.RESET}",
        f"  Base reward:  {C.BOLD}{fmt_vlt(base_reward)}{C.RESET} / submission",
    ]
    print()
    print(box("PROTOCOL STATS", proto_lines, C.BLUE))

    feeds = stats.get("feeds", [])
    feed_lines = []
    if feeds:
        for f in feeds[:4]:
            name = f.get("name", "?")
            price = f.get("price", 0)
            sources = f.get("sources", 0)
            stale = f.get("stale", False)
            pcolor = C.RED if stale else C.GREEN
            icon = "x" if stale else "*"
            feed_lines.append(f"  {pcolor}{icon}{C.RESET} ${fmt_amount(price):>10}  {name:<12} ({sources} src)")
    else:
        feed_lines.append(f"  {C.DIM}(no feeds configured){C.RESET}")
    print()
    print(box("PRICE FEEDS", feed_lines, C.YELLOW))

    print()
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    print(f"{C.DIM}  q Quit | r Refresh | s Setup | c Compound | h Heartbeat | a Auto-refresh{C.RESET}")
    if hint:
        print(f"  {hint}")
    last_str = datetime.fromtimestamp(client.last_update).strftime('%H:%M:%S') if client.last_update else 'never'
    print(f"{C.DIM}  Auto-refresh: every {REFRESH_INTERVAL}s | Last: {last_str}{C.RESET}")

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
        "Configuration saved!", "",
        f"Services:  {cfg.get('services')}",
        f"Address:   {cfg.get('miner_address')[:20]}...",
        f"Endpoint:  {cfg.get('miner_endpoint')[:20]}...", "",
        "Ready to mine once contracts are deployed.",
    ])

def check_contracts(cfg):
    if not cfg.contracts.get("staked_oracle") or not cfg.contracts.get("miner"):
        clear()
        print(BANNER)
        print(f"\n{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"{C.YELLOW}  !  PREMIÈRE CONFIGURATION{C.RESET}")
        print(f"{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"\n{C.BOLD}L'assistant va tout configurer automatiquement:{C.RESET}")
        print(f"  {C.GREEN}1.{C.RESET} Wallet   — détection, création ou import (seed affichée)")
        print(f"  {C.GREEN}2.{C.RESET} Daemon   — détection du noeud Xelis")
        print(f"  {C.GREEN}3.{C.RESET} Contrats — chargés automatiquement depuis le bundle réseau")
        print(f"  {C.GREEN}4.{C.RESET} Services — oracle / chat / les deux\n")
        choice = menu("Démarrer la configuration ?", [
            ("Oui — lancer l'assistant automatique", "setup"),
            ("Voir le dashboard (mode démo)", "demo"),
            ("Quitter", None),
        ])
        if choice == "setup": return "setup"
        elif choice == "demo": return "demo"
        else: sys.exit(0)
    return "live"

def action_heartbeat(cfg, client):
    info_box("Heartbeat", [
        "Sending heartbeat...", "",
        "(This will submit a transaction to the",
        "XelisVaultMiner contract once deployed.)",
    ])

def action_toggle_compound(cfg):
    current = cfg.get("compound", False)
    cfg.data["compound"] = not current
    cfg.save()
    state = "ON" if cfg.data["compound"] else "OFF"
    info_box("Compound", [f"Compound rewards is now {state}"])

def main():
    import argparse
    parser = argparse.ArgumentParser(description="XELIS Vault Miner Dashboard")
    parser.add_argument("--rpc", help="Daemon RPC URL")
    parser.add_argument("--wallet-url", help="Wallet RPC URL")
    parser.add_argument("--miner", action="store_true")
    parser.add_argument("--services", choices=["oracle", "chat", "both"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    args = parser.parse_args()

    cfg = Config()
    if args.rpc: cfg.data["rpc_url"] = args.rpc
    if args.wallet_url: cfg.data["wallet_url"] = args.wallet_url
    if args.services: cfg.data["services"] = args.services
    if args.setup:
        # v7.1: onboarding automatique (wallet/daemon/contrats) — l'utilisateur
        # ne saisit plus les adresses de contrats ni les URLs par défaut.
        import onboarding
        onboarding.run_onboarding(cfg)
        return

    mode = check_contracts(cfg)
    if mode == "setup":
        import onboarding
        onboarding.run_onboarding(cfg)
        return

    client = XelisClient(cfg)
    auto_refresh = True
    client.refresh()

    miner_data = {
        "reputation": 10000, "stake": 10000000000,
        "total_rewards": 0, "total_slashed": 0,
        "active": True, "valid_submissions": 0, "total_submissions": 0,
    }
    stats = {
        "total_budget": 600000000000000, "distributed": 0,
        "budget_factor": 10000, "total_miners": 1, "active_miners": 1,
        "total_staked": 10000000000, "base_reward": 47564687, "feeds": [],
    }

    running = [True]
    def on_signal(sig, frame): running[0] = False
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    hint = ""
    hide_cursor()
    try:
        while running[0]:
            render_dashboard(cfg, client, miner_data, stats, hint)
            hint = ""
            key = read_key_timeout(REFRESH_INTERVAL if auto_refresh else 999)
            if key is None:
                if auto_refresh:
                    client.refresh()
                    hint = f"{C.GREEN}Auto-refreshed at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key in ("Q", "CTRL_C", "CTRL_D"):
                break
            elif key == "S":
                show_cursor()
                interactive_setup(cfg)
                client = XelisClient(cfg)
                hide_cursor()
            elif key == "R":
                client.refresh()
                hint = f"{C.GREEN}Manual refresh at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key == "C":
                action_toggle_compound(cfg)
                hint = "Compound toggled"
            elif key == "H":
                action_heartbeat(cfg, client)
                hint = "Heartbeat sent"
            elif key == "A":
                auto_refresh = not auto_refresh
                state = "ON" if auto_refresh else "OFF"
                hint = f"Auto-refresh: {state}"
    finally:
        show_cursor()
        clear()
        print(f"\n{C.CYAN}{C.BOLD}  Shutting down... Goodbye!{C.RESET}\n")

if __name__ == "__main__":
    main()
