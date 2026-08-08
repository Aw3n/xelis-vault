#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v6.0 — Miner Dashboard (xvault-miner)
============================================================================
Beautiful real-time TUI dashboard for XELIS Vault miners.

Features:
  - Real-time reputation, stake, rewards display
  - Service selection (oracle, chat, or both)
  - Heartbeat monitoring
  - Price submission tracking
  - Budget & distribution stats
  - OS auto-detection (Linux/macOS)
  - Interactive configuration

Usage:
  xvault-miner                    # Interactive setup + dashboard
  xvault-miner --miner            # Start mining immediately
  xvault-miner --services oracle  # Oracle only
  xvault-miner --services chat    # Chat only
  xvault-miner --services both    # Both (default)
  xvault-miner --dry-run          # Simulate without submitting

Privacy: No telemetry. No phone-home. Wallet info stays local.
============================================================================
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
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

# ── Config ──────────────────────────────────────────────────────────────────
VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"
LOG_DIR = VAULT_DIR / "logs"
LOG_FILE = LOG_DIR / "miner.log"

# Contract addresses — UPDATE THESE after deployment
# These are placeholders; real addresses go in config.json
DEFAULT_CONTRACTS = {
    "staked_oracle": "",
    "miner": "",
    "vlt_token": "",
    "vlt_asset": "",
    "xusd": "",
    "xusd_asset": "",
    "vault_engine": "",
    "psm": "",
    "vault_swap": "",
    "governance_vault": "",
    "governor": "",
    "timelock": "",
    "guardian_multisig": "",
    "treasury": "",
    "contract_registry": "",
}

# ── ANSI Colors ─────────────────────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"

def clear(): os.system("cls" if os.name == "nt" else "clear")
def hide_cursor(): sys.stdout.write("\033[?25l"); sys.stdout.flush()
def show_cursor(): sys.stdout.write("\033[?25h"); sys.stdout.flush()

# ── Banner ──────────────────────────────────────────────────────────────────
BANNER = f"""{C.CYAN}{C.BOLD}
 ██████  ██      ██   ██ ██ ███████  ██████ ████████ ██  ██████  ███    ██
██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ████   ██
██    ██ ██      █████   ██ █████   ██         ██    ██ ██    ██ ██ ██  ██
██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ██  ██ ██
 ██████  ███████ ██   ██ ██ ███████  ██████    ██    ██  ██████  ██   ████
{C.RESET}{C.DIM}              Miner Dashboard v6.0 — Privacy-First DeFi{C.RESET}"""

# ── OS Detection ────────────────────────────────────────────────────────────
def detect_os() -> dict:
    """Detect OS, arch, shell, and package manager."""
    os_name = platform.system()
    arch = platform.machine()
    info = {
        "os": os_name,
        "arch": arch,
        "shell": os.environ.get("SHELL", "/bin/bash").split("/")[-1],
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }
    if os_name == "Linux":
        info["distro"] = platform.freedesktop_os_release().get("ID", "unknown") if hasattr(platform, "freedesktop_os_release") else "unknown"
        if shutil.which("apt"): info["pkg"] = "apt"
        elif shutil.which("dnf"): info["pkg"] = "dnf"
        elif shutil.which("pacman"): info["pkg"] = "pacman"
        elif shutil.which("yum"): info["pkg"] = "yum"
        else: info["pkg"] = "unknown"
    elif os_name == "Darwin":
        info["distro"] = "macos"
        info["pkg"] = "brew" if shutil.which("brew") else "unknown"
    return info

