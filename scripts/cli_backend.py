#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — CLI chain backend (live on-chain layer)
 ============================================================================
 Real interactions with the deployed contracts, built on the same proven
 primitives used by the deployment/test tooling (protocol.py):

   - wallet ops  : build_transaction / invoke_contract (ValueCell params)
   - daemon reads: get_contract_data (string keys), get_contract_balance

 Contract hashes & asset hashes come from the network bundle
 (network/testnet.json) so the CLI always targets the current deployment.
 Entry ids are the COMPILED chunk indices (verified on-chain).

 Only flows verified end-to-end on-chain are exposed as transactions.
 Everything else is shown as "coming soon" by the CLI.
 ============================================================================
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))
from protocol import (
    WalletClient, DaemonClient, RPCError,
    val_u64, val_u128, val_u8, val_str, val_hash, val_addr, val_bytes,
    parse_cell,
)

ZERO_HASH = "0" * 64

# ---------------------------------------------------------------------------
# Network bundle loading (contracts + assets)
# ---------------------------------------------------------------------------

def _bundle_candidates() -> list:
    here = Path(__file__).parent
    return [
        here.parent / "network" / "testnet.json",      # installed layout
        here.parent.parent / "network" / "testnet.json",
        here / "network_testnet.json",
    ]


def load_bundle() -> dict:
    for c in _bundle_candidates():
        if c.exists():
            try:
                return json.loads(c.read_text())
            except Exception:
                pass
    return {}


# Fallbacks (current testnet deployment) if the bundle file is missing.
# Registry `cur_<Name>` is always preferred over these static tables.
_FALLBACK = {
    "contracts": {
        "AirdropTracker": "ef896baa1c88d64462500b48c8a6d0fb47b92b46718d1949c79d8d0268769dca",
        "AssetVault": "d16f7671f3e5399e1da826f9c4743f6fd5161e54048c945da6bea25d1032ff64",
        "ComplianceModule": "1c0f143207c24d3b3e7fd04000cd1425e498505171de45ca980238e9f71c7f4a",
        "ContractRegistry": "19161543b9e5aef00c5a3e226058b946d847c78941f0c89e9b996c6332204970",
        "FaucetContract": "0169707c19522269e8126edf36066e2c83c384e8c31f8072667f7cfad06631ec",
        "FeeDistributor": "c7e23f4cbe34ecb411811e7edbdbd55e428f2884b36d067be94ca4ca425491f7",
        "FlashCallback": "a84fc6d305b4ed1a6e15c310461799172272ec1cabf209316e724c3ede420f40",
        "FlashLoan": "f8505eb95c5bb070e4f2a7f2d80826e13d140d2ee03b6bfdfaf1b7772c4be9f4",
        "FounderVesting": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "FounderVesting10y": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "FounderVesting4y": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "GovernanceVault": "52cb2f100984319c7f41bbec03fb3e7679279eafdd4abb44ff5d8fdd7631cf97",
        "Governor": "608eec92282bcba466e88d7e70d616be5653e9a120997866d738838e783862c3",
        "GuardianMultisig": "9792a5894877a5982c9efdfb91f94c1536fe5f21c017a56c59691776413e4929",
        "InterestRateModel": "e9f716b07628fb8793adf3e20142348082a5021d671f316dad1e02cfb70f9c6d",
        "LendingMarket": "cb8f489382368b2f1b27bffcba346ede50aa180ebefac89ac444995bc95255bc",
        "MinerDelegation": "5eb34079fd84ee3626e410c0e9cbf5d568c76cabeaf36c0d00b5e21693033685",
        "MinerPool": "de744e0ccf45252070eb8fe83d0d16d36736ab7af1014a69405f358fb63c439b",
        "OracleGovernance": "bab86ca4a01c3250ce90b5c5d569b87ab221a212321848e104eb89500c28c953",
        "PSM": "977ddf73305dd21c29ffbe69dc2bdb29a12a62f4ff8bbc3140cafd4b51d5c2e1",
        "Payroll": "44ce12fb3d143f360c84664fe4849f01fb31ce5b45aebda38b037c70b4079b30",
        "PeerLoan": "ec1ed4f280fef7cd7b13cb0231be12cfb53ddc57b38eaa822e00497221d82d36",
        "PrivacyMixer": "d54cc19be3d16a86a3849be4389e44a9c123ebb0042a88e94f4e91893f940ab8",
        "RevenueShare": "49c363dae4d32473d6d3c26ce0482cf735f7d656c665094002c1d21a6978c94b",
        "SavingsRate": "139caff55ca74911eb0c2631e5aab623a53ee56c7b24143328ecef3a610a9738",
        "SealedBidAuction": "ac0c5a4e22a8348d3e98ff6183fdab23117f06f4a154098c1d7c84b24c3097f5",
        "StakedOracle": "e89bc25043c320fdac9c2030bc99e4b5bd94c9e0043132d10f66cd93576fa515",
        "SyndicatePool": "5980cbd860081e613d32fd86d1c474fd798c8a7da262177078ad2eeb8dcb5cb0",
        "Timelock": "b925d8e30ccd7bcffdc1376a6aecd8daaaa71603a3d0a4c9413d9e4a8ed11082",
        "TreasuryVault": "01d3851249e13354465766306e65be15497a9a9df6f46e35fe417879c4a5ab84",
        "VLTToken": "020f228fbd61e3a6cd2d570083e14c02f7073f293c79ee4059359b896e217d84",
        "VaultChat": "5904a314ec3dfda55654647ea03c8b6d149102505f076006bc1cd36f7cc3e80b",
        "VaultEngineV3": "844cab735a8156f55c3055c2ff56a6824ad6d55b32f7dfb866655bde2bfa2054",
        "VaultSwapV2": "5defc37154200f1cabb5b5fa43510565ab791e34b20f2cf4132ec7d9ac4e2041",
        "XelisVaultMiner": "6c70647e233dd634aa05cd6bdca06b521947c4c682d7decac0700d8a79d4b024",
        "xUSD": "4836190ca2f2278cfc3e8ad8c7e05bbd0070de253c64615f6eea2c19885063a1",
    },
    "vlt_asset": "3f1f9a3c0a90a0a548670a069e8edad5c0c20914b20b289426b2857c6715f58f",
    "xusd_asset": "be39794c4a32f231d410c8be3a4d9e80455c667d902c5edf8527dea52533356e",
}

