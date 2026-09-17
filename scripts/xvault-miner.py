#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — Miner / Oracle Operator Console (xvault-miner)
============================================================================
Live auto-refreshing dashboard + guided setup + operator handbook.

Run:  xvault-miner
      xvault-miner --setup        (guided first-time config)
      xvault-miner --rpc URL      (override daemon RPC)

Everything reads REAL on-chain state through the same cli_backend as the
xvault CLI. Keys:
      q quit   r refresh   a auto-refresh toggle   s setup
      m actions menu       p price-provider handbook
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

sys.path.insert(0, str(Path(__file__).parent))
from tui import (
    C, BANNER, clear, hide_cursor, show_cursor, read_key, read_key_timeout,
    menu, text_input, confirm, info_box, render_panel, render_metrics,
    render_badge, render_bar, render_ok, render_warn, render_error,
    render_status,
)
from cli_backend import Backend, DECIMALS
from protocol import RPCError

from config import Config, CONFIG_PATH, VAULT_DIR
LOG_DIR = VAULT_DIR / "logs"

REFRESH_INTERVAL = 5

# Miner struct field order (XelisVaultMiner.slx `Miner`) returned for key
# `miner_<addr>`:
#   0 addr, 1 endpoint_url, 2 miner_pubkey, 3 stake, 4 services_mask,
#   5 registered_at, 6 last_heartbeat, 7 total_rewards_earned,
#   8 total_slashed, 9 reputation, 10 valid_submissions,
#   11 successful_anchors, 12 total_submissions, 13 last_infraction_topo,
#   14 active
M_ADDR, M_ENDPOINT, M_PUBKEY, M_STAKE, M_MASK, M_AT, M_HB, M_REW, \
    M_SLASH, M_REP, M_VSUB, M_ANCH, M_TSUB, M_LINF, M_ACTIVE = range(15)

SERVICE_ORACLE, SERVICE_CHAT = 1, 2


# ---------------------------------------------------------------------------
# Tier / formatting helpers
# ---------------------------------------------------------------------------

def tier_name(rep):
    if rep >= 8000: return "EXCELLENT"
    if rep >= 5000: return "GOOD"
    if rep >= 2000: return "WARNING"
    if rep >= 1000: return "CRITICAL"
    return "LOW"


def tier_color(tier):
    return {"EXCELLENT": C.GREEN, "GOOD": C.CYAN, "WARNING": C.YELLOW,
            "CRITICAL": C.RED, "LOW": C.RED + C.BOLD}.get(tier, C.GRAY)


def tier_bar(rep):
    """Reputation as a fractional bar (quiet look)."""
    return render_bar(min(rep / 10000, 1.0), 20)


def svc_badges(mask):
    out = []
    if mask & SERVICE_ORACLE:
        out.append(render_badge("Oracle", C.CYAN))
    if mask & SERVICE_CHAT:
        out.append(render_badge("Chat relay", C.MAGENTA))
    return " ".join(out) if out else f"{C.DIM}none{C.RESET}"


# ---------------------------------------------------------------------------
# Live data collection (real reads via the backend)
# ---------------------------------------------------------------------------

