#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — Community CLI (xvault)
============================================================================
Interactive CLI with arrow-key navigation. No typing numbers.
Works on Linux, macOS, and Windows.

Live on-chain data & verified contract flows via cli_backend.
Features not yet enabled are clearly marked "coming soon".
============================================================================
"""
from __future__ import annotations

import json
import platform
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tui import (
    C, clear, hide_cursor, show_cursor, read_key, read_key_timeout,
    menu, text_input, confirm, info_box, progress_bar, BANNER,
)
from cli_backend import Backend, DECIMALS, OpResult

VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Config:
    def __init__(self):
        self.data = {
            "rpc_url": "http://127.0.0.1:18081",
            "wallet_url": "http://127.0.0.1:18082",
            "wallet_user": "wallet",
            "wallet_pass": "testpass",
            "miner_address": "",
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
        try:
            import os
            os.chmod(CONFIG_PATH, 0o600)   # contains the wallet file password
        except Exception:
            pass

    def get(self, key, default=""):
        return self.data.get(key, default)

    @property
    def contracts(self):
        return self.data.get("contracts", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def short_addr(a: str, n: int = 10) -> str:
    if not a:
        return "-"
    return f"{a[:n]}...{a[-6:]}"


def parse_amount(text: str) -> int | None:
    """Human amount → atomic (1e8). Returns None on invalid input."""
    text = text.strip().replace(",", "").replace("_", "")
    try:
        v = float(text)
    except ValueError:
        return None
    if v <= 0:
        return None
    return int(round(v * 10 ** DECIMALS))


def show_result(res, action: str):
    if res.ok:
        info_box("Transaction sent", [
            f"{C.GREEN}{action} successful{C.RESET}",
            "",
            f"Tx hash:",
            f"{C.DIM}{res.tx[:62]}{C.RESET}",
            *(            f"{C.DIM}{res.tx[i:i+62]}{C.RESET}" for i in range(62, len(res.tx), 62)),
            *(["",
               f"{C.GREEN}✔ Confirmée on-chain"
               + (f" — bloc {str(getattr(res, 'topo'))[:12]}…" if getattr(res, 'topo') else "")
               + f" en {getattr(res, 'secs', 0):.0f} s{C.RESET}"]
              if getattr(res, "confirmed", None) else
              ["", f"{C.YELLOW}⏳ Pas encore visible dans un bloc après "
                   f"{getattr(res, 'secs', 0):.0f} s — vérifie via 'History'.{C.RESET}"]),
        ], color=C.GREEN)
    else:
        friendly = _friendly_error(res.reason or "")
        if friendly:
            info_box("Insufficient balance", [
                f"{C.RED}{action}: {friendly}{C.RESET}",
                "",
                f"{C.GRAY}Tip: mint xUSD first (Swap > Mint) or lower the amount."
                f"{C.RESET}",
            ], color=C.RED)
        else:
            info_box("Transaction failed", [
                f"{C.RED}{action} was rejected by the chain{C.RESET}",
                "",
                f"Reason: {res.reason}",
            ], color=C.RED)


def ask_amount(b: Backend, asset: str, prompt_text: str, default: str = "1"):
    """text_input with the live balance always visible in the prompt."""
    try:
        bal = b.fmt(b.wallet.balance(asset))
    except Exception:
        bal = "?"
    return text_input(f"{prompt_text}  [balance: {bal}]", default=default)


def wait_confirm(b: Backend, tx: str, max_s: int = 90):
    """Poll the daemon until the tx lands in a block. Returns (ok, topo)."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        r = b.daemon.get_transaction(tx)
        if isinstance(r, dict):
            topo = (r.get("executed_in_block") or r.get("block_topoheight")
                    or r.get("topoheight"))
            if topo or r.get("blocks"):
                return True, topo
        time.sleep(3)
    return False, None


def run_tx(b: Backend, fn, action: str):
    """Pending indicator + confirmation feedback around a write op."""
    print(f"\n{C.DIM}⏳ Transaction en cours — signature → broadcast → attente du "
          f"bloc (~5-15 s)…{C.RESET}", flush=True)
    t0 = time.time()
    try:
        res = fn()
    except Exception as e:
        sys.stdout.write("\r\x1b[K"); sys.stdout.flush()
        show_result(OpResult(False, reason=str(e)[:200]), action)
        return None
    if not res.ok:
        sys.stdout.write("\r\x1b[K"); sys.stdout.flush()
        show_result(res, action)
        return None
    ok, topo = wait_confirm(b, res.tx)
    secs = time.time() - t0
    sys.stdout.write("\r\x1b[K"); sys.stdout.flush()
    res.confirmed = ok
    res.topo = topo
    res.secs = secs
    show_result(res, action)
    return res


def _friendly_error(msg: str):
    """Translate raw wallet PROOF errors into human text (FR/EN mix kept short)."""
    if "not enough funds" in msg:
        m = re.search(r"required:\s*(\d+),\s*available:\s*(\d+)", msg)
        if m:
            req, av = int(m.group(1)), int(m.group(2))
            return (f"available {av / 10**DECIMALS:.6g}, "
                    f"required {req / 10**DECIMALS:.6g}")
        return "not enough funds for amount + fee"
    return None


def _check_balance(b: Backend, asset: str, atomic: int) -> bool:
    """True if the wallet can spend `atomic` of `asset`; offers max otherwise."""
    try:
        avail = b.wallet.balance(asset)
    except Exception:
        return True                      # cannot check — let the chain decide
    if atomic <= avail:
        return True
    info_box("Insufficient balance", [
        f"{C.RED}Not enough funds in this wallet.{C.RESET}",
        "",
        f"Available: {C.BOLD}{b.fmt(avail)}{C.RESET}",
        f"Requested: {b.fmt(atomic)}",
        "",
        f"{C.GRAY}Lower the amount or top up your wallet.{C.RESET}",
    ], color=C.RED)
    return False