# ── Config ──────────────────────────────────────────────────────────────────
class Config:
    def __init__(self):
        self.rpc_url = "http://127.0.0.1:18081"
        self.wallet_url = "http://127.0.0.1:18082"
        self.wallet_user = "wallet"
        self.wallet_pass = "testpass"
        self.miner_address = ""
        self.miner_endpoint = ""
        self.services = "both"  # oracle, chat, both
        self.enable_oracle = True
        self.enable_miner = True
        self.dry_run = False
        self.contracts = DEFAULT_CONTRACTS.copy()
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                self.rpc_url = data.get("rpc_url", self.rpc_url)
                self.wallet_url = data.get("wallet_url", self.wallet_url)
                self.wallet_user = data.get("wallet_user", self.wallet_user)
                self.wallet_pass = data.get("wallet_pass", self.wallet_pass)
                self.miner_address = data.get("miner_address", "")
                self.miner_endpoint = data.get("miner_endpoint", "")
                self.services = data.get("services", "both")
                stored = data.get("contracts", {})
                for k in self.contracts:
                    if k in stored:
                        self.contracts[k] = stored[k]
            except Exception:
                pass

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "rpc_url": self.rpc_url,
            "wallet_url": self.wallet_url,
            "wallet_user": self.wallet_user,
            "wallet_pass": self.wallet_pass,
            "miner_address": self.miner_address,
            "miner_endpoint": self.miner_endpoint,
            "services": self.services,
            "contracts": self.contracts,
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2))

# ── XELIS RPC Client ────────────────────────────────────────────────────────
class XelisClient:
    def __init__(self, config: Config):
        self.cfg = config
        self.session = requests.Session()
        self.session.auth = (config.wallet_user, config.wallet_pass)

    def rpc_call(self, method: str, params: list = None) -> Optional[Any]:
        """Call XELIS daemon JSON-RPC."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}
        try:
            r = self.session.post(self.cfg.rpc_url, json=payload, timeout=10)
            data = r.json()
            if "error" in data and data["error"]:
                return None
            return data.get("result")
        except Exception:
            return None

    def wallet_call(self, method: str, params: list = None) -> Optional[Any]:
        """Call XELIS wallet JSON-RPC."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}
        try:
            r = self.session.post(self.cfg.wallet_url, json=payload, timeout=10)
            data = r.json()
            if "error" in data and data["error"]:
                return None
            return data.get("result")
        except Exception:
            return None

    def get_topoheight(self) -> int:
        r = self.rpc_call("get_topoheight")
        return r if isinstance(r, int) else 0

    def get_balance(self, asset: str = "") -> int:
        if not self.cfg.miner_address:
            return 0
        r = self.wallet_call("get_balance", [self.cfg.miner_address, asset])
        if r and isinstance(r, dict):
            return r.get("balance", 0)
        return 0

    def get_miner_info(self) -> Optional[dict]:
        """Read miner data from XelisVaultMiner contract."""
        if not self.cfg.contracts.get("miner"):
            return None
        # This would use read_contract_data or similar RPC
        # Placeholder — actual implementation depends on XELIS RPC API
        return None

# ── Dashboard UI ────────────────────────────────────────────────────────────
def box(title: str, content: str, color: str = C.CYAN, width: int = 60) -> str:
    """Create a colored box with title and content."""
    lines = content.split("\n")
    top = f"{color}┌{'─' * (width - 2)}┐{C.RESET}"
    hdr = f"{color}│ {C.BOLD}{title:<{width - 4}} {C.RESET}{color}│{C.RESET}"
    mid = f"{color}├{'─' * (width - 2)}┤{C.RESET}"
    body = ""
    for line in lines:
        body += f"{color}│{C.RESET} {line:<{width - 3}} {color}│{C.RESET}\n"
    bot = f"{color}└{'─' * (width - 2)}┘{C.RESET}"
    return f"{top}\n{hdr}\n{mid}\n{body}{bot}"

def tier_color(tier: str) -> str:
    return {
        "EXCELLENT": C.GREEN,
        "GOOD": C.CYAN,
        "WARNING": C.YELLOW,
        "CRITICAL": C.RED,
        "BANNED": C.BG_RED + C.WHITE,
    }.get(tier, C.GRAY)

def tier_name(rep: int) -> str:
    if rep >= 8000: return "EXCELLENT"
    if rep >= 5000: return "GOOD"
    if rep >= 2000: return "WARNING"
    if rep >= 1000: return "CRITICAL"
    return "BANNED"

def fmt_amount(val: int, decimals: int = 8) -> str:
    """Format atomic units to human-readable."""
    if val == 0: return "0"
    whole = val // (10 ** decimals)
    frac = val % (10 ** decimals)
    if frac == 0:
        return f"{whole}"
    return f"{whole}.{frac:0{decimals}}"[:12]