def fetch_live(b: Backend) -> dict:
    live = {"connected": False, "topo": 0, "balances": {},
            "miner": {}, "miner_loaded": False, "stats": {}, "feeds": [],
            "relayer": None, "error": "", "endpoint_updatable": None}
    try:
        topo = b.daemon.topoheight()
        live["topo"] = topo
        live["balances"] = b.balances()
        if not b.address:
            raise ValueError("Operator address unavailable; check wallet/configuration")
        m = b.my_miner()
        if m is not None:
            if not isinstance(m, list) or len(m) < 15:
                raise ValueError("Invalid miner record returned by daemon")
            live["miner"] = {
                "endpoint": str(m[M_ENDPOINT]),
                "stake": int(m[M_STAKE]),
                "mask": int(m[M_MASK]),
                "registered_at": int(m[M_AT]),
                "hb_topo": int(m[M_HB]),
                "rewards": int(m[M_REW]),
                "slashed": int(m[M_SLASH]),
                "reputation": int(m[M_REP]),
                "valid_submissions": int(m[M_VSUB]),
                "anchors": int(m[M_ANCH]),
                "total_submissions": int(m[M_TSUB]),
                "active": bool(m[M_ACTIVE]),
            }
            live["endpoint_updatable"] = b.miner_supports_update_endpoint()
        live["miner_loaded"] = True
        live["stats"] = b.miner_stats()
        p = b.price()
        if p:
            price_raw, feed_topo, stale = p
            live["feeds"].append({"name": "XEL/USD", "price_raw": price_raw,
                                  "age": max(0, topo - feed_topo), "stale": stale})
        if b.has_wallet:
            live["relayer"] = b.chat_relayer_status(b.address)
        live["connected"] = True
    except (RPCError, ValueError, TypeError) as e:
        live["error"] = str(e)
    return live


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def render_dashboard(cfg, live, hint=""):
    clear()
    now = datetime.now().strftime("%H:%M:%S")
    addr = cfg.get("miner_address") or cfg.get("wallet_url") and "(wallet set)" or "(not set)"

    print(f"{C.CYAN}{C.BOLD}  XELIS VAULT {C.RESET}{render_badge('MINER / ORACLE OPERATOR', C.MAGENTA)}")
    print(f"{C.DIM}  {platform.system()}/{platform.machine()}  {C.GRAY}·{C.RESET}  {render_badge('TESTNET', C.YELLOW)}")
    print(f"{C.GRAY}{'─' * 60}{C.RESET}")

    conn = render_ok("CONNECTED") if live["connected"] else \
        render_error("UNAVAILABLE / INCOMPLETE READS")
    topo = f"{live['topo']:,}" if live["connected"] else "-"
    print(f"  {C.DIM}{now}{C.RESET}   {C.DIM}Topoheight:{C.RESET} {C.BOLD}{topo}{C.RESET}   {conn}")
    print(f"  {C.DIM}Operator:{C.RESET} {addr}")
    if live.get("error"):
        print(f"  {render_warn(live['error'])}")

    # ── Miner status ──
    m = live.get("miner") or {}
    if m:
        active = m.get("active", False)
        status = render_ok("REGISTERED") if active else render_warn("INACTIVE")
        rep = m.get("reputation", 3000)
        tier = tier_name(rep)
        tcolor = tier_color(tier)
        mask = m.get("mask", 0)
        hb = m.get("hb_topo", 0)
        if hb and live["connected"]:
            age = max(0, live["topo"] - hb)
            stats = live.get("stats") or {}
            interval = stats.get("heartbeat_interval")
            timeout = stats.get("heartbeat_timeout")
            if timeout and age > timeout:
                hb_txt = render_error(f"{age} blk ago — timeout exceeded")
            elif interval and age >= interval:
                hb_txt = render_warn(f"{age} blk ago — due")
            elif interval and timeout:
                hb_txt = render_ok(f"{age} blk ago")
            else:
                hb_txt = render_warn(f"{age} blk ago — schedule unknown")
        else:
            hb_txt = f"{C.DIM}unavailable{C.RESET}"
        m_lines = [
            f"  {status}   {render_badge(f'Reputation {rep} · {tier}', tcolor)}",
            render_metrics([
                ("Stake", bfmt(m.get("stake"), "VLT")),
                ("Rewards", f"{C.GREEN}{bfmt(m.get('rewards'), 'VLT')}{C.RESET}"),
            ], width=54),
            render_metrics([
                ("Services", svc_badges(mask)),
                ("Last heartbeat", hb_txt),
            ], width=54),
            f"  {C.DIM}Submissions:{C.RESET} {m.get('valid_submissions', 0)} valid / "
            f"{m.get('total_submissions', 0)} total   "
            f"{C.DIM}Anchors:{C.RESET} {m.get('anchors', 0)}   "
            f"{C.DIM}Slashed:{C.RESET} {C.RED}{bfmt(m.get('slashed'), 'VLT')}{C.RESET}",
            f"  {C.DIM}On-chain endpoint:{C.RESET} {m.get('endpoint') or '—'}",
            f"  {C.DIM}Reputation:{C.RESET} {tier_bar(rep)} {rep}/10000",
        ]
        desired = cfg.get("miner_endpoint")
        if desired and desired != m.get("endpoint"):
            support = live.get("endpoint_updatable")
            m_lines += [f"  Configured endpoint: {desired}"]
            if support is True:
                m_lines.append(render_warn("Not synchronized — Actions > Update endpoint"))
            elif support is False:
                m_lines.append(render_error("Not synchronized — contract cannot change it yet"))
                m_lines.append(f"  {C.DIM}update_endpoint (chunk 88) not deployed:{C.RESET}")
                m_lines.append(f"  {C.DIM}a developer upgrade of XelisVaultMiner is needed.{C.RESET}")
            else:
                m_lines.append(render_warn("Not synchronized — contract capability unknown"))
                m_lines.append(f"  {C.DIM}Refresh once the node answers.{C.RESET}")
        print()
        print(render_panel("  MINER  STATUS", m_lines, border_color=C.CYAN, width=58))
    else:
        print()
        if live.get("miner_loaded"):
            lines = [render_warn("Not registered"),
                     "This address has no miner profile on-chain yet.",
                     "Press m > Register to start earning VLT."]
        else:
            lines = [render_warn("Miner status unavailable"),
                     "Registration could not be checked; refresh after reconnecting."]
        print(render_panel("  MINER  STATUS", lines, border_color=C.CYAN, width=58))

    # ── Wallet balances ──
    bal = live.get("balances") or {}
    b_lines = []
    for sym in ("XEL", "VLT", "xUSD"):
        v = bal.get(sym)
        b_lines.append(f"  {C.BOLD}{sym:<5}{C.RESET}  {bfmt(v)}")
    print()
    print(render_panel("  WALLET  BALANCE", b_lines, border_color=C.GREEN, width=28))

    # ── Protocol stats ──
    stats = live.get("stats") or {}
    s_lines = []
    if stats.get("total_staked") is not None:
        s_lines.append(f"  Total staked:  {C.BOLD}{bfmt(stats['total_staked'], 'VLT')}{C.RESET}")
    if stats.get("budget") is not None and stats.get("distributed") is not None:
        pct = stats["distributed"] * 100 // stats["budget"] if stats["budget"] > 0 else 0
        s_lines += [
            f"  Budget spent:  {pct}%",
            f"                 {render_bar(pct / 100, 24)}",
        ]
    if stats.get("min_stake") is not None:
        s_lines.append(f"  Min stake:     {bfmt(stats['min_stake'], 'VLT')}")
    if stats.get("budget") is not None:
        s_lines.append(f"  Reward budget: {C.BOLD}{bfmt(stats['budget'], 'VLT')}{C.RESET}")
    if not s_lines:
        s_lines.append(f"  {C.DIM}(miner contract not reachable){C.RESET}")
    print()
    print(render_panel("  PROTOCOL  STATS", s_lines, border_color=C.BLUE, width=32))

    # ── Price feeds ──
    f_lines = []
    feeds = live.get("feeds") or []
    if feeds:
        for f in feeds[:6]:
            c = C.RED if f["stale"] else C.GREEN
            icon = "●" if f["stale"] else "●"
            price = f["price_raw"] / 10 ** DECIMALS
            f_lines.append(
                f"  {c}{icon}{C.RESET} ${price:>9,.4f}  {f['name']:<9}"
                f"  {C.DIM}age {f['age']} blk{C.RESET}")
    else:
        f_lines.append(f"  {C.DIM}(no oracle data yet){C.RESET}")
    print()
    print(render_panel("  PRICE  FEEDS", f_lines, border_color=C.YELLOW, width=40))

    # ── Relayer status ──
    rl = live.get("relayer")
    if rl:
        r_lines = []
        ok = rl.get("active")
        r_lines.append(f"  {render_status(bool(ok), 'Relayer')}")
        if rl.get("bond"):
            r_lines.append(f"  Bond: {C.BOLD}{bfmt(rl['bond'], 'VLT')}{C.RESET}")
        reg = rl.get("registered")
        if reg:
            r_lines.append(f"  Endpoint: {C.CYAN}{reg.get('endpoint', '')}{C.RESET}")
            r_lines.append(f"  {C.DIM}Free: {reg.get('free_daily_limit', '')} msg/day · "
                           f"{reg.get('free_wallet_slots', '')} slots{C.RESET}")
        print()
        print(render_panel("  RELAYER  (VaultChat)", r_lines, border_color=C.MAGENTA, width=48))

    print()
    print(f"{C.GRAY}{'─' * 60}{C.RESET}")
    if not cfg.get("wallet_url"):
        print(f"  {render_warn('No wallet connected — run setup (s).')}")
    print(f"  {C.DIM}q Quit │ r Refresh │ a Auto-refresh │ s Setup │ m Actions │ p Provider guide{C.RESET}")
    if hint:
        print(f"  {hint}")