def coming_soon(name: str, desc: str):
    info_box(f"{name} — Coming soon", [
        f"{C.BOLD}{name}{C.RESET} is not enabled yet.",
        "",
        *desc,
        "",
        f"{C.GRAY}Follow the project for release updates.{C.RESET}",
    ], color=C.YELLOW)


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def screen_dashboard(b: Backend):
    """Live dashboard: auto-refreshes until a key is pressed."""
    hide_cursor()
    try:
        while True:
            clear()
            print(BANNER)
            topo = b.topo()
            price_info = b.price()
            bal = b.balances()
            ms = b.miner_stats()
            psm = b.psm_reserves()

            print(f"{C.GRAY}{'─' * 66}{C.RESET}")
            status = f"{C.GREEN}● connected{C.RESET}" if topo else f"{C.RED}○ daemon offline{C.RESET}"
            print(f"  Network: testnet   Topoheight: {C.BOLD}{topo:,}{C.RESET}   {status}")
            print()

            # Price feed
            if price_info:
                price_raw, feed_topo, stale = price_info
                age = max(0, topo - feed_topo)
                tag = f"{C.RED}STALE{C.RESET}" if stale else f"{C.GREEN}fresh{C.RESET}"
                print(f"  XEL/USD:  {C.BOLD}${price_raw / 10**DECIMALS:,.4f}{C.RESET}"
                      f"   feed age {age} blocks  [{tag}]")
            else:
                print(f"  XEL/USD:  {C.DIM}no oracle data{C.RESET}")

            # Balances
            xel, vlt, xusd = bal.get("XEL"), bal.get("VLT"), bal.get("xUSD")
            print()
            print(f"  Your wallet ({short_addr(b.address)}):")
            print(f"    XEL   {b.fmt(xel)}")
            print(f"    VLT   {b.fmt(vlt)}")
            print(f"    xUSD  {b.fmt(xusd)}")

            # Protocol
            print()
            print(f"  {C.BOLD}Protocol{C.RESET}")
            if psm:
                print(f"    PSM reserves     {b.fmt(psm.get('xel'))} XEL  | "
                      f"{b.fmt(psm.get('xusd'))} xUSD")
            if ms.get("total_staked") is not None:
                print(f"    Miner staked     {b.fmt(ms['total_staked'])} VLT")
            if ms.get("budget") is not None and ms.get("distributed") is not None:
                pct = ms["distributed"] * 100 // ms["budget"] if ms["budget"] else 0
                bar = progress_bar(ms["distributed"], ms["budget"], 24)
                print(f"    Rewards budget   {bar} {pct}%")

            print()
            print(f"  {C.DIM}Address: {b.address or 'not configured'}{C.RESET}")
            print()
            print(f"{C.GRAY}{'─' * 66}{C.RESET}")
            print(f"{C.DIM}  Refreshing every 3 s — press any key to go back{C.RESET}")

            for _ in range(30):  # 30 × 100 ms
                if read_key_timeout(0.1) is not None:
                    return
                time.sleep(0.0)
    finally:
        show_cursor()