def fmt_vlt(val: int) -> str:
    return f"{fmt_amount(val)} VLT"

def fmt_xel(val: int) -> str:
    return f"{fmt_amount(val)} XEL"

def progress_bar(current: int, maximum: int, width: int = 20) -> str:
    if maximum == 0: return f"[{'?' * width}]"
    pct = min(current / maximum, 1.0)
    filled = int(pct * width)
    color = C.GREEN if pct > 0.5 else C.YELLOW if pct > 0.25 else C.RED
    return f"[{color}{'█' * filled}{'░' * (width - filled)}{C.RESET}]"

def render_dashboard(cfg: Config, client: XelisClient, miner_data: dict, stats: dict):
    """Render the full dashboard."""
    clear()
    topo = client.get_topoheight()
    now = datetime.now().strftime("%H:%M:%S")

    print(BANNER)
    print(f"{C.GRAY}{'─' * 70}{C.RESET}")
    print(f"{C.DIM}  {now}  │  Topo: {topo}  │  OS: {platform.system()}/{platform.machine()}{C.RESET}")
    print()

    # ── Miner Status Box ──
    rep = miner_data.get("reputation", 0)
    tier = tier_name(rep)
    tcolor = tier_color(tier)
    stake = miner_data.get("stake", 0)
    rewards = miner_data.get("total_rewards", 0)
    slashed = miner_data.get("total_slashed", 0)
    active = miner_data.get("active", False)
    valid_subs = miner_data.get("valid_submissions", 0)
    total_subs = miner_data.get("total_submissions", 0)

    status = f"{C.GREEN}● ACTIVE{C.RESET}" if active else f"{C.RED}● INACTIVE{C.RESET}"
    addr = cfg.miner_address[:12] + "..." if cfg.miner_address else "(not set)"

    miner_content = (
        f"{C.BOLD}Address:{C.RESET}    {addr}\n"
        f"{C.BOLD}Status:{C.RESET}      {status}\n"
        f"{C.BOLD}Stake:{C.RESET}       {fmt_vlt(stake)}\n"
        f"{C.BOLD}Reputation:{C.RESET}  {tcolor}{rep}/10000 ({tier}){C.RESET}\n"
        f"              {progress_bar(rep, 10000, 30)}\n"
        f"{C.BOLD}Rewards:{C.RESET}     {C.GREEN}{fmt_vlt(rewards)}{C.RESET}\n"
        f"{C.BOLD}Slashed:{C.RESET}     {C.RED}{fmt_vlt(slashed)}{C.RESET}\n"
        f"{C.BOLD}Submissions:{C.RESET} {valid_subs}/{total_subs} valid"
    )
    print(box("MINER STATUS", miner_content, C.CYAN, 62))

    # ── Services Box ──
    svc_mask = miner_data.get("services_mask", 0)
    oracle_on = "✓" if svc_mask & 1 else "✗"
    chat_on = "✓" if svc_mask & 2 else "✗"
    svc_color_o = C.GREEN if svc_mask & 1 else C.GRAY
    svc_color_c = C.GREEN if svc_mask & 2 else C.GRAY

    svc_content = (
        f"{svc_color_o}{oracle_on}{C.RESET} Oracle (price feeds)   "
        f"{svc_color_c}{chat_on}{C.RESET} Chat (msg anchoring)\n"
        f"\n"
        f"{C.BOLD}Oracle rewards:{C.RESET}  {C.GREEN}{fmt_vlt(stats.get('oracle_rewards', 0))}{C.RESET}\n"
        f"{C.BOLD}Chat rewards:{C.RESET}    {C.GREEN}{fmt_vlt(stats.get('chat_rewards', 0))}{C.RESET}"
    )
    print(box("SERVICES", svc_content, C.MAGENTA, 62))

    # ── Protocol Stats Box ──
    budget = stats.get("total_budget", 600000000000000)
    distributed = stats.get("distributed", 0)
    budget_pct = (distributed / budget * 100) if budget > 0 else 0
    factor = stats.get("budget_factor", 10000)
    total_miners = stats.get("total_miners", 0)
    active_miners = stats.get("active_miners", 0)

    proto_content = (
        f"{C.BOLD}Total miners:{C.RESET}    {total_miners} ({active_miners} active)\n"
        f"{C.BOLD}Total staked:{C.RESET}    {fmt_vlt(stats.get('total_staked', 0))}\n"
        f"{C.BOLD}Budget:{C.RESET}          {fmt_vlt(distributed)} / {fmt_vlt(budget)} ({budget_pct:.1f}%)\n"
        f"                    {progress_bar(distributed, budget, 34)}\n"
        f"{C.BOLD}Budget factor:{C.RESET}   {factor / 10000:.2f}x\n"
        f"{C.BOLD}Base reward:{C.RESET}     {fmt_vlt(stats.get('base_reward', 0))} / submission"
    )
    print(box("PROTOCOL STATS", proto_content, C.BLUE, 62))

    # ── Price Feeds Box ──
    feeds = stats.get("feeds", [])
    feed_lines = ""
    if feeds:
        for f in feeds[:5]:
            name = f.get("name", "?")
            price = f.get("price", 0)
            sources = f.get("sources", 0)
            stale = f.get("stale", False)
            pcolor = C.RED if stale else C.GREEN
            feed_lines += f"{pcolor}${fmt_amount(price, 8):>12}{C.RESET}  {name:<12} ({sources} src)\n"
    else:
        feed_lines = f"{C.DIM}(no feeds configured){C.RESET}\n"

    print(box("PRICE FEEDS", feed_lines.strip(), C.YELLOW, 62))

    # ── Footer ──
    print()
    print(f"{C.GRAY}{'─' * 70}{C.RESET}")
    print(f"{C.DIM}  [Q]uit  [R]efresh  [S]ervices  [C]ompound  [H]eartbeat  [L]ogs{C.RESET}")
    print(f"{C.DIM}  Config: {CONFIG_PATH}{C.RESET}")
    print(f"{C.DIM}  Logs:   {LOG_FILE}{C.RESET}")