def bfmt(v, suffix=""):
    """Format a possibly-None atomic balance."""
    if v is None:
        return f"{C.DIM}--{C.RESET}"
    n = v / 10 ** DECIMALS
    s = f"{n:,.4f}" if n >= 1 else f"{n:.8f}".rstrip("0").rstrip(".") or "0"
    return f"{C.GREEN}{s}{(' ' + suffix) if suffix else ''}{C.RESET}"


# ---------------------------------------------------------------------------
# Guided setup (every field explained — this was the #1 UX complaint)
# ---------------------------------------------------------------------------

def interactive_setup(cfg):
    clear()
    print(BANNER)
    print(f"\n{C.CYAN}{C.BOLD}Guided Miner Setup{C.RESET}")
    print(f"  {C.DIM}Most fields already carry a good default — press Enter to keep it.{C.RESET}\n")

    cfg.data["rpc_url"] = text_input(
        "Daemon JSON-RPC URL",
        cfg.get("rpc_url"))
    print(f"{C.DIM}  → Chain node. Use {C.CYAN}http://127.0.0.1:18081{C.RESET}{C.DIM} if your Xelis node runs locally.{C.RESET}")
    time.sleep(0.4)

    wurl = text_input(
        "Wallet RPC URL  (blank = read-only mode)",
        cfg.get("wallet_url"))
    print(f"{C.DIM}  → Your wallet RPC, e.g. {C.CYAN}http://127.0.0.1:18082{C.RESET}{C.DIM}.\n"
          f"    Needed only for writes: heartbeat, register, stake.{C.RESET}")
    time.sleep(0.4)
    cfg.data["wallet_url"] = wurl

    cfg.data["miner_address"] = text_input(
        "Operator address  (the wallet that becomes the miner)",
        cfg.get("miner_address"))
    print(f"{C.DIM}  → Must match the wallet above. Starts with {C.CYAN}xet:{C.RESET}{C.DIM}.{C.RESET}")
    time.sleep(0.4)

    endp = cfg.get("miner_endpoint")
    print(f"{C.CYAN}{C.BOLD}  Public endpoint URL (advertised service address){C.RESET}")
    print(f"  {C.DIM}This is where the network routes your services (price submissions for")
    print(f"  {C.DIM}Oracle, message anchoring for Chat relay). Examples:{C.RESET}")
    print(f"  {C.GREEN}  • https://mine.xelisvault.io{C.RESET}{C.DIM}   — a public relay you run/control{C.RESET}")
    print(f"  {C.GREEN}  • http://127.0.0.1:18081{C.RESET}{C.DIM}   — direct local node{C.RESET}")
    print(f"  {C.GREEN}  • ws://1.2.3.4:18081{C.RESET}{C.DIM}      — your own public node{C.RESET}\n")
    new_endp = text_input("Public endpoint URL", endp)
    cfg.data["miner_endpoint"] = new_endp.strip()
    print(f"{C.DIM}  → Cannot be empty and is written on-chain at registration.{C.RESET}")
    time.sleep(0.4)

    services = menu("Which services do you support? (maximises rewards)", [
        ("Oracle only — submit prices, earn VLT", "oracle"),
        ("Chat relay only — anchor messages, earn VLT", "chat"),
        ("Both — maximize rewards (recommended)", "both"),
    ])
    if services:
        cfg.data["services"] = services

    cfg.save()
    msg_lines = [
        render_ok("Configuration saved!"), "",
        f"Services:  {cfg.get('services')}",
        f"Address:   {(cfg.get('miner_address') or '(none)')}",
        f"Endpoint:  {(cfg.get('miner_endpoint') or '(none)')}", "",
        "Contract addresses load automatically from the network bundle.",
    ]
    msg_lines += ["Saved locally only; existing on-chain settings are unchanged.",
                  "Use Actions > Update endpoint to request an on-chain change, once the",
                  "deployed miner contract exposes that entry (see the miner status panel)."]
    info_box("Setup Complete", msg_lines, color=C.GREEN)


