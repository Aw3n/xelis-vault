#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — Miner Dashboard (xvault-miner)
============================================================================
Live auto-refreshing TUI dashboard for oracle/miner operators.
Real on-chain data via cli_backend (same layer as the xvault CLI).

Features:
  - Auto-refresh every 5 s (topoheight, balances, miner profile, feeds)
  - Real miner profile: stake, reputation, rewards, heartbeat age
  - Protocol-wide stats: total staked, reward budget distribution
  - Price feed monitoring with staleness detection
  - Real heartbeat transaction (h key) when a wallet is connected
============================================================================
"""
from __future__ import annotations

import json
import platform
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from tui import (
    C, BANNER, clear, hide_cursor, show_cursor, read_key_timeout,
    menu, text_input, confirm, info_box, progress_bar,
)
from cli_backend import Backend, DECIMALS

VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"
LOG_DIR = VAULT_DIR / "logs"

REFRESH_INTERVAL = 5


class Config:
    def __init__(self):
        self.data = {
            "rpc_url": "http://127.0.0.1:18081",
            "wallet_url": "",
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
            except Exception:
                pass

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.data, indent=2))

    def get(self, key, default=""):
        return self.data.get(key, default)

    @property
    def contracts(self):
        return self.data.get("contracts", {})


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_amount(val, decimals=8):
    if val is None or val == 0:
        return "0"
    return f"{val / (10 ** decimals):,.4f}"


def fmt_vlt(val): return f"{fmt_amount(val)} VLT"
def fmt_xel(val): return f"{fmt_amount(val)} XEL"


def tier_name(rep):
    if rep >= 8000: return "EXCELLENT"
    if rep >= 5000: return "GOOD"
    if rep >= 2000: return "WARNING"
    if rep >= 1000: return "CRITICAL"
    return "LOW"


def tier_color(tier):
    return {"EXCELLENT": C.GREEN, "GOOD": C.CYAN, "WARNING": C.YELLOW,
            "CRITICAL": C.RED, "LOW": C.RED + C.BOLD}.get(tier, C.GRAY)


def tier_icon(tier):
    return {"EXCELLENT": "*", "GOOD": "+", "WARNING": "!",
            "CRITICAL": "!", "LOW": "x"}.get(tier, "?")


_ANSI_STRIP = [C.GREEN, C.RED, C.YELLOW, C.CYAN, C.BOLD, C.DIM, C.GRAY,
               C.MAGENTA, C.BLUE, C.WHITE, C.RESET]


def box(title, lines, color=C.CYAN, width=58):
    result = []
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    result.append(f"{color}| {C.BOLD}{title:<{width - 4}} {C.RESET}{color}|{C.RESET}")
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    for line in lines:
        clean = line
        for code in _ANSI_STRIP:
            clean = clean.replace(code, "")
        pad = max(0, width - 4 - len(clean))
        result.append(f"{color}|{C.RESET} {line}{' ' * pad} {color}|{C.RESET}")
    result.append(f"{color}+{'-' * (width - 2)}+{C.RESET}")
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Live data collection (all real reads through the backend)
# ---------------------------------------------------------------------------

def fetch_live(b: Backend) -> dict:
    live = {"connected": False, "topo": 0, "balances": {},
            "miner": {}, "stats": {}, "feeds": []}
    topo = b.topo()
    if not topo:
        return live
    live["connected"] = True
    live["topo"] = topo

    bal = b.balances()
    live["balances"] = bal

    m = b.my_miner()
    if isinstance(m, list) and len(m) >= 15:
        try:
            live["miner"] = {
                "registered": bool(m[14]),
                "stake": int(m[3]),
                "reputation": int(m[9]),
                "rewards": int(m[7]),
                "slashed": int(m[8]),
                "valid_submissions": int(m[10]),
                "total_submissions": int(m[12]),
                "hb_topo": int(m[6]) if m[6] else 0,
                "services_mask": int(m[4]),
            }
        except (ValueError, TypeError):
            pass

    ms = b.miner_stats()
    live["stats"] = ms

    p = b.price()
    if p:
        price_raw, feed_topo, stale = p
        live["feeds"].append({"name": "XEL/USD", "price_raw": price_raw,
                              "age": max(0, topo - feed_topo), "stale": stale})
    return live


def render_dashboard(cfg, live, hint=""):
    clear()
    now = datetime.now().strftime("%H:%M:%S")
    addr = cfg.get("miner_address") or "(not set)"
    compound = cfg.get("compound", False)

    print(f"{C.CYAN}{C.BOLD}  XELIS VAULT — Miner Dashboard{C.RESET}")
    print(f"{C.DIM}  {platform.system()}/{platform.machine()}{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    conn = f"{C.GREEN}CONNECTED{C.RESET}" if live["connected"] else \
           f"{C.RED}OFFLINE — is the daemon running?{C.RESET}"
    topo = f"{live['topo']:,}" if live["connected"] else "-"
    print(f"{C.DIM}  {now}  |  Topo: {topo}  |  {conn}{C.RESET}")
    print(f"{C.DIM}  Address: {addr[:44]}{C.RESET}")
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")

    # ── Miner status ──
    m = live.get("miner") or {}
    rep = m.get("reputation", 10000)
    tier = tier_name(rep)
    tcolor, ticon = tier_color(tier), tier_icon(tier)
    stake = m.get("stake", 0)
    rewards = m.get("rewards", 0)
    slashed = m.get("slashed", 0)
    active = m.get("registered", False)
    valid = m.get("valid_submissions", 0)
    total = m.get("total_submissions", 0)
    success_rate = f"{(valid / total * 100):.0f}%" if total > 0 else "N/A"

    status_icon = f"{C.GREEN}*{C.RESET}" if active else f"{C.RED}x{C.RESET}"
    status_text = f"{C.GREEN}REGISTERED{C.RESET}" if active else \
                  f"{C.YELLOW}NOT REGISTERED{C.RESET}"
    hb = m.get("hb_topo", 0)
    if hb and live["connected"]:
        age = max(0, live["topo"] - hb)
        hb_line = f"  Last beat:   {age} blocks ago ({C.BOLD}h{C.RESET} to send one)"
    else:
        hb_line = f"  Last beat:   never"

    miner_lines = [
        f"{status_icon} Status:      {status_text}",
        f"  Stake:       {C.BOLD}{fmt_vlt(stake)}{C.RESET}",
        f"  Reputation:  {tcolor}{ticon} {rep}/10000 ({tier}){C.RESET}",
        f"               {progress_bar(rep, 10000, 28)}",
        f"  Rewards:     {C.GREEN}{fmt_vlt(rewards)}{C.RESET}  ({success_rate} valid)",
        f"  Slashed:     {C.RED}{fmt_vlt(slashed)}{C.RESET}",
        hb_line,
    ]
    print()
    print(box("MINER STATUS", miner_lines, C.CYAN))

    # ── Wallet balances ──
    bal = live.get("balances") or {}
    bal_lines = []
    for sym in ("XEL", "VLT", "xUSD"):
        v = bal.get(sym)
        bal_lines.append(f"  {sym:<5} {C.GREEN}{b_fmt(v)}{C.RESET}")
    print()
    print(box("WALLET BALANCE", bal_lines, C.GREEN))

    # ── Services ──
    services = cfg.get("services", "both")
    svc_mask_cfg = 3 if services == "both" else (1 if services == "oracle" else 2)
    svc_mask = m.get("services_mask", svc_mask_cfg) if m else svc_mask_cfg
    oracle_state = f"{C.GREEN}ON {C.RESET}" if svc_mask & 1 else f"{C.GRAY}OFF{C.RESET}"
    chat_state = f"{C.GREEN}ON {C.RESET}" if svc_mask & 2 else f"{C.GRAY}OFF{C.RESET}"
    compound_state = f"{C.GREEN}ON {C.RESET}" if compound else f"{C.GRAY}OFF{C.RESET}"
    svc_lines = [
        f"  Oracle (price feeds):  {oracle_state}  Chat (msg anchor): {chat_state}",
        f"  Compound rewards:      {compound_state}",
    ]
    print()
    print(box("SERVICES", svc_lines, C.MAGENTA))

    # ── Protocol stats ──
    stats = live.get("stats") or {}
    budget = stats.get("budget")
    distributed = stats.get("distributed")
    staked = stats.get("total_staked")
    proto_lines = [f"  Total staked: {fmt_vlt(staked) if staked is not None else '--'}"]
    if budget and distributed is not None:
        pct = distributed * 100 // budget
        proto_lines += [
            f"  Reward budget: {pct}% distributed",
            f"                 {progress_bar(int(pct), 100, 28)}",
            f"  Budget size:   {fmt_vlt(budget)}",
        ]
    elif distributed is not None:
        proto_lines.append(f"  Distributed:  {fmt_vlt(distributed)}")
    if not proto_lines or (len(proto_lines) == 1 and "--" in proto_lines[0]):
        proto_lines.append(f"  {C.DIM}(miner contract not reachable){C.RESET}")
    print()
    print(box("PROTOCOL STATS", proto_lines, C.BLUE))

    # ── Price feeds ──
    feed_lines = []
    feeds = live.get("feeds") or []
    if feeds:
        for f in feeds[:6]:
            pcolor = C.RED if f["stale"] else C.GREEN
            icon = "x" if f["stale"] else "*"
            price = f["price_raw"] / 10 ** DECIMALS
            feed_lines.append(
                f"  {pcolor}{icon}{C.RESET} ${price:>10,.4f}  {f['name']:<10}"
                f" (age {f['age']} blocks)")
    else:
        feed_lines.append(f"  {C.DIM}(no oracle data yet){C.RESET}")
    print()
    print(box("PRICE FEEDS", feed_lines, C.YELLOW))

    print()
    print(f"{C.GRAY}{'=' * 60}{C.RESET}")
    wallet_note = "" if cfg.get("wallet_url") else \
        f"  {C.YELLOW}No wallet connected — run 'xvault' once to set up.{C.RESET}\n"
    print(wallet_note, end="")
    print(f"{C.DIM}  q Quit | r Refresh | s Setup | c Compound | h Heartbeat | a Auto-refresh{C.RESET}")
    if hint:
        print(f"  {hint}")


def b_fmt(v):
    """Format a balance that may be None."""
    if v is None:
        return f"{C.DIM}--{C.RESET}"
    return f"{v / 10 ** DECIMALS:,.4f}"


# ---------------------------------------------------------------------------
# Setup screens
# ---------------------------------------------------------------------------

def interactive_setup(cfg):
    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}Miner Setup{C.RESET}\n")
    print(f"  {C.GRAY}{'=' * 56}{C.RESET}\n")
    cfg.data["rpc_url"] = text_input("Daemon RPC URL", cfg.get("rpc_url"))
    wurl = text_input("Wallet RPC URL (empty = read-only)", cfg.get("wallet_url"))
    cfg.data["wallet_url"] = wurl
    cfg.data["miner_address"] = text_input("Your miner address", cfg.get("miner_address"))
    cfg.data["miner_endpoint"] = text_input("Public endpoint URL", cfg.get("miner_endpoint"))
    services = menu("Which services do you want to support?", [
        ("Oracle only (submit prices, earn VLT)", "oracle"),
        ("Chat only (anchor messages, earn VLT)", "chat"),
        ("Both (maximize rewards)", "both"),
    ])
    if services:
        cfg.data["services"] = services
    cfg.save()
    info_box("Setup Complete", [
        "Configuration saved!", "",
        f"Services:  {cfg.get('services')}",
        f"Address:   {(cfg.get('miner_address') or '')[:20]}...",
        f"Endpoint:  {(cfg.get('miner_endpoint') or '')[:20]}...", "",
        "Contract addresses are loaded automatically",
        "from the bundled network file.",
    ])


def check_contracts(cfg):
    """Contracts come from the network bundle; only setup state matters."""
    bundle_ok = bool(Backend(cfg.data).C("miner"))
    has_wallet = bool(cfg.get("wallet_url"))
    if not bundle_ok or not has_wallet:
        clear()
        print(BANNER)
        print(f"\n{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"{C.YELLOW}  !  FIRST-TIME SETUP{C.RESET}")
        print(f"{C.YELLOW}{'=' * 60}{C.RESET}")
        print(f"\n{C.BOLD}The wizard configures everything automatically:{C.RESET}")
        print(f"  {C.GREEN}1.{C.RESET} Wallet   — detect, create or import (seed shown once)")
        print(f"  {C.GREEN}2.{C.RESET} Daemon   — find your Xelis node")
        print(f"  {C.GREEN}3.{C.RESET} Contracts — loaded from the bundled network file")
        print(f"  {C.GREEN}4.{C.RESET} Services  — oracle / chat / both\n")
        choice = menu("Start configuration?", [
            ("Yes — run the automatic wizard (recommended)", "setup"),
            ("Manual settings only", "manual"),
            ("View dashboard anyway (demo mode)", "demo"),
            ("Quit", None),
        ])
        if choice == "setup":
            import onboarding
            onboarding.run_onboarding(cfg)
            return "live"
        if choice == "manual":
            interactive_setup(cfg)
            return "live"
        if choice == "demo":
            return "demo"
        sys.exit(0)
    return "live"


# ---------------------------------------------------------------------------
# Actions (real transactions)
# ---------------------------------------------------------------------------

def action_heartbeat(cfg, b):
    if not b.has_wallet:
        info_box("Heartbeat failed", [
            "No wallet connected.",
            "Run 'xvault' and complete the wallet setup first."], color=C.RED)
        return
    res = b.miner_heartbeat()
    if res.ok:
        info_box("Heartbeat sent", [
            f"{C.GREEN}Transaction broadcast ✓{C.RESET}", "",
            f"Tx: {res.tx[:40]}…"], color=C.GREEN)
    else:
        info_box("Heartbeat rejected", [f"Reason: {res.reason}"], color=C.RED)


def action_toggle_compound(cfg):
    current = cfg.get("compound", False)
    cfg.data["compound"] = not current
    cfg.save()
    state = "ON" if cfg.data["compound"] else "OFF"
    info_box("Compound", [f"Compound rewards is now {state}",
                          "", "(applies to future reward payouts)"])


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

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
    if args.rpc:
        cfg.data["rpc_url"] = args.rpc
    if args.wallet_url:
        cfg.data["wallet_url"] = args.wallet_url
    if args.services:
        cfg.data["services"] = args.services
    if args.setup:
        import onboarding
        onboarding.run_onboarding(cfg)
        return

    mode = check_contracts(cfg)

    auto_refresh = True
    running = [True]

    def on_signal(sig, frame):
        running[0] = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    hint = ""
    hide_cursor()
    try:
        while running[0]:
            b = Backend(cfg.data)
            live = fetch_live(b) if mode != "demo" or b.topo() else \
                {"connected": False, "topo": 0, "balances": {}, "miner": {},
                 "stats": {}, "feeds": []}
            render_dashboard(cfg, live, hint)
            hint = ""
            key = read_key_timeout(REFRESH_INTERVAL if auto_refresh else 999)
            if key is None:
                if auto_refresh:
                    hint = f"{C.DIM}Auto-refreshed at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key in ("Q", "CTRL_C", "CTRL_D"):
                break
            elif key == "S":
                show_cursor()
                interactive_setup(cfg)
                hide_cursor()
            elif key == "R":
                hint = f"{C.GREEN}Manual refresh at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key == "C":
                action_toggle_compound(cfg)
            elif key == "H":
                show_cursor()
                action_heartbeat(cfg, b)
                time.sleep(1.2)
                hide_cursor()
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