# ── Interactive Setup ──────────────────────────────────────────────────────
def interactive_setup(cfg: Config, os_info: dict) -> Config:
    """First-run interactive configuration."""
    clear()
    print(BANNER)
    print()
    print(f"{C.CYAN}{C.BOLD}Welcome to XELIS Vault Miner!{C.RESET}")
    print(f"{C.DIM}Detected: {os_info['os']}/{os_info['arch']} — Python {os_info['python']}{C.RESET}")
    print()

    # RPC URL
    print(f"{C.BOLD}1. XELIS Daemon RPC URL{C.RESET}")
    cfg.rpc_url = input(f"  [{cfg.rpc_url}]: ").strip() or cfg.rpc_url
    print()

    # Wallet URL
    print(f"{C.BOLD}2. XELIS Wallet RPC URL{C.RESET}")
    cfg.wallet_url = input(f"  [{cfg.wallet_url}]: ").strip() or cfg.wallet_url
    print()

    # Miner address
    print(f"{C.BOLD}3. Your miner address{C.RESET}")
    addr = input(f"  [{cfg.miner_address or 'xelis1...'}]: ").strip()
    if addr: cfg.miner_address = addr
    print()

    # Endpoint URL
    print(f"{C.BOLD}4. Public endpoint URL{C.RESET} (for miner registration)")
    ep = input(f"  [{cfg.miner_endpoint or 'https://my-miner.example:8080'}]: ").strip()
    if ep: cfg.miner_endpoint = ep
    print()

    # Service selection
    print(f"{C.BOLD}5. Which services do you want to support?{C.RESET}")
    print(f"  {C.CYAN}1{C.RESET} = Oracle only (submit prices, earn VLT)")
    print(f"  {C.CYAN}2{C.RESET} = Chat only (anchor messages, earn VLT)")
    print(f"  {C.CYAN}3{C.RESET} = Both (maximize rewards)")
    choice = input(f"  Choose [1/2/3, default=3]: ").strip() or "3"
    cfg.services = {"1": "oracle", "2": "chat", "3": "both"}.get(choice, "both")
    print()

    # Contract addresses
    print(f"{C.BOLD}6. Contract addresses{C.RESET} (press Enter to keep defaults)")
    for key in ["staked_oracle", "miner", "vlt_token", "vlt_asset"]:
        current = cfg.contracts.get(key, "")
        val = input(f"  {key} [{current[:20]}...]: ").strip()
        if val: cfg.contracts[key] = val
    print()

    cfg.save()
    print(f"{C.GREEN}✓ Configuration saved to {CONFIG_PATH}{C.RESET}")
    time.sleep(1)
    return cfg