def check_contracts(cfg):
    """Contracts come from the network bundle; only setup state matters."""
    bundle_ok = bool(Backend(cfg.data).C("miner"))
    has_wallet = bool(cfg.get("wallet_url"))
    if not bundle_ok or not has_wallet:
        clear()
        print(BANNER)
        print(f"\n{C.YELLOW}{'─' * 60}{C.RESET}")
        print(f"{render_warn('FIRST-TIME SETUP')}")
        print(f"{C.YELLOW}{'─' * 60}{C.RESET}")
        reason = "contract bundle not found" if not bundle_ok else "no wallet configured"
        print(f"\n{C.BOLD}Need to configure: {reason}.{C.RESET}")
        print(f"  The wizard guides you, explains each field, and auto-loads")
        print(f"  contract addresses from the bundled network file.\n")
        choice = menu("Start configuration?", [
            ("Yes — run the guided setup (recommended)", "setup"),
            ("Manual settings only", "manual"),
            ("View dashboard anyway (read-only demo)", "demo"),
            ("Quit", None),
        ])
        if choice == "setup":
            interactive_setup(cfg)
            return "live"
        if choice == "manual":
            interactive_setup(cfg)
            return "live"
        if choice == "demo":
            return "demo"
        sys.exit(0)
    return "live"