# ContractRegistry names for live resolution (registry is authoritative).
_REGISTRY_NAMES = {
    "staked_oracle": "StakedOracle",
    "miner": "XelisVaultMiner",
    "vlt_token": "VLTToken",
    "xusd": "xUSD",
    "vault_engine": "VaultEngine",
    "vault_swap": "VaultSwap",
    "psm": "PSM",
    "savings_rate": "SavingsRate",
    "mixer": "PrivacyMixer",
    "treasury_vault": "TreasuryVault",
    "asset_vault": "AssetVault",
    "faucet": "FaucetContract",
}

# ---------------------------------------------------------------------------
# Compiled entry-chunk ids (source of truth: docs/entry_chunk_ids.json)
# ---------------------------------------------------------------------------

CHUNKS = {
    "PSM":            {"mint": 8, "redeem": 9},
    "VaultEngineV3":  {"deposit": 17, "borrow": 18, "repay": 19, "withdraw": 20},
    "VaultSwapV2":    {"create_pool": 16, "add_liquidity": 17, "swap": 18},
    "SavingsRate":    {"deposit": 8, "withdraw": 9, "claim_interest": 10},
    "PrivacyMixer":   {"deposit": 5, "execute_mix": 6, "execute_refund": 7},
    "TreasuryVault":  {"propose": 9, "confirm": 10, "revoke": 11, "execute": 12, "deposit": 16},
    "AssetVault":     {"mint": 5, "transfer_asset": 6},
    "StakedOracle":   {"submit_price": 16, "aggregate_now": 17},
    "XelisVaultMiner": {"register_miner": 15, "enable_service": 16, "increase_stake": 18,
                        "submit_heartbeat": 21},
}

DECIMALS = 8