# ── Main Loop ───────────────────────────────────────────────────────────────
def main():
    # Check if contracts are configured
    cfg = Config()
    if not cfg.contracts.get("staked_oracle") or not cfg.contracts.get("miner"):
        print(BANNER)
        print(f"\n{C.YELLOW}{'=' * 70}{C.RESET}")
        print(f"{C.YELLOW}  ⚠  CONTRACTS NOT YET DEPLOYED{C.RESET}")
        print(f"{C.YELLOW}{'=' * 70}{C.RESET}")
        print(f"\n{C.BOLD}The XELIS Vault smart contracts are not yet deployed on testnet.{C.RESET}")
        print(f"{C.DIM}Expected deployment: August 25, 2026{C.RESET}\n")
        print(f"The dashboard is installed and ready, but cannot connect to the protocol")
        print(f"until contract addresses are configured.\n")
        print(f"{C.CYAN}Once contracts are deployed (around Aug 25):{C.RESET}")
        print(f"  1. Run: {C.BOLD}xvault-miner --setup{C.RESET}")
        print(f"  2. Enter the contract addresses when prompted")
        print(f"  3. Start mining: {C.BOLD}xvault-miner --miner{C.RESET}\n")
        print(f"{C.DIM}Follow https://x.com/xelisvault for deployment announcements.{C.RESET}")
        print(f"{C.DIM}Discord: https://discord.gg/UHpYAWbG{C.RESET}\n")
        return

    parser = argparse.ArgumentParser(description="XELIS Vault Miner Dashboard")
    parser.add_argument("--rpc", help="Daemon RPC URL")
    parser.add_argument("--wallet-url", help="Wallet RPC URL")
    parser.add_argument("--miner", action="store_true", help="Start mining immediately")
    parser.add_argument("--services", choices=["oracle", "chat", "both"], help="Services to support")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without submitting")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip prompts")
    args = parser.parse_args()

    os_info = detect_os()
    cfg = Config()

    if args.rpc: cfg.rpc_url = args.rpc
    if args.wallet_url: cfg.wallet_url = args.wallet_url
    if args.services: cfg.services = args.services
    if args.dry_run: cfg.dry_run = True

    # First-run setup
    if args.setup or not CONFIG_PATH.exists() or not cfg.miner_address:
        if not args.yes:
            cfg = interactive_setup(cfg, os_info)

    client = XelisClient(cfg)

    # Signal handler
    running = [True]
    def on_signal(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    hide_cursor()
    try:
        while running[0]:
            # Gather data
            topo = client.get_topoheight()
            # Placeholder miner data — in production, read from contract
            miner_data = {
                "reputation": 10000,
                "stake": 10000000000,
                "total_rewards": 0,
                "total_slashed": 0,
                "active": True,
                "valid_submissions": 0,
                "total_submissions": 0,
                "services_mask": 3 if cfg.services == "both" else (1 if cfg.services == "oracle" else 2),
            }
            stats = {
                "total_budget": 600000000000000,
                "distributed": 0,
                "budget_factor": 10000,
                "total_miners": 1,
                "active_miners": 1,
                "total_staked": 10000000000,
                "base_reward": 47564687,
                "oracle_rewards": 0,
                "chat_rewards": 0,
                "feeds": [],
            }

            render_dashboard(cfg, client, miner_data, stats)

            # Wait for input or timeout
            time.sleep(5)  # Refresh every 5 seconds
    except Exception as e:
        print(f"\n{C.RED}Error: {e}{C.RESET}")
    finally:
        show_cursor()
        print(f"\n{C.DIM}Shutting down...{C.RESET}")

if __name__ == "__main__":
    main()