# ---------------------------------------------------------------------------
# Price provider handbook — the "provider guide" the user asked for
# ---------------------------------------------------------------------------

PROVIDER_GUIDE = [
    ("What is a price provider?",
     "A miner with the Oracle service enabled. Every round you submit a price",
     "for XEL/USD; the protocol aggregates honest feeds and pays VLT via the",
     "reputation system. You also earn for correct, on-time submissions."),
    ("Ready to run as a provider?",
     "1. Register as a miner with Oracle service (menu -> Register).",
     "2. Fund the wallet with a bit of XEL for tx fees.",
     "3. Launch the keeper below — it auto-submits prices + heartbeats."),
    ("How the keeper works",
     "• submit_price every round with real exchange data",
     "• poke aggregate_now to unblock the aggregation window",
     "• heartbeat follows each wallet's on-chain last_heartbeat + hi",
     "• small fixed fee 0.001 XEL per tx; no cached price submissions"),
    ("Health rules (StakedOracle)",
     "Price rounds run every 200 blocks; check the feed's hard_stale.",
     "hi = heartbeat minimum interval read from the miner contract.",
     "ht = heartbeat timeout read from the miner contract.",
     "Keep reputation > 5000 (Good) to keep the 1.0x+ multiplier."),
    ("Tips",
     "• Never submit before the window opens (alreadysub deadlock).",
     "• Keep your node + wallet RPC online and synced.",
     "• This launcher uses your configured operator wallet only.",
     "• Restart the keeper after changing wallet/daemon configuration."),
]


def provider_guide(cfg):
    while True:
        clear()
        print(f"{C.CYAN}{C.BOLD}  PRICE PROVIDER — HANDBOOK & LAUNCHER{C.RESET}")
        print(f"{C.GRAY}{'─' * 60}{C.RESET}\n")
        panels = []
        for title, *body in PROVIDER_GUIDE:
            panels.append(render_panel(f"  {title}", body,
                                       border_color=C.CYAN, width=58))
        print("\n\n".join(panels))

        keeper_pid = keeper_running()
        if keeper_pid:
            kline = render_ok(f"Keeper RUNNING (pid {keeper_pid})")
            launcher = [("Stop oracle keeper", "stopkeeper")]
        else:
            kline = render_warn("Oracle keeper NOT running — no live price submissions")
            launcher = [("Launch oracle keeper (auto submits prices + heartbeats)", "keeper")]

        print()
        print(render_panel("  KEEPER  STATUS", [f"  {kline}"],
                           border_color=C.MAGENTA, width=40))
        print()
        opts = launcher + [
            ("Back to dashboard", None),
        ]
        choice = menu("Provider launcher", opts)
        if choice is None:
            return
        if choice == "keeper":
            launch_keeper(cfg)
        elif choice == "stopkeeper":
            stop_keeper()


KEEPER_PID = VAULT_DIR / "keeper.pid"