def screen_vault(b: Backend):
    while True:
        vaults = b.my_vaults()
        opts = [("View my vaults", "view"),
                ("Open / top-up a vault (deposit XEL collateral)", "deposit")]
        if vaults:
            opts += [("Borrow xUSD", "borrow"),
                     ("Repay debt", "repay"),
                     ("Withdraw collateral", "withdraw")]
        opts.append(("Back", None))
        choice = menu("Vault — collateralized xUSD", opts,
                      subtitle="Deposit XEL, borrow xUSD at 200% minimum ratio")
        if choice is None:
            return
        if choice == "view":
            lines = []
            if not vaults:
                lines.append(f"{C.DIM}No vault yet. Deposit XEL to open one.{C.RESET}")
            for v in vaults:
                hf = b.health_factor(v)
                if hf is None:
                    hf_s = "--"
                elif hf == float("inf"):
                    hf_s = f"{C.GREEN}no debt{C.RESET}"
                elif hf < 1.05:
                    hf_s = f"{C.RED}⚠ {hf:.2f}{C.RESET}"
                elif hf < 1.5:
                    hf_s = f"{C.YELLOW}{hf:.2f}{C.RESET}"
                else:
                    hf_s = f"{C.GREEN}{hf:.2f}{C.RESET}"
                state = f"{C.RED}LIQUIDATED{C.RESET}" if v["liquidated"] else "active"
                lines.append(
                    f"Vault #{v['id']}  {state}")
                lines.append(
                    f"   Collateral: {b.fmt(v['collateral'], 'XEL')}   "
                    f"Debt: {b.fmt(v['borrow_amount'], 'xUSD')}   HF: {hf_s}")
            info_box("My vaults", lines or ["empty"], color=C.CYAN)
        elif choice == "deposit":
            amt = ask_amount(b, b.xel_asset, "XEL amount to deposit as collateral:")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, b.xel_asset, atomic):
                continue
            if confirm(f"Deposit {amt} XEL into the Vault?"):
                run_tx(b, lambda: b.vault_deposit(atomic), "Vault deposit")
        elif choice == "borrow":
            vid = text_input("Vault id:", default=str(vaults[0]["id"]))
            try:
                vid_i = int(vid)
            except ValueError:
                continue
            amt = ask_amount(b, b.xusd_asset, "xUSD amount to borrow:", "10")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Borrow {amt} xUSD against vault #{vid_i}?"):
                run_tx(b, lambda: b.vault_borrow(vid_i, atomic), "Borrow")
        elif choice == "repay":
            vid = text_input("Vault id:", default=str(vaults[0]["id"]))
            try:
                vid_i = int(vid)
            except ValueError:
                continue
            amt = ask_amount(b, b.xusd_asset, "xUSD amount to repay:", "10")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Repay {amt} xUSD on vault #{vid_i}?"):
                run_tx(b, lambda: b.vault_repay(vid_i, atomic), "Repay")
        elif choice == "withdraw":
            vid = text_input("Vault id:", default=str(vaults[0]["id"]))
            try:
                vid_i = int(vid)
            except ValueError:
                continue
            amt = ask_amount(b, b.xel_asset, "XEL amount to withdraw:", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Withdraw {amt} XEL from vault #{vid_i}?"):
                run_tx(b, lambda: b.vault_withdraw(vid_i, atomic), "Withdraw")


def screen_swap(b: Backend):
    usd = b.price_usd()
    while True:
        pools = b.amm_pools()
        psm = b.psm_reserves()
        sub = (f"XEL/USD ${usd:,.4f}   PSM reserves: "
               f"{b.fmt(psm.get('xel'))} XEL / {b.fmt(psm.get('xusd'))} xUSD"
               ) if usd else "Oracle price unavailable"
        choice = menu("Swap", [
            ("Mint xUSD from XEL (PSM)", "mint"),
            ("Redeem XEL from xUSD (PSM)", "redeem"),
            ("Swap via AMM pool", "swap"),
            ("View AMM pools", "pools"),
            ("Add liquidity to AMM pool", "liquidity"),
            ("Back", None),
        ], subtitle=sub)
        if choice is None:
            return
        if choice == "mint":
            amt = ask_amount(b, b.xel_asset, "XEL amount to convert to xUSD:")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, b.xel_asset, atomic):
                continue
            est = atomic / 10 ** DECIMALS * (usd or 1)
            if confirm(f"Mint {amt} XEL → ≈{est:.4f} xUSD ?"):
                run_tx(b, lambda: b.psm_mint(atomic), "Mint xUSD")
        elif choice == "redeem":
            avail = 0
            try:
                avail = b.wallet.balance(b.xusd_asset)
            except Exception:
                pass
            default = "1" if avail >= 10**DECIMALS else f"{avail / 10**DECIMALS:.6f}".rstrip("0").rstrip(".")
            amt = text_input(f"xUSD amount to redeem for XEL (you hold {b.fmt(avail)}):",
                             default=default or "0.5")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, b.xusd_asset, atomic):
                continue
            est = atomic / 10 ** DECIMALS / (usd or 1) if usd else 0
            if confirm(f"Redeem {amt} xUSD → ≈{est:.4f} XEL ?"):
                run_tx(b, lambda: b.psm_redeem(atomic), "Redeem xUSD")
        elif choice == "swap":
            pick = menu("Select direction", [
                ("XEL → xUSD", (b.xel_asset, b.xusd_asset)),
                ("xUSD → XEL", (b.xusd_asset, b.xel_asset)),
                ("XEL → VLT", (b.xel_asset, b.vlt_asset)),
                ("Back", None)])
            if not pick:
                continue
            ain, aout = pick
            sym_in = "XEL" if ain == b.xel_asset else ("xUSD" if ain == b.xusd_asset else "VLT")
            amt = ask_amount(b, ain, f"{sym_in} amount to swap:")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, ain, atomic):
                continue
            if confirm(f"Swap {amt} {sym_in} via AMM?"):
                run_tx(b, lambda: b.amm_swap(ain, aout, atomic), "AMM swap")
        elif choice == "pools":
            lines = []
            if not pools:
                lines.append(f"{C.DIM}No AMM pools yet.{C.RESET}")
            for p in pools:
                def sym(h):
                    return "XEL" if h == b.xel_asset else ("VLT" if h == b.vlt_asset else "xUSD")
                lines.append(f"{sym(p['a'])}/{sym(p['b'])}:  "
                             f"{b.fmt(p['reserve_a'], sym(p['a']))}  |  "
                             f"{b.fmt(p['reserve_b'], sym(p['b']))}")
            info_box("AMM pools", lines or ["empty"], color=C.CYAN)
        elif choice == "liquidity":
            coming_soon("Add liquidity", [
                "Liquidity provision UI requires LP token accounting",
                "which is being finalized.",
                "",
                "You can still swap through existing pools today."])


def screen_savings(b: Backend):
    while True:
        st = b.savings_stats()
        td = st.get("total_deposits")
        cx = st.get("contract_xusd")
        sub = (f"Total deposits: {b.fmt(td)} xUSD   |   Contract balance: "
               f"{b.fmt(cx)} xUSD") if td is not None else "Loading..."
        choice = menu("Savings (xUSD interest-bearing deposits)", [
            ("Deposit xUSD", "dep"),
            ("Withdraw xUSD", "wd"),
            ("Claim accrued interest", "claim"),
            ("Back", None),
        ], subtitle=sub)
        if choice is None:
            return
        if choice == "dep":
            amt = ask_amount(b, b.xusd_asset, "xUSD amount to deposit:", "10")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, b.xusd_asset, atomic):
                continue
            if confirm(f"Deposit {amt} xUSD into Savings?"):
                run_tx(b, lambda: b.savings_deposit(atomic), "Savings deposit")
        elif choice == "wd":
            amt = ask_amount(b, b.xusd_asset, "xUSD amount to withdraw:", "10")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Withdraw {amt} xUSD from Savings?"):
                run_tx(b, lambda: b.savings_withdraw(atomic), "Savings withdraw")
        elif choice == "claim":
            if confirm("Claim all accrued savings interest?"):
                run_tx(b, lambda: b.savings_claim_interest(), "Interest claim")