class OpResult:
    """Outcome of a transaction op."""
    def __init__(self, ok: bool, tx: str = "", reason: str = ""):
        self.ok = ok
        self.tx = tx
        self.reason = reason

    def __bool__(self):
        return self.ok


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class Backend:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        bundle = load_bundle() or _FALLBACK
        contracts = dict(_FALLBACK["contracts"])
        contracts.update({k: v for k, v in bundle.get("contracts", {}).items() if v})
        # accept both naming styles from older bundles
        alias = {"oracle": "staked_oracle", "vault_engine_v3": "vault_engine",
                 "psm_contract": "psm"}
        for a, b in alias.items():
            if a in contracts and b not in contracts:
                contracts[b] = contracts[a]
        self.contracts = contracts
        self.vlt_asset = bundle.get("vlt_asset") or _FALLBACK["vlt_asset"]
        self.xusd_asset = bundle.get("xusd_asset") or _FALLBACK["xusd_asset"]
        self.xel_asset = ZERO_HASH
        self.feed_id = int(bundle.get("oracle_feed_id", 0))

        daemon_url = cfg.get("rpc_url") or "http://127.0.0.1:18081"
        wallet_url = cfg.get("wallet_url") or ""
        if daemon_url and not daemon_url.endswith("/json_rpc"):
            daemon_url += "/json_rpc"
        if wallet_url and not wallet_url.endswith("/json_rpc"):
            wallet_url += "/json_rpc"
        self.daemon = DaemonClient(daemon_url)
        auth = (cfg.get("wallet_user") or "wallet", cfg.get("wallet_pass") or "testpass")
        self.wallet = WalletClient(wallet_url, auth) if wallet_url else None
        self._resolve_via_registry()

    def _resolve_via_registry(self):
        """ContractRegistry cur_<Name> overrides static tables (authoritative)."""
        reg = self.contracts.get("registry")
        if not reg:
            return
        for key, name in _REGISTRY_NAMES.items():
            try:
                h = self.daemon.read_key(reg, f"cur_{name}")
            except Exception:
                continue
            if h and isinstance(h, str) and len(h) == 64:
                self.contracts[key] = h

    # -- helpers ----------------------------------------------------------

    @property
    def address(self) -> str:
        return self.cfg.get("miner_address") or ""

    @property
    def has_wallet(self) -> bool:
        return bool(self.wallet)

    def C(self, key: str) -> str:
        return self.contracts.get(key, "")

    def topo(self) -> int:
        try:
            return self.daemon.topoheight()
        except Exception:
            return 0

    def balance(self, asset: str = ZERO_HASH) -> Optional[int]:
        if not self.wallet:
            return None
        try:
            return self.wallet.balance(asset)
        except Exception:
            return None

    def balances(self) -> dict:
        out = {}
        for name, asset in (("XEL", self.xel_asset), ("VLT", self.vlt_asset),
                            ("xUSD", self.xusd_asset)):
            b = self.balance(asset)
            out[name] = b
        return out

    def fmt(self, amount: Optional[int], suffix: str = "") -> str:
        if amount is None:
            return "--"
        v = amount / (10 ** DECIMALS)
        s = f"{v:,.4f}" if v >= 1 else f"{v:.8f}".rstrip("0").rstrip(".") or "0"
        return f"{s}{(' ' + suffix) if suffix else ''}"

    def price(self):
        """(price_raw, feed_topo, stale) from StakedOracle storage."""
        so = self.C("staked_oracle")
        if not so:
            return None
        fg = self.daemon.read_key(so, f"fg_{self.feed_id}")
        if isinstance(fg, list) and len(fg) >= 2:
            price, feed_topo = int(fg[0]), int(fg[1])
            hsb = self.daemon.read_key(so, "hsb")
            hard_stale = int(hsb) if isinstance(hsb, int) else 500
            stale = (self.topo() - feed_topo) > hard_stale
            return price, feed_topo, stale
        return None

    def price_usd(self) -> Optional[float]:
        p = self.price()
        return (p[0] / 10 ** DECIMALS) if p else None

    # -- protocol stats -----------------------------------------------------

    def miner_stats(self) -> dict:
        mn = self.C("miner")
        out = {}
        if not mn:
            return out
        ts = self.daemon.read_key(mn, "ts")
        tb = self.daemon.read_key(mn, "tb")
        dist = self.daemon.read_key(mn, "dist")
        ms = self.daemon.read_key(mn, "ms")
        if isinstance(ts, int): out["total_staked"] = ts
        if isinstance(tb, int): out["budget"] = tb
        if isinstance(dist, int): out["distributed"] = dist
        if isinstance(ms, int): out["min_stake"] = ms
        return out

    def my_miner(self) -> Optional[list]:
        mn = self.C("miner")
        addr = self.address
        if not mn or not addr:
            return None
        m = self.daemon.read_key(mn, f"miner_{addr}")
        return m if isinstance(m, list) else None

    def psm_reserves(self) -> dict:
        psm = self.C("psm")
        out = {}
        if not psm:
            return out
        try:
            out["xel"] = self.daemon.get_contract_balance(psm, self.xel_asset)
        except Exception:
            pass
        try:
            out["xusd"] = self.daemon.get_contract_balance(psm, self.xusd_asset)
        except Exception:
            pass
        return out

    def amm_pools(self) -> list:
        vs = self.C("vault_swap")
        if not vs:
            return []
        count = self.daemon.read_key(vs, "pc")
        pools = []
        n = int(count) if isinstance(count, int) else 0
        pairs = [(self.xel_asset, self.xusd_asset), (self.xel_asset, self.vlt_asset),
                 (self.vlt_asset, self.xusd_asset)]
        for a, b in pairs:
            lo, hi = (a, b) if a < b else (b, a)
            pool = self.daemon.read_key(vs, f"p_{lo}_{hi}")
            if isinstance(pool, list) and len(pool) >= 6:
                pools.append({"a": str(pool[0]), "b": str(pool[1]),
                              "reserve_a": int(pool[2]), "reserve_b": int(pool[3])})
        return pools

    def my_vaults(self) -> list:
        ve = self.C("vault_engine")
        addr = self.address
        if not ve or not addr:
            return []
        n = self.daemon.read_key(ve, "n")
        total = int(n) if isinstance(n, int) else 0
        vaults = []
        for i in range(1, min(total, 200) + 1):
            snap = self.daemon.read_key(ve, f"v_{i}")
            if isinstance(snap, list) and len(snap) >= 10:
                owner = str(snap[0])
                if owner == addr:
                    vaults.append({
                        "id": i,
                        "collateral_asset": str(snap[1]),
                        "collateral": int(snap[2]),
                        "borrow_amount": int(snap[4]),
                        "last_update_topo": int(snap[6]),
                        "liquidated": bool(snap[7]),
                    })
        return vaults

    def health_factor(self, v: dict) -> Optional[float]:
        """Approximate HF: collateral value / debt value (xUSD ≈ $1)."""
        price = self.price_usd()
        if not price or not v:
            return None
        col_val = v["collateral"] / 10 ** DECIMALS * price
        debt_val = v["borrow_amount"] / 10 ** DECIMALS
        if debt_val == 0:
            return float("inf")
        return col_val / debt_val

    MIN_CR = 2.0  # 200% minimum collateral ratio

    def savings_stats(self) -> dict:
        sr = self.C("savings_rate")
        out = {}
        if not sr:
            return out
        td = self.daemon.read_key(sr, "td")
        ab = self.daemon.read_key(sr, "ab")
        if isinstance(td, int):
            out["total_deposits"] = td
        if isinstance(ab, int):
            out["apy_bps"] = ab
        try:
            out["contract_xusd"] = self.daemon.get_contract_balance(sr, self.xusd_asset)
        except Exception:
            pass
        return out

    def mixer_stats(self) -> dict:
        mx = self.C("mixer")
        out = {}
        if not mx:
            return out
        pc = self.daemon.read_key(mx, "pc")
        tmc = self.daemon.read_key(mx, "tmc")
        tm = self.daemon.read_key(mx, f"tm_{self.xel_asset}")
        if isinstance(pc, int): out["pending"] = pc
        if isinstance(tmc, int): out["total_mixes"] = tmc
        if isinstance(tm, int): out["total_mixed"] = tm
        return out

    def treasury_info(self) -> dict:
        tv = self.C("treasury_vault")
        out = {}
        if not tv:
            return out
        sc = self.daemon.read_key(tv, "sc")
        q = self.daemon.read_key(tv, "q")
        pc = self.daemon.read_key(tv, "pc")
        if isinstance(sc, int): out["signers"] = sc
        if isinstance(q, int): out["quorum"] = q
        if isinstance(pc, int): out["proposals"] = pc
        try:
            out["xel"] = self.daemon.get_contract_balance(tv, self.xel_asset)
            out["xusd"] = self.daemon.get_contract_balance(tv, self.xusd_asset)
        except Exception:
            pass
        return out

    def rwa_asset_info(self) -> dict:
        av = self.C("asset_vault")
        out = {}
        if not av:
            return out
        ah = self.daemon.read_key(av, "ah")
        if ah:
            out["asset_hash"] = str(ah)
            info = self.daemon.read_key(av, "ai")
            if isinstance(info, list):
                out["info"] = info
            try:
                out["supply"] = None  # native asset supply needs asset read
            except Exception:
                pass
        return out

    # -- faucet --------------------------------------------------------------

    def faucet_info(self) -> dict:
        fa = self.C("faucet")
        out = {}
        if not fa:
            return out
        xa = self.daemon.read_key(fa, "xa")
        va = self.daemon.read_key(fa, "va2")
        cd = self.daemon.read_key(fa, "cd")
        if isinstance(xa, int): out["xel_per_claim"] = xa
        if isinstance(va, int): out["vlt_per_claim"] = va
        if isinstance(cd, int): out["cooldown"] = cd
        try:
            out["xel_pool"] = self.daemon.get_contract_balance(fa, self.xel_asset)
            out["vlt_pool"] = self.daemon.get_contract_balance(fa, self.vlt_asset)
        except Exception:
            pass
        last = self.daemon.read_key(fa, f"ulc_{self.address}") if self.address else None
        if isinstance(last, int):
            out["my_last_claim_topo"] = last
        return out

    # =========================================================================
    # Transaction ops — only flows verified end-to-end on-chain
    # =========================================================================

    def _invoke(self, contract_key: str, fn: str, params=None, deposits=None,
                max_gas: int = 10_000_000) -> OpResult:
        contract = self.C(contract_key)
        chunk = CHUNKS.get(contract_key, {}).get(fn)
        if not contract or chunk is None:
            return OpResult(False, reason=f"{contract_key}.{fn} unavailable")
        if not self.wallet:
            return OpResult(False, reason="No wallet connected (read-only mode)")
        try:
            tx = self.wallet.invoke(contract, chunk, params=params,
                                    deposits=deposits or {}, max_gas=max_gas)
        except RPCError as e:
            msg = str(e)
            if "Module error: " in msg:
                msg = msg.split("Module error: ", 1)[1].split(":")[0].strip()
            elif "Server returned error: [" in msg:
                msg = msg.split("Server returned error: ", 1)[1][:160]
            return OpResult(False, reason=msg[:200])
        except Exception as e:
            return OpResult(False, reason=str(e)[:200])
        return OpResult(True, tx=tx)

    # --- PSM ---------------------------------------------------------------

    def psm_mint(self, xel_amount_atomic: int, min_xusd_out: int = 1) -> OpResult:
        expected = int(xel_amount_atomic * (self.price_usd() or 1.0))
        min_out = max(min_xusd_out, int(expected * 0.95))  # 5% slippage guard
        return self._invoke("PSM", "mint",
                            [val_u64(xel_amount_atomic), val_u64(min_out)],
                            deposits={self.xel_asset: {"amount": xel_amount_atomic}},
                            max_gas=15_000_000)

    def psm_redeem(self, xusd_amount_atomic: int, min_xel_out: int = 1) -> OpResult:
        usd = self.price_usd() or 1.0
        expected_xel = int(xusd_amount_atomic / usd)
        min_out = max(min_xel_out, int(expected_xel * 0.90))  # 10% slippage guard
        return self._invoke("PSM", "redeem",
                            [val_u64(xusd_amount_atomic), val_u64(min_out)],
                            deposits={self.xusd_asset: {"amount": xusd_amount_atomic}},
                            max_gas=15_000_000)

    # --- VaultEngine V3 ------------------------------------------------------

    def vault_deposit(self, xel_amount_atomic: int) -> OpResult:
        salt = ("0" * 60) + format(int(time.time()) & 0xFFFFFFFF, "08x")
        return self._invoke("VaultEngineV3", "deposit",
                            [val_hash(self.xel_asset), val_u64(xel_amount_atomic),
                             val_hash(salt)],
                            deposits={self.xel_asset: {"amount": xel_amount_atomic}},
                            max_gas=20_000_000)

    def vault_borrow(self, vault_id: int, xusd_amount_atomic: int) -> OpResult:
        return self._invoke("VaultEngineV3", "borrow",
                            [val_u64(vault_id), val_u64(xusd_amount_atomic)],
                            max_gas=25_000_000)

    def vault_repay(self, vault_id: int, xusd_amount_atomic: int) -> OpResult:
        return self._invoke("VaultEngineV3", "repay",
                            [val_u64(vault_id), val_u64(xusd_amount_atomic)],
                            deposits={self.xusd_asset: {"amount": xusd_amount_atomic}},
                            max_gas=25_000_000)

    def vault_withdraw(self, vault_id: int, xel_amount_atomic: int) -> OpResult:
        return self._invoke("VaultEngineV3", "withdraw",
                            [val_u64(vault_id), val_u64(xel_amount_atomic)],
                            max_gas=20_000_000)

    # --- AMM -----------------------------------------------------------------

    def amm_swap(self, asset_in: str, asset_out: str,
                 amount_in_atomic: int, min_out_atomic: int = 1) -> OpResult:
        reserves = self._pool_reserves(asset_in, asset_out)
        if reserves:
            r_in, r_out = reserves
            if r_in > 0:
                out_est = amount_in_atomic * r_out // (r_in + amount_in_atomic)
                min_out_atomic = max(min_out_atomic, int(out_est * 0.90))
        return self._invoke("VaultSwapV2", "swap",
                            [val_hash(asset_in), val_hash(asset_out),
                             val_u64(amount_in_atomic), val_u64(min_out_atomic)],
                            deposits={asset_in: {"amount": amount_in_atomic}},
                            max_gas=25_000_000)

    def amm_add_liquidity(self, asset_a: str, amount_a_atomic: int,
                          asset_b: str, amount_b_atomic: int) -> OpResult:
        lo, hi = (asset_a, asset_b) if asset_a < asset_b else (asset_b, asset_a)
        lo_amt = amount_a_atomic if lo == asset_a else amount_b_atomic
        hi_amt = amount_b_atomic if lo == asset_a else amount_a_atomic
        return self._invoke("VaultSwapV2", "add_liquidity",
                            [val_hash(lo), val_hash(hi), val_u64(lo_amt), val_u64(hi_amt)],
                            deposits={lo: {"amount": lo_amt}, hi: {"amount": hi_amt}},
                            max_gas=30_000_000)

    def _pool_reserves(self, a: str, b: str):
        vs = self.C("vault_swap")
        if not vs:
            return None
        lo, hi = (a, b) if a < b else (b, a)
        pool = self.daemon.read_key(vs, f"p_{lo}_{hi}")
        if isinstance(pool, list) and len(pool) >= 6:
            ra, rb = int(pool[2]), int(pool[3])
            return (ra, rb) if lo == a else (rb, ra)
        return None

    # --- Savings -------------------------------------------------------------

    def savings_deposit(self, xusd_amount_atomic: int) -> OpResult:
        return self._invoke("SavingsRate", "deposit",
                            [val_u64(xusd_amount_atomic)],
                            deposits={self.xusd_asset: {"amount": xusd_amount_atomic}},
                            max_gas=15_000_000)

    def savings_withdraw(self, xusd_amount_atomic: int) -> OpResult:
        return self._invoke("SavingsRate", "withdraw",
                            [val_u64(xusd_amount_atomic)], max_gas=15_000_000)

    def savings_claim_interest(self) -> OpResult:
        return self._invoke("SavingsRate", "claim_interest", [], max_gas=15_000_000)

    # --- Privacy Mixer (private send: deposit → auto-mix to recipient) -------

    def mixer_send(self, recipient: str, xel_amount_atomic: int,
                   min_anonymity: int = 3) -> OpResult:
        return self._invoke("PrivacyMixer", "deposit",
                            [val_addr(recipient), val_hash(self.xel_asset),
                             val_u64(min_anonymity)],
                            deposits={self.xel_asset: {"amount": xel_amount_atomic}},
                            max_gas=20_000_000)

    def mixer_execute_mix(self) -> OpResult:
        return self._invoke("PrivacyMixer", "execute_mix", [], max_gas=30_000_000)

    def mixer_refund(self) -> OpResult:
        return self._invoke("PrivacyMixer", "execute_refund", [], max_gas=30_000_000)

    # --- Treasury Vault (multisig) --------------------------------------------

    def treasury_deposit(self, asset: str, amount_atomic: int) -> OpResult:
        return self._invoke("TreasuryVault", "deposit",
                            [val_hash(asset), val_u64(amount_atomic)],
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=10_000_000)

    def treasury_propose(self, asset: str, to: str, amount_atomic: int,
                         data_hex: str = "") -> OpResult:
        return self._invoke("TreasuryVault", "propose",
                            [val_hash(asset), val_addr(to),
                             val_u64(amount_atomic), val_bytes(data_hex)],
                            max_gas=10_000_000)

    def treasury_confirm(self, proposal_id: int) -> OpResult:
        return self._invoke("TreasuryVault", "confirm", [val_u64(proposal_id)])

    def treasury_revoke(self, proposal_id: int) -> OpResult:
        return self._invoke("TreasuryVault", "revoke", [val_u64(proposal_id)])

    def treasury_execute(self, proposal_id: int) -> OpResult:
        return self._invoke("TreasuryVault", "execute", [val_u64(proposal_id)],
                            max_gas=15_000_000)

    # --- RWA / AssetVault (issuer) ---------------------------------------------

    def rwa_mint(self, to: str, amount_atomic: int) -> OpResult:
        return self._invoke("AssetVault", "mint", [val_addr(to), val_u64(amount_atomic)],
                            max_gas=15_000_000)

    def rwa_transfer(self, to: str, amount_atomic: int) -> OpResult:
        av = self.C("asset_vault")
        ah = self.daemon.read_key(av, "ah") if av else None
        if not ah:
            return OpResult(False, reason="No RWA asset created yet")
        ah = str(ah)
        try:
            self.wallet.track_asset(ah)
        except Exception:
            pass  # already tracked
        return self._invoke("AssetVault", "transfer_asset",
                            [val_addr(to), val_u64(amount_atomic)],
                            deposits={ah: {"amount": amount_atomic}},
                            max_gas=15_000_000)

    # --- Miner actions -----------------------------------------------------------

    def miner_heartbeat(self) -> OpResult:
        return self._invoke("XelisVaultMiner", "submit_heartbeat", [])

    def miner_increase_stake(self, vlt_amount_atomic: int) -> OpResult:
        return self._invoke("XelisVaultMiner", "increase_stake",
                            [val_u64(vlt_amount_atomic)],
                            deposits={self.vlt_asset: {"amount": vlt_amount_atomic}})

    # --- Faucet -------------------------------------------------------------------

    def faucet_distribute(self, addresses: list) -> OpResult:
        fa = self.C("faucet")
        chunk = 6  # distribute(Address[])
        if not fa or not self.wallet:
            return OpResult(False, reason="Faucet unavailable")
        try:
            tx = self.wallet.invoke(fa, chunk,
                                    [{"type": "object", "value": [val_addr(a) for a in addresses]}],
                                    deposits={}, max_gas=10_000_000)
        except RPCError as e:
            msg = str(e)
            if "Module error: " in msg:
                msg = msg.split("Module error: ", 1)[1].split(":")[0].strip()
            return OpResult(False, reason=msg[:200])
        except Exception as e:
            return OpResult(False, reason=str(e)[:200])
        return OpResult(True, tx=tx)