def keeper_running() -> int | None:
    try:
        pid = int(KEEPER_PID.read_text().strip())
    except Exception:
        return None
    from onboarding import process_alive
    if process_alive(pid):
        return pid
    KEEPER_PID.unlink(missing_ok=True)
    return None


def launch_keeper(cfg) -> None:
    import subprocess
    script = Path(__file__).parent / "oracle_keeper3.py"
    if not script.exists():
        info_box("Keeper", [render_error(f"oracle_keeper3.py not found at {script}")],
                 color=C.RED)
        return
    if keeper_running():
        info_box("Keeper", [render_warn("Keeper already running; stop it before restarting.")])
        return
    if not all(cfg.get(key) for key in ("rpc_url", "wallet_url", "miner_address")):
        info_box("Keeper", [render_error("Configure the daemon, wallet and operator address first.")], color=C.RED)
        return
    from onboarding import _detached_kwargs
    try:
        cfg.save()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        py = sys.executable or "python3"
        with open(LOG_DIR / "keeper.log", "ab") as logf:
            proc = subprocess.Popen(
                [py, "-u", str(script), "--config", str(CONFIG_PATH),
                 "--rpc", cfg.get("rpc_url")],
                stdout=logf, stderr=logf, **_detached_kwargs())
        KEEPER_PID.write_text(str(proc.pid))
    except OSError as e:
        info_box("Keeper", [render_error(f"Could not launch: {e}")], color=C.RED)
        return
    info_box("Keeper launched", [
        render_ok(f"Oracle keeper process launched (pid {proc.pid})"), "",
        "Uses your configured wallet; initialization and submissions are not yet verified.",
        f"Log: {LOG_DIR / 'keeper.log'}",
    ], color=C.GREEN)


def stop_keeper() -> None:
    pid = keeper_running()
    if not pid:
        info_box("Keeper", [render_warn("Keeper is not running.")])
        return
    from onboarding import terminate_process
    if terminate_process(pid):
        KEEPER_PID.unlink(missing_ok=True)
        info_box("Keeper stopped", [render_ok(f"Stopped pid {pid}.")], color=C.GREEN)
    else:
        info_box("Keeper", [render_error(f"Could not stop pid {pid}.")], color=C.RED)


# ---------------------------------------------------------------------------
# Actions (real transactions)
# ---------------------------------------------------------------------------

def action_registration_flow(cfg, b):
    """Guided registration with a clean explanation of service choice."""
    if not b.has_wallet:
        info_box("Register miner", [
            render_error("No wallet connected."),
            "Run setup (s) first, or just run 'xvault' to set one up.",
        ], color=C.RED)
        return
    if b.my_miner():
        info_box("Already registered", [
            render_ok("This address already has a miner profile."), "",
            "Use 'Increase stake' or 'Enable service' instead.",
        ], color=C.GREEN)
        return

    endpoint = cfg.get("miner_endpoint")
    if not endpoint:
        info_box("Register miner", [
            render_error("No public endpoint configured."),
            "Set your endpoint in Setup (s) — it is advertised on-chain.",
        ], color=C.RED)
        return

    svc = cfg.get("services", "both")
    mask = {"both": SERVICE_ORACLE | SERVICE_CHAT,
            "oracle": SERVICE_ORACLE, "chat": SERVICE_CHAT}.get(svc, 3)

    min_atomic = b.miner_stake_min() or 100 * 10 ** DECIMALS
    show_cursor()
    amt = text_input("VLT stake to deposit (minimum required by contract):",
                     default=f"{min_atomic / 10 ** DECIMALS:g}")
    hide_cursor()
    try:
        stake_atomic = int(float(amt) * 10 ** DECIMALS)
    except ValueError:
        return
    if stake_atomic <= 0:
        return

    print(f"{C.DIM}  Registering with: endpoints={endpoint}  services_mask={mask}  "
          f"stake={amt} VLT{C.RESET}\n")
    if not confirm(f"Register this address as a miner (services mask {mask}, "
                   f"endpoint {endpoint})?"):
        return
    res = b.miner_register(endpoint, mask, stake_atomic)
    if res.ok:
        info_box("Registration broadcast", [
            render_ok("Transaction broadcast; registration not yet verified"), "",
            f"Tx: {res.tx}",
            "Refresh miner status before sending further actions.",
        ], color=C.GREEN)
    else:
        info_box("Registration rejected", [render_error(f"Reason: {res.reason}")],
                 color=C.RED)