def screen_privacy(b: Backend):
    while True:
        st = b.mixer_stats()
        sub = (f"Pools pending: {st.get('pending', '-')}   mixes executed: "
               f"{st.get('total_mixes', '-')}   total mixed: "
               f"{b.fmt(st.get('total_mixed'))} XEL") if st else "Loading..."
        choice = menu("Privacy Mixer — private payments", [
            ("Send privately (mix to recipient)", "send"),
            ("Trigger mix execution now", "exec"),
            ("Request refund of my deposit", "refund"),
            ("How it works", "help"),
            ("Back", None),
        ], subtitle=sub)
        if choice is None:
            return
        if choice == "send":
            dest = text_input("Recipient address (xet:...):").strip()
            if not dest.startswith("xet:") or len(dest) < 20:
                info_box("Invalid address", ["Please enter a full xet: address."],
                         color=C.RED)
                continue
            amt = ask_amount(b, b.xel_asset, "XEL amount to send privately:", "0.1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if not _check_balance(b, b.xel_asset, atomic):
                continue
            if confirm(f"Privately send {amt} XEL?\nFunds are pooled and mixed "
                       f"(min anonymity 3) before delivery."):
                run_tx(b, lambda: b.mixer_send(dest, atomic), "Private send")
        elif choice == "exec":
            if confirm("Execute mixer pooling now?\n(Also runs automatically when a pool fills.)"):
                run_tx(b, lambda: b.mixer_execute_mix(), "Mix execution")
        elif choice == "refund":
            if confirm("Request refund of your pending mixer deposit?\n"
                       "(Only possible after the pool timeout.)"):
                run_tx(b, lambda: b.mixer_refund(), "Mixer refund")
        elif choice == "help":
            info_box("How the mixer works", [
                "1. You deposit XEL with a recipient address.",
                "2. Deposits wait in an anonymous pool",
                "   (min 3 participants).",
                "3. When the pool is ready, everyone's funds",
                "   are shuffled and paid out together —",
                "   breaking the on-chain link between sender",
                "   and recipient.",
                "",
                f"{C.YELLOW}Note: mixing takes time (hours to days).{C.RESET}",
            ], color=C.MAGENTA)


def screen_treasury(b: Backend):
    while True:
        t = b.treasury_info()
        sub = (f"{t.get('signers', '?')} signers · quorum {t.get('quorum', '?')} · "
               f"{t.get('proposals', '?')} proposals · treasury "
               f"{b.fmt(t.get('xel'))} XEL") if t else "Loading..."
        choice = menu("Treasury Vault (multisig)", [
            ("Fund the treasury (deposit)", "fund"),
            ("Create spending proposal (signer)", "propose"),
            ("Confirm proposal (signer)", "confirm"),
            ("Execute confirmed proposal (signer)", "execute"),
            ("Back", None),
        ], subtitle=sub)
        if choice is None:
            return
        if choice == "fund":
            amt = ask_amount(b, b.xel_asset, "XEL amount to deposit into treasury:")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Deposit {amt} XEL into the Treasury?"):
                run_tx(b, lambda: b.treasury_deposit(b.xel_asset, atomic), "Treasury deposit")
        elif choice == "propose":
            dest = text_input("Destination address (xet:...):").strip()
            if not dest.startswith("xet:"):
                continue
            amt = ask_amount(b, b.xel_asset, "XEL amount to propose spending:")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Propose spending {amt} XEL to {short_addr(dest)}?"):
                run_tx(b, lambda: b.treasury_propose(b.xel_asset, dest, atomic), "Proposal")
        elif choice in ("confirm", "execute"):
            pid = text_input("Proposal id:")
            try:
                pid_i = int(pid.strip())
            except ValueError:
                continue
            verb = "Confirm" if choice == "confirm" else "Execute"
            fn = b.treasury_confirm if choice == "confirm" else b.treasury_execute
            if confirm(f"{verb} proposal #{pid_i}?"):
                run_tx(b, lambda: fn(pid_i), f"Proposal {verb}")


def screen_rwa(b: Backend):
    av = b.C("asset_vault")
    ah = b.daemon.read_key(av, "ah") if av else None
    issuer = b.daemon.read_key(av, "i") if av else None
    while True:
        sub = (f"Issuer: {issuer[:18]}…" if issuer else "No RWA asset registered yet")
        opts = []
        if ah:
            opts.append(("Transfer RWA tokens", "transfer"))
        opts += [("Register new asset & mint (admin)", "create"),
                 ("Back", None)]
        choice = menu("RWA Assets (real-world assets)", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "transfer":
            dest = text_input("Recipient address (xet:...):").strip()
            if not dest.startswith("xet:"):
                continue
            amt = ask_amount(b, ah, "Token amount to transfer:", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Transfer {amt} RWA tokens to {short_addr(dest)}?"):
                run_tx(b, lambda: b.rwa_transfer(dest, atomic), "RWA transfer")
        elif choice == "create":
            name = text_input("Asset name (e.g. 'My Token'):")
            if not name:
                continue
            sym = text_input("Symbol (e.g. 'MTK'):")
            if not sym:
                continue
            dec = text_input("Decimals (default 8):").strip() or "8"
            sup = text_input("Initial supply (human-readable, e.g. 1000):")
            if not sup:
                continue
            try:
                dec_i, sup_i = int(dec), int(float(sup) * 10 ** int(dec))
            except ValueError:
                info_box("Invalid input", ["Bad decimals or supply."], color=C.RED)
                continue
            if confirm(f"Register '{name}' ({sym}) supply={sup} dec={dec_i}?"):
                run_tx(b, lambda: b.rwa_register(name, sym, dec_i, sup_i),
                       "Register RWA asset")


def screen_faucet(b: Backend):
    while True:
        f = b.faucet_info()
        sub = (f"Gives {b.fmt(f.get('xel_per_claim'))} XEL + "
               f"{b.fmt(f.get('vlt_per_claim'))} VLT per distribution · pool "
               f"{b.fmt(f.get('xel_pool'))} XEL") if f else "Loading..."
        choice = menu("Testnet Faucet", [
            ("Distribute to my address", "me"),
            ("View faucet details", "info"),
            ("Back", None),
        ], subtitle=sub)
        if choice is None:
            return
        if choice == "me":
            if not b.address:
                info_box("No address", ["Configure your wallet first."], color=C.RED)
                continue
            if confirm(f"Distribute faucet funds to {short_addr(b.address)}?"):
                run_tx(b, lambda: b.faucet_distribute([b.address]), "Faucet distribution")
        elif choice == "info":
            lines = [
                f"XEL per claim:  {b.fmt(f.get('xel_per_claim'), 'XEL')}",
                f"VLT per claim:  {b.fmt(f.get('vlt_per_claim'), 'VLT')}",
                f"Cooldown:       {f.get('cooldown', '-')} blocks",
                f"Pool balances:  {b.fmt(f.get('xel_pool'))} XEL · "
                f"{b.fmt(f.get('vlt_pool'))} VLT",
            ]
            if f.get("my_last_claim_topo"):
                lines.append(f"Your last claim: topo {f['my_last_claim_topo']:,}")
            info_box("Faucet details", lines, color=C.CYAN)


# --- Governance screen ------------------------------------------------------

def screen_governance(b: Backend):
    while True:
        total = b.gov_total_staked()
        user  = b.gov_user_staked()
        count = b.gov_stakes_count()
        sub = (f"Total staked: {b.fmt(total, 'VLT') if total else '—'}  ·  "
               f"Your stake: {b.fmt(user, 'VLT') if user else '—'}  ·  "
               f"Positions: {count if count is not None else '—'}")
        opts = [("Stake VLT (voting power)", "stake"),
                ("Unstake a position", "unstake"),
                ("Claim rewards", "claim"),
                ("Info", "info"),
                ("Back", None)]
        choice = menu("Governance", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "stake":
            amt = ask_amount(b, b.vlt_asset, "VLT amount to stake:", "100")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            days = text_input("Lock period in days (default 7):").strip() or "7"
            if confirm(f"Stake {amt} VLT for {days} days?"):
                run_tx(b, lambda a=atomic, d=int(days): b.gov_stake(a, d),
                       "Governance stake")
        elif choice == "unstake":
            sid = text_input("Stake ID to unstake (number):").strip()
            if not sid:
                continue
            if confirm(f"Unstake position #{sid}? (reverts if still locked)"):
                run_tx(b, lambda i=int(sid): b.gov_unstake(i),
                       "Governance unstake")
        elif choice == "claim":
            if confirm("Claim governance rewards?"):
                run_tx(b, b.gov_claim_rewards, "Claim governance rewards")
        elif choice == "info":
            info_box("Governance", [
                f"Total staked:  {b.fmt(total, 'VLT') if total else '—'}",
                f"Your stake:    {b.fmt(user, 'VLT') if user else '—'}",
                f"Stake count:   {count if count is not None else '—'}",
                "",
                "Min lock: 7 days. Voting power = stake × (1 + lock boost).",
            ], color=C.CYAN)


# --- Loans screen (FlashLoan / PeerLoan / Syndicate) -----------------------

def screen_loans(b: Backend):
    while True:
        choice = menu("Loans", [
            ("Flash Loan", "flash"),
            ("Peer Loans", "peer"),
            ("Syndicate Pools", "syn"),
            ("Back", None),
        ])
        if choice is None:
            return
        if choice == "flash":
            screen_flashloan(b)
        elif choice == "peer":
            screen_peerloan(b)
        elif choice == "syn":
            screen_syndicate(b)


def screen_flashloan(b: Backend):
    while True:
        liq = b.flashloan_liquidity(b.xel_asset)
        earned = b.flashloan_earned()
        fee = b._read_int("FlashLoan", "get_fee_bps", [])
        sub = (f"Liquidity: {b.fmt(liq, 'XEL') if liq else '—'}  ·  "
               f"Earned: {b.fmt(earned, 'XEL') if earned else '—'}  ·  "
               f"Fee: {fee or '—'} bps")
        opts = [("Borrow (flash loan)", "borrow"),
                ("Fund liquidity", "fund"),
                ("Back", None)]
        choice = menu("Flash Loan", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "borrow":
            amt = ask_amount(b, b.xel_asset, "Amount to borrow (XEL):", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            cb = text_input("Callback contract hash (64 hex):").strip()
            if not cb or len(cb) != 64:
                info_box("Invalid", ["Need a 64-char hex callback hash."], color=C.RED)
                continue
            if confirm(f"Borrow {amt} XEL via FlashLoan?"):
                run_tx(b, lambda a=atomic, c=cb: b.flashloan_borrow(b.xel_asset, a, c),
                       "Flash loan borrow")
        elif choice == "fund":
            amt = ask_amount(b, b.xel_asset, "XEL amount to fund:", "5")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Fund FlashLoan with {amt} XEL?"):
                run_tx(b, lambda a=atomic: b.flashloan_fund(b.xel_asset, a),
                       "Fund FlashLoan")


def screen_peerloan(b: Backend):
    while True:
        count = b.pl_count()
        sub = f"Offers: {count if count is not None else '—'}"
        opts = [("Create offer (lend)", "create"),
                ("Accept offer (borrow)", "accept"),
                ("Repay a loan", "repay"),
                ("Cancel offer", "cancel"),
                ("Back", None)]
        choice = menu("Peer Loans", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "create":
            amt = ask_amount(b, b.xel_asset, "Amount to lend (XEL):", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            ibps = text_input("Interest bps (max 5000, e.g. 500 = 5%):").strip() or "500"
            dur = text_input("Duration in blocks (min 1440):").strip() or "1440"
            coll_amt = ask_amount(b, b.vlt_asset, "Collateral required (VLT):", "100")
            catom = parse_amount(coll_amt)
            if catom is None:
                continue
            if confirm(f"Lend {amt} XEL @ {ibps}bps for {dur} blocks?"):
                run_tx(b, lambda a=atomic, i=int(ibps), d=int(dur), ca=catom:
                       b.pl_create_offer(b.xel_asset, a, i, d, b.vlt_asset, ca),
                       "Create loan offer")
        elif choice == "accept":
            oid = text_input("Offer ID to accept:").strip()
            if not oid:
                continue
            coll = ask_amount(b, b.vlt_asset, "Collateral VLT to attach:", "100")
            catom = parse_amount(coll)
            if catom is None:
                continue
            if confirm(f"Accept offer #{oid} with {coll} VLT collateral?"):
                run_tx(b, lambda i=int(oid), c=catom:
                       b.pl_accept_offer(i, b.vlt_asset, c),
                       "Accept loan offer")
        elif choice == "repay":
            oid = text_input("Offer ID to repay:").strip()
            if not oid:
                continue
            amt = ask_amount(b, b.xel_asset, "Repay amount (XEL, include interest):", "1.1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Repay offer #{oid} with {amt} XEL?"):
                run_tx(b, lambda i=int(oid), a=atomic: b.pl_repay(i, a),
                       "Repay loan")
        elif choice == "cancel":
            oid = text_input("Offer ID to cancel:").strip()
            if not oid:
                continue
            if confirm(f"Cancel offer #{oid}?"):
                run_tx(b, lambda i=int(oid): b.pl_cancel_offer(i),
                       "Cancel loan offer")


def screen_syndicate(b: Backend):
    while True:
        count = b.sp_count()
        sub = f"Pools: {count if count is not None else '—'}"
        opts = [("Create pool", "create"),
                ("Supply to pool", "supply"),
                ("Activate pool (borrower)", "activate"),
                ("Repay pool", "repay"),
                ("Claim from pool", "claim"),
                ("Back", None)]
        choice = menu("Syndicate Pools", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "create":
            amt = ask_amount(b, b.xel_asset, "Total pool size (XEL):", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            ibps = text_input("Interest bps (max 5000):").strip() or "500"
            dur = text_input("Duration in blocks (min 1440):").strip() or "1440"
            coll = ask_amount(b, b.vlt_asset, "Collateral required (VLT):", "100")
            catom = parse_amount(coll)
            if catom is None:
                continue
            if confirm(f"Create syndicate pool: {amt} XEL @ {ibps}bps, {coll} VLT collateral?"):
                run_tx(b, lambda a=atomic, i=int(ibps), d=int(dur), ca=catom:
                       b.sp_create_pool(b.xel_asset, a, i, d, b.vlt_asset, ca),
                       "Create syndicate pool")
        elif choice == "supply":
            pid = text_input("Pool ID to supply to:").strip()
            if not pid:
                continue
            amt = ask_amount(b, b.xel_asset, "XEL to supply:", "0.5")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Supply {amt} XEL to pool #{pid}?"):
                run_tx(b, lambda i=int(pid), a=atomic: b.sp_supply(i, a),
                       "Supply to pool")
        elif choice == "activate":
            pid = text_input("Pool ID to activate:").strip()
            if not pid:
                continue
            if confirm(f"Activate pool #{pid}? (requires full funding + collateral attached)"):
                run_tx(b, lambda i=int(pid): b.sp_activate(i),
                       "Activate pool")
        elif choice == "repay":
            pid = text_input("Pool ID to repay:").strip()
            if not pid:
                continue
            amt = ask_amount(b, b.xel_asset, "XEL to repay:", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            if confirm(f"Repay {amt} XEL to pool #{pid}?"):
                run_tx(b, lambda i=int(pid), a=atomic: b.sp_repay(i, a),
                       "Repay pool")
        elif choice == "claim":
            pid = text_input("Pool ID to claim from:").strip()
            if not pid:
                continue
            if confirm(f"Claim from pool #{pid}?"):
                run_tx(b, lambda i=int(pid): b.sp_claim(i),
                       "Claim from pool")


# --- Auctions screen --------------------------------------------------------

def screen_auctions(b: Backend):
    while True:
        count = b.au_count()
        sub = f"Auctions: {count if count is not None else '—'}"
        opts = [("Create auction (seller)", "create"),
                ("Commit bid (buyer)", "commit"),
                ("Reveal bid (buyer)", "reveal"),
                ("Settle / declare winner", "settle"),
                ("Claim asset / proceeds", "claim"),
                ("Back", None)]
        choice = menu("Sealed-Bid Auctions", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "create":
            amt = ask_amount(b, b.vlt_asset, "VLT amount to auction:", "10")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            minb = ask_amount(b, b.xel_asset, "Minimum bid (XEL):", "0.1")
            minb_atomic = parse_amount(minb)
            if minb_atomic is None:
                continue
            cdur = text_input("Commit duration blocks (min 1440):").strip() or "1440"
            rdur = text_input("Reveal duration blocks (min 1440):").strip() or "1440"
            if confirm(f"Auction {amt} VLT, min bid {minb} XEL?"):
                run_tx(b, lambda a=atomic, m=minb_atomic, c=int(cdur), r=int(rdur):
                       b.au_create(b.vlt_asset, a, b.xel_asset, m, c, r),
                       "Create auction")
        elif choice == "commit":
            aid = text_input("Auction ID:").strip()
            if not aid:
                continue
            bh = text_input("Bid hash (64 hex, blake3 of 'amount|nonce|addr'):").strip()
            if not bh or len(bh) != 64:
                info_box("Invalid", ["Need 64-char hex hash."], color=C.RED)
                continue
            if confirm(f"Commit bid on auction #{aid}?"):
                run_tx(b, lambda i=int(aid), h=bh: b.au_commit(i, h),
                       "Commit bid")
        elif choice == "reveal":
            aid = text_input("Auction ID:").strip()
            if not aid:
                continue
            amt = ask_amount(b, b.xel_asset, "Bid amount (XEL):", "1")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            nonce = text_input("Nonce (integer used in hash):").strip() or "0"
            if confirm(f"Reveal bid {amt} XEL on auction #{aid}?"):
                run_tx(b, lambda i=int(aid), a=atomic, n=int(nonce):
                       b.au_reveal(i, a, n),
                       "Reveal bid")
        elif choice == "settle":
            aid = text_input("Auction ID:").strip()
            if not aid:
                continue
            if confirm(f"Settle auction #{aid}?"):
                run_tx(b, lambda i=int(aid): b.au_settle(i),
                       "Settle auction")
        elif choice == "claim":
            aid = text_input("Auction ID:").strip()
            if not aid:
                continue
            c = text_input("Claim what? (asset/proceeds):").strip().lower()
            if c == "asset":
                run_tx(b, lambda i=int(aid): b.au_claim_asset(i),
                       "Claim auction asset")
            elif c == "proceeds":
                run_tx(b, lambda i=int(aid): b.au_claim_proceeds(i),
                       "Claim auction proceeds")


# --- VaultChat screen -------------------------------------------------------

def screen_chat(b: Backend):
    while True:
        gc = b.chat_groups_count()
        sub = f"Groups: {gc if gc is not None else '—'}"
        opts = [("Register session", "register"),
                ("Send DM", "dm"),
                ("Create group", "cgrp"),
                ("Add group member", "amem"),
                ("Send group message", "gmsg"),
                ("Anchor messages", "anchor"),
                ("Relayer: bond + register", "relayer"),
                ("Relayer: set fee", "fee"),
                ("Relayer: claim fees", "claim"),
                ("Back", None)]
        choice = menu("Encrypted Chat (VaultChat)", opts, subtitle=sub)
        if choice is None:
            return
        if choice == "register":
            ek = text_input("Encrypted session key (64 hex):").strip()
            if not ek or len(ek) != 64:
                info_box("Invalid", ["Need 64-char hex key."], color=C.RED)
                continue
            if confirm("Register chat session?"):
                run_tx(b, lambda k=ek: b.chat_register(k), "Register session")
        elif choice == "dm":
            dest = text_input("Recipient address (xet:...):").strip()
            if not dest.startswith("xet:"):
                continue
            msg = text_input("Message (hex-encoded encrypted payload):").strip()
            if not msg:
                continue
            if confirm(f"Send DM to {short_addr(dest)}?"):
                run_tx(b, lambda d=dest, m=msg: b.chat_send_dm(d, m),
                       "Send DM")
        elif choice == "cgrp":
            ek = text_input("Group encrypted key (64 hex):").strip()
            if not ek or len(ek) != 64:
                info_box("Invalid", ["Need 64-char hex key."], color=C.RED)
                continue
            if confirm("Create group chat?"):
                run_tx(b, lambda k=ek: b.chat_create_group(k), "Create group")
        elif choice == "amem":
            gid = text_input("Group ID:").strip()
            if not gid:
                continue
            addr = text_input("Member address (xet:...):").strip()
            if not addr.startswith("xet:"):
                continue
            ek = text_input("Encrypted key for member (64 hex):").strip()
            if not ek or len(ek) != 64:
                info_box("Invalid", ["Need 64-char hex key."], color=C.RED)
                continue
            if confirm(f"Add {short_addr(addr)} to group #{gid}?"):
                run_tx(b, lambda g=int(gid), a=addr, k=ek:
                       b.chat_add_member(g, a, k),
                       "Add group member")
        elif choice == "gmsg":
            gid = text_input("Group ID:").strip()
            if not gid:
                continue
            msg = text_input("Message (hex-encoded):").strip()
            if not msg:
                continue
            if confirm(f"Send message to group #{gid}?"):
                run_tx(b, lambda g=int(gid), m=msg: b.chat_group_msg(g, m),
                       "Send group message")
        elif choice == "anchor":
            root = text_input("Merkle root (64 hex):").strip()
            if not root or len(root) != 64:
                info_box("Invalid", ["Need 64-char hex root."], color=C.RED)
                continue
            count = text_input("Message count:").strip() or "1"
            if confirm(f"Anchor {count} messages?"):
                run_tx(b, lambda r=root, c=int(count): b.chat_anchor(r, c),
                       "Anchor messages")
        elif choice == "relayer":
            amt = ask_amount(b, b.vlt_asset, "VLT bond (min 50):", "50")
            atomic = parse_amount(amt)
            if atomic is None:
                continue
            ep = text_input("Relayer endpoint (url):").strip() or "http://localhost"
            if confirm(f"Bond {amt} VLT + register as relayer?"):
                run_tx(b, lambda a=atomic: b.chat_stake_bond(a), "Stake bond")
                time.sleep(4)
                run_tx(b, lambda: b.chat_register_relayer(ep, 1000000, 100),
                       "Register relayer")
        elif choice == "fee":
            tok = text_input("Token (0=XEL, 1=VLT):").strip() or "0"
            fee = text_input("Fee in atomic units (e.g. 1000000 = 0.01):").strip()
            if not fee:
                continue
            if confirm(f"Set relayer fee: {fee} for token {tok}?"):
                run_tx(b, lambda t=int(tok), f=int(fee): b.chat_set_fee(t, f),
                       "Set relayer fee")
        elif choice == "claim":
            if confirm("Claim relayer fees?"):
                run_tx(b, b.chat_claim_fees, "Claim relayer fees")


# --- Miner tools screen -----------------------------------------------------
    m = b.my_miner()
    stats = b.miner_stats()
    lines = []
    if m and isinstance(m, list) and len(m) >= 15:
        stake = m[3]
        hb_topo = m[6]
        rewards = m[7]
        rep = m[9]
        active = bool(m[14])
        age = max(0, b.topo() - hb_topo) if hb_topo else -1
        lines.append(f"Registered: {'yes' if active else 'no'}   Reputation: {rep}")
        lines.append(f"Stake: {b.fmt(stake, 'VLT')}   Rewards earned: {b.fmt(rewards, 'VLT')}")
        if age >= 0:
            lines.append(f"Last heartbeat: {age} blocks ago")
    else:
        lines.append(f"{C.DIM}This address has no miner profile yet.{C.RESET}")
        lines.append("")
        lines.append("Run xvault-miner to register and start earning.")
    lines.append("")
    lines.append(f"Network staked: {b.fmt(stats.get('total_staked'), 'VLT')}")
    info_box("Miner status", lines, color=C.CYAN)

    import onboarding
    miner_pid = onboarding.miner_running()
    mopts = []
    if miner_pid:
        mopts.append((f"Stop built-in miner (pid {miner_pid})", "stop"))
    else:
        mopts.append(("Start built-in miner (auto-configured)", "start"))
        threads = cfg_miner_threads()
        mopts.append((f"Set thread count (currently {threads})", "threads"))
    mopts += [
        ("Send heartbeat now", "hb"),
        ("Increase miner stake", "stake"),
        ("Back", None),
    ]
    choice = menu("Miner tools", mopts)
    if choice == "hb":
        run_tx(b, lambda: b.miner_heartbeat(), "Heartbeat")
    elif choice == "stake":
        amt = ask_amount(b, b.vlt_asset, "VLT amount to add to miner stake:", "100")
        atomic = parse_amount(amt)
        if atomic is None:
            return
        if confirm(f"Stake {amt} VLT more?"):
            run_tx(b, lambda: b.miner_increase_stake(atomic), "Stake increase")
    elif choice == "start":
        from pathlib import Path as _P
        cfg_obj = _load_cfg()
        ok, msg = onboarding.start_miner(cfg_obj)
        info_box("Miner", [msg], color=C.GREEN if ok else C.RED)
    elif choice == "stop":
        ok, msg = onboarding.stop_miner()
        info_box("Miner", [msg], color=C.GREEN if ok else C.RED)
    elif choice == "threads":
        from pathlib import Path as _P
        cfg_obj = _load_cfg()
        t = text_input("Number of mining threads:",
                       default=str(cfg_obj.get("miner_threads") or 4))
        if t.isdigit() and 1 <= int(t) <= 64:
            cfg_obj.data["miner_threads"] = t
            cfg_obj.save()
            info_box("Saved", [f"{t} thread(s) — applies at next start."],
                     color=C.GREEN)


def _load_cfg():
    """Fresh Config instance (screens receive only the Backend)."""
    return Config()


def cfg_miner_threads() -> str:
    try:
        return str(json.loads(CONFIG_PATH.read_text()).get(
            "miner_threads") or (max(1, (__import__("os").cpu_count() or 2) - 1)))
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Settings / wallet setup
# ---------------------------------------------------------------------------

def run_onboarding(cfg: Config) -> bool:
    """Delegate to the shared onboarding wizard (English, seed-safe)."""
    import onboarding
    ok = onboarding.run_onboarding(cfg)
    cfg.load()
    return ok


def screen_settings(b: Backend, cfg: Config):
    while True:
        bundle_path = None
        for cand in (Path(__file__).parent.parent / "network" / "testnet.json",):
            if cand.exists():
                bundle_path = cand
                break
        ver = "?"
        n_contracts = "?"
        if bundle_path:
            try:
                d = json.loads(bundle_path.read_text())
                ver = d.get("version", "?")
                n_contracts = len(d.get("contracts", {}))
            except Exception:
                pass
        choice = menu("Settings", [
            ("Edit RPC endpoints", "rpc"),
            ("Reset local configuration", "reset"),
            ("Back", None),
        ], subtitle=f"Contract bundle v{ver} ({n_contracts} contracts)")
        if choice is None:
            return
        if choice == "rpc":
            rpc = text_input("Daemon JSON-RPC URL:", default=cfg.get("rpc_url")).strip()
            wal = text_input("Wallet JSON-RPC URL:", default=cfg.get("wallet_url")).strip()
            cfg.data["rpc_url"] = rpc
            cfg.data["wallet_url"] = wal
            cfg.save()
            info_box("Saved", ["RPC endpoints updated."], color=C.GREEN)
        elif choice == "reset":
            if confirm("Delete local configuration? (wallet files are kept)",
                       default_yes=False):
                CONFIG_PATH.unlink(missing_ok=True)
                cfg.__init__()
                info_box("Done", ["Configuration reset."], color=C.GREEN)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ensure_wallet_alive(cfg: Config) -> bool:
    """Auto-relaunch the managed wallet RPC when it is configured but down.

    This is what makes remote-node mode 'zero unavailable': the chain data
    comes from the public node and the local wallet process is (re)started
    transparently in the background.
    """
    import onboarding
    binary = cfg.get("wallet_binary")
    wpath = cfg.get("wallet_path")
    password = cfg.get("wallet_password")
    if not (binary and wpath and password and Path(binary).exists()):
        return False
    port = int(cfg.get("wallet_rpc_port") or 18082)
    url = f"http://127.0.0.1:{port}"
    try:
        onboarding.rpc_call(url, "get_address",
                            auth=(cfg.get("wallet_user", "wallet"),
                                  cfg.get("wallet_pass", "testpass")), timeout=3)
        return True  # already up
    except Exception:
        pass
    try:
        network = cfg.get("wallet_network", "testnet")
        daemon = cfg.get("rpc_url") or onboarding.PUBLIC_NODE
        onboarding.launch_wallet(binary, network, daemon, password,
                                 Path(wpath), port)
        addr = onboarding.wait_for_wallet(url, ("wallet",
                                                cfg.get("wallet_pass", "testpass")),
                                          timeout_s=180)
        return bool(addr)
    except Exception:
        return False


def main():
    cfg = Config()
    first_run = not CONFIG_PATH.exists()

    while True:
        # transparently bring the managed wallet back before building Backend
        if not first_run and cfg.get("wallet_binary"):
            ensure_wallet_alive(cfg)

        b = Backend(cfg.data)
        online = b.topo() > 0
        wallet_ok = bool(b.wallet)
        if wallet_ok:
            try:
                b.wallet.balance()
            except Exception:
                wallet_ok = False

        title_lines = [BANNER]
        clear()
        print(BANNER)
        print(f"{C.GRAY}{'─' * 66}{C.RESET}")
        net = f"{C.GREEN}● daemon online{C.RESET}" if online else \
              f"{C.RED}○ daemon offline{C.RESET}"
        wal = f"{C.GREEN}● wallet open{C.RESET}" if wallet_ok else \
              f"{C.YELLOW}○ no wallet{C.RESET}"
        addr = short_addr(cfg.get("miner_address")) if cfg.get("miner_address") else short_addr(b.address)
        print(f"  {net}   {wal}   Address: {addr}")
        print()

        opts = [
            ("Dashboard (live)", lambda: screen_dashboard(b)),
            ("Vault — collateralized xUSD", lambda: screen_vault(b)),
            ("Swap (xUSD / AMM)", lambda: screen_swap(b)),
            ("Savings", lambda: screen_savings(b)),
            ("Privacy Mixer", lambda: screen_privacy(b)),
            ("Governance", lambda: screen_governance(b)),
            ("Loans (Flash / Peer / Syndicate)", lambda: screen_loans(b)),
            ("Sealed-Bid Auctions", lambda: screen_auctions(b)),
            ("Encrypted Chat", lambda: screen_chat(b)),
            ("Treasury (multisig)", lambda: screen_treasury(b)),
            ("RWA Assets", lambda: screen_rwa(b)),
            ("Miner tools", lambda: screen_miner_tools(b)),
            ("Faucet", lambda: screen_faucet(b)),
        ]
        opts.append(("Settings", ("settings",)))
        if first_run or not wallet_ok:
            opts.insert(0, ("Set up wallet / node", ("setup",)))
        opts.append(("Quit", ("quit",)))

        choice = menu("", opts)
        if choice is None or choice == ("quit",):
            clear()
            return
        if choice == ("setup",):
            first_run = not run_onboarding(cfg)
            continue
        if choice == ("settings",):
            screen_settings(b, cfg)
            continue
        # normal screens
        try:
            choice()
        except Exception as e:
            info_box("Error", [str(e)[:200]], color=C.RED)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear()