def action_heartbeat(cfg, b):
    if not b.has_wallet:
        info_box("Heartbeat failed", [
            render_error("No wallet connected."),
            "Run 'xvault' and complete the wallet setup first.",
        ], color=C.RED)
        return
    res = b.miner_heartbeat()
    if res.ok:
        info_box("Heartbeat sent", [
            render_ok("Transaction broadcast; execution not yet verified"), "",
            f"Tx: {res.tx}",
            "Refresh to check the on-chain heartbeat before retrying.",
        ], color=C.GREEN)
    else:
        info_box("Heartbeat rejected", [render_error(f"Reason: {res.reason}")],
                 color=C.RED)


def action_increase_stake(cfg, b):
    if not b.has_wallet:
        info_box("Increase stake", [render_error("No wallet connected.")], color=C.RED)
        return
    amt = text_input("VLT amount to add to miner stake:", default="100")
    try:
        atomic = int(float(amt) * 10 ** DECIMALS)
    except ValueError:
        return
    if atomic <= 0:
        return
    if confirm(f"Stake {amt} VLT more?"):
        res = b.miner_increase_stake(atomic)
        if res.ok:
            info_box("Stake transaction broadcast", [
                render_ok("Broadcast; refresh to verify the on-chain stake."), f"Tx: {res.tx}"],
                color=C.GREEN)
        else:
            info_box("Failed", [render_error(f"Reason: {res.reason}")], color=C.RED)


def action_enable_service(cfg, b):
    if not b.has_wallet:
        info_box("Enable service", [render_error("No wallet connected.")], color=C.RED)
        return
    svc = menu("Enable a service", [
        ("Oracle (submit prices, earn VLT)", SERVICE_ORACLE),
        ("Chat relay (anchor messages, earn VLT)", SERVICE_CHAT),
        ("Back", None),
    ])
    if not svc:
        return
    label = "Oracle" if svc == SERVICE_ORACLE else "Chat relay"
    if confirm(f"Enable {label} service?"):
        res = b.miner_enable_service(svc)
        if res.ok:
            info_box("Service transaction broadcast", [
                render_ok(f"Broadcast; refresh to verify {label} is enabled."), f"Tx: {res.tx}"],
                color=C.GREEN)
        else:
            info_box("Failed", [render_error(f"Reason: {res.reason}")], color=C.RED)


def action_update_endpoint(cfg, b):
    """Update the miner's public endpoint URL on-chain."""
    if not b.has_wallet:
        info_box("Update endpoint", [render_error("No wallet connected.")], color=C.RED)
        return
    try:
        m = b.my_miner()
    except RPCError as e:
        info_box("Update endpoint", [render_error(f"Cannot read miner status: {e}")], color=C.RED)
        return
    if not m:
        info_box("Update endpoint", [
            render_error("Not registered yet."),
            "Register first (Actions > Register as miner).",
        ], color=C.RED)
        return
    current = cfg.get("miner_endpoint") or ""
    if not isinstance(m, list) or len(m) < 15:
        info_box("Update endpoint", [
            render_error("Invalid miner record returned by daemon."),
            "Refresh miner status before retrying.",
        ], color=C.RED)
        return
    on_chain = str(m[M_ENDPOINT])
    new_ep = text_input(f"New public endpoint URL (on-chain: {on_chain}):", current).strip()
    if not new_ep:
        return
    if new_ep == on_chain:
        cfg.data["miner_endpoint"] = new_ep
        cfg.save()
        info_box("Endpoint", [render_ok("Endpoint already matches on-chain; local configuration saved.")])
        return
    if not confirm(f"Update on-chain endpoint to {new_ep}?"):
        return
    cfg.data["miner_endpoint"] = new_ep
    cfg.save()
    res = b.miner_update_endpoint(new_ep)
    if res.ok:
        info_box("Endpoint verified", [
            render_ok("On-chain endpoint verified"),
            f"  {C.CYAN}{new_ep}{C.RESET}",
        ] + ([f"Tx: {res.tx}"] if res.tx else []), color=C.GREEN)
    else:
        info_box("Endpoint not verified", [
            render_warn(f"Reason: {res.reason}"),
            "Desired endpoint saved locally; the dashboard shows the on-chain value.",
        ] + ([f"Tx: {res.tx}", "Check transaction/status before retrying."] if res.tx else []), color=C.YELLOW)


def action_menu(cfg, b):
    from onboarding import miner_running, start_miner, stop_miner
    running = miner_running()
    opts = [
        ("Register as miner (guided)", "reg"),
        ("Update public endpoint on-chain", "updatep"),
        ("Send heartbeat now", "hb"),
        ("Increase miner stake", "stake"),
        ("Enable a service", "svc"),
        ("Price provider handbook / keeper", "prov"),
    ]
    if running:
        opts.append(("Stop built-in PoW miner", "stopminer"))
    else:
        opts.append(("Start built-in PoW miner", "startminer"))
    opts.append(("Back", None))
    choice = menu("Miner actions", opts)
    if choice == "reg":
        action_registration_flow(cfg, b)
    elif choice == "updatep":
        action_update_endpoint(cfg, b)
    elif choice == "hb":
        action_heartbeat(cfg, b)
    elif choice == "stake":
        action_increase_stake(cfg, b)
    elif choice == "svc":
        action_enable_service(cfg, b)
    elif choice == "prov":
        provider_guide(cfg)
    elif choice == "startminer":
        ok, msg = start_miner(cfg)
        info_box("PoW miner", [render_ok(msg) if ok else render_error(msg)],
                 color=C.GREEN if ok else C.RED)
    elif choice == "stopminer":
        ok, msg = stop_miner()
        info_box("PoW miner", [render_ok(msg) if ok else render_error(msg)],
                 color=C.GREEN if ok else C.RED)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="XELIS Vault — Miner / Oracle console")
    parser.add_argument("--rpc", help="Daemon RPC URL")
    parser.add_argument("--wallet-url", help="Wallet RPC URL")
    parser.add_argument("--services", choices=["oracle", "chat", "both"])
    parser.add_argument("--miner", action="store_true", help="Open the miner actions menu")
    parser.add_argument("--dry-run", action="store_true", help="Read-only dashboard; no actions or processes")
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.setup:
        parser.error("--dry-run cannot be combined with --setup")

    cfg = Config()
    if args.rpc:
        cfg.data["rpc_url"] = args.rpc
    if args.wallet_url:
        cfg.data["wallet_url"] = args.wallet_url
    if args.services:
        cfg.data["services"] = args.services
    if args.setup:
        interactive_setup(cfg)
        return

    if not args.dry_run:
        check_contracts(cfg)

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
            live = fetch_live(b)
            render_dashboard(cfg, live, "Read-only mode (--dry-run)" if args.dry_run else hint)
            hint = ""
            if args.miner and not args.dry_run:
                key = "m"
                args.miner = False
            else:
                key = read_key_timeout(REFRESH_INTERVAL if auto_refresh else 999)
            if args.dry_run and key in ("s", "m", "p", "h"):
                continue
            if key is None:
                if auto_refresh:
                    hint = f"{C.DIM}Auto-refreshed at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key in ("Q", "CTRL_C", "CTRL_D"):
                break
            elif key == "s":
                show_cursor()
                interactive_setup(cfg)
                hide_cursor()
            elif key == "r":
                hint = f"{C.GREEN}Manual refresh at {datetime.now().strftime('%H:%M:%S')}{C.RESET}"
            elif key == "a":
                auto_refresh = not auto_refresh
                hint = f"Auto-refresh: {'ON' if auto_refresh else 'OFF'}"
            elif key in ("m", "p", "h"):
                show_cursor()
                try:
                    if key == "m":
                        action_menu(cfg, b)
                    elif key == "p":
                        provider_guide(cfg)
                    else:
                        action_heartbeat(cfg, b)
                except RPCError as e:
                    info_box("RPC unavailable", [render_error(str(e)),
                             "Check transaction/status before retrying an action."], color=C.RED)
                finally:
                    hide_cursor()
    finally:
        show_cursor()
        clear()
        print(f"\n{C.CYAN}{C.BOLD}  Shutting down... Goodbye!{C.RESET}\n")


if __name__ == "__main__":
    main()
