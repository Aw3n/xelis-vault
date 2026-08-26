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
    val_u64, val_u128, val_u8, val_u16, val_str, val_hash, val_addr, val_bytes,
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
        "AssetVault": "e65d593b5818af605caffbc5c56dbf2ee966b8b7baad18e165a6012b7f7343df",
        "ComplianceModule": "1c0f143207c24d3b3e7fd04000cd1425e498505171de45ca980238e9f71c7f4a",
        "ContractRegistry": "19161543b9e5aef00c5a3e226058b946d847c78941f0c89e9b996c6332204970",
        "FaucetContract": "ed6e2f58c9a98bd098534efce6f430a3b2abb77cf015e5e5b193c4f37d7e16a4",
        "FeeDistributor": "c7e23f4cbe34ecb411811e7edbdbd55e428f2884b36d067be94ca4ca425491f7",
        "FlashCallback": "a84fc6d305b4ed1a6e15c310461799172272ec1cabf209316e724c3ede420f40",
        "FlashLoan": "3e3ae983175a1f97013963803d977dd39a3b525c1778cb4cd4e3c4858e2b5ef8",
        "FounderVesting": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "FounderVesting10y": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "FounderVesting4y": "fa07e6f5b5273c6d48994e846a05363099366661c4128f76b1fe41d15d1055a4",
        "GovernanceVault": "1e0408c02b99eeca65399033d16330e0af936525dd41fd860980e214f59d5da5",
        "Governor": "eb7a1aea5518ddeff6ab7379d9abe854969b690928124314ba378e5073c154b9",
        "GuardianMultisig": "9792a5894877a5982c9efdfb91f94c1536fe5f21c017a56c59691776413e4929",
        "InterestRateModel": "e9f716b07628fb8793adf3e20142348082a5021d671f316dad1e02cfb70f9c6d",
        "LendingMarket": "cb8f489382368b2f1b27bffcba346ede50aa180ebefac89ac444995bc95255bc",
        "MinerDelegation": "5eb34079fd84ee3626e410c0e9cbf5d568c76cabeaf36c0d00b5e21693033685",
        "MinerPool": "de744e0ccf45252070eb8fe83d0d16d36736ab7af1014a69405f358fb63c439b",
        "OracleGovernance": "bab86ca4a01c3250ce90b5c5d569b87ab221a212321848e104eb89500c28c953",
        "PSM": "977ddf73305dd21c29ffbe69dc2bdb29a12a62f4ff8bbc3140cafd4b51d5c2e1",
        "Payroll": "44ce12fb3d143f360c84664fe4849f01fb31ce5b45aebda38b037c70b4079b30",
        "PeerLoan": "ee27ecae9d8bb9b600026e883506eac39d81e5c908cca9dfeb6d96b529117568",
        "PrivacyMixer": "d384649c8f8f52116a198d2125bd1b6c3dff9bfda55643979c85a28631a6261d",
        "RevenueShare": "49c363dae4d32473d6d3c26ce0482cf735f7d656c665094002c1d21a6978c94b",
        "SavingsRate": "69d719949fd8f25fc33c8d4e8d9da6d8cb30f63a0163e39e1c9de79129d86f27",
        "SealedBidAuction": "105bb6ccdb14f8cd34da78b85ed36790b29b2625d168297aa4294d3a557c46eb",
        "StakedOracle": "e89bc25043c320fdac9c2030bc99e4b5bd94c9e0043132d10f66cd93576fa515",
        "SyndicatePool": "e1622bb0c1dace2c0b008a8448f2ade7df7eeb898410aa7f3355bf57bb48a0ae",
        "Timelock": "b925d8e30ccd7bcffdc1376a6aecd8daaaa71603a3d0a4c9413d9e4a8ed11082",
        "TreasuryVault": "c50042aa59703bb1c73ffa0ffcb01f23b8ae8419d1e23b2892b9dcf9dde0a886",
        "VLTToken": "020f228fbd61e3a6cd2d570083e14c02f7073f293c79ee4059359b896e217d84",
        "VaultChat": "54fbd12e40b5e039b9a1c7c0b9475cebc0fd77ec72cbf35a9551712a59ea0bbd",
        "VaultEngineV3": "dcefbd7bd5de056247b3e4195d52df42b32fa510361cd1dc31ed115d65450e48",
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
    "vault_engine": "VaultEngineV3",
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
    "PrivacyMixer":   {"deposit": 5, "execute_mix": 6, "execute_refund": 7,
                        "set_timeout_blocks": 15},
    "TreasuryVault":  {"propose": 9, "confirm": 10, "revoke": 11, "execute": 12, "deposit": 16},
    "AssetVault":     {"mint": 5, "transfer_asset": 6, "create_asset": 4,
                        "set_registry": 10},
    "StakedOracle":   {"submit_price": 16, "aggregate_now": 17},
    "XelisVaultMiner": {"register_miner": 15, "enable_service": 16, "increase_stake": 18,
                        "submit_heartbeat": 21},
    "GovernanceVault": {"stake": 4, "unstake": 5, "claim_rewards": 6,
                         "get_total_staked": 9, "get_user_staked": 10,
                         "notify_reward_amount": 12, "set_reward_distributor": 13},
    "Governor":        {"propose": 3, "vote": 4, "queue": 5, "cancel": 6,
                         "get_proposal_count": 7},
    "FlashLoan":       {"flash_loan": 6, "get_fee_bps": 7, "get_total_earned": 8,
                         "get_available_liquidity": 9, "set_fee_bps": 10,
                         "verify_callback": 23},
    "FlashCallback":   {"on_flash_loan": 2, "set_flash_loan": 4, "claim_profit": 5},
    "PeerLoan":        {"create_offer": 6, "cancel_offer": 7, "accept_offer": 8,
                         "repay": 9, "claim_collateral": 10, "get_offer": 11,
                         "get_offers_count": 12},
    "SyndicatePool":   {"create_pool": 8, "supply": 9, "withdraw_supply": 10,
                         "activate_pool": 11, "repay": 12, "claim": 13,
                         "get_pool": 14, "get_lender_position": 15,
                         "get_pools_count": 16},
    "SealedBidAuction": {"create_auction": 13, "commit": 14, "reveal": 15,
                          "settle": 16, "declare_winner": 17, "refund_bid": 18,
                          "claim_asset": 19, "claim_proceeds": 20,
                          "get_auction": 21, "get_auctions_count": 22},
    "Timelock":         {"execute_proposal": 6, "cancel_proposal": 7,
                          "set_min_delay": 9, "set_governor": 11},
    "VaultChat":        {"register_session": 7, "create_group": 8,
                          "add_group_member": 9, "anchor_messages": 11,
                          "store_message": 38, "store_group_message": 48,
                          "set_relayer_fee": 51, "claim_relayer_fees": 56,
                          "stake_relayer_bond": 121, "register_as_relayer": 66,
                          "send_direct_message": 113, "get_session": 13,
                          "get_group": 14, "is_active": 16,
                          "get_last_anchor": 17, "get_groups_count": 18},
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
        reg = (self.contracts.get("registry")
               or self.contracts.get("ContractRegistry")
               or self.contracts.get("contract_registry"))
        if not reg:
            return
        resolved = {}
        for key, name in _REGISTRY_NAMES.items():
            try:
                h = self.daemon.read_key(reg, f"cur_{name}")
            except Exception:
                continue
            if h and isinstance(h, str) and len(h) == 64:
                resolved[key] = h                # snake_case alias
                resolved[name] = h               # canonical CamelCase key
        self.contracts.update(resolved)

    # -- helpers ----------------------------------------------------------

    @property
    def address(self) -> str:
        addr = self.cfg.get("miner_address") or ""
        if addr:
            return addr
        try:
            return self.wallet.address() or ""
        except Exception:
            return ""

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
            pool = self.daemon.read_key(vs, f"p{lo}_{hi}")
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
            snap = self.daemon.read_key(ve, f"v{i}")
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
        salt = format(int(time.time()) & 0xFFFFFFFF, "x").zfill(64)
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

    # --- Governance ----------------------------------------------------------

    def gov_stake(self, vlt_atomic: int, lock_days: int = 7) -> OpResult:
        return self._invoke("GovernanceVault", "stake",
                            [val_u64(vlt_atomic), val_u64(lock_days)],
                            deposits={self.vlt_asset: {"amount": vlt_atomic}},
                            max_gas=20_000_000)

    def gov_unstake(self, stake_id: int) -> OpResult:
        return self._invoke("GovernanceVault", "unstake",
                            [val_u64(stake_id)], max_gas=15_000_000)

    def gov_claim_rewards(self) -> OpResult:
        return self._invoke("GovernanceVault", "claim_rewards",
                            [], max_gas=20_000_000)

    def gov_total_staked(self) -> int | None:
        return self._read_int("GovernanceVault", "get_total_staked", [])

    def gov_user_staked(self) -> int | None:
        return self._read_int("GovernanceVault", "get_user_staked",
                              [val_addr(self._my_addr())])

    def gov_stakes_count(self) -> int | None:
        return self._read_int("GovernanceVault", "get_stakes_count", [])

    # --- Governor (on-chain governance) --------------------------------------

    def gov_propose(self, target: str, entry_id: int,
                    params_hex: str, description: str) -> OpResult:
        return self._invoke("Governor", "propose",
                            [val_hash(target), val_u16(entry_id),
                             val_bytes(params_hex), val_str(description)],
                            max_gas=30_000_000)

    def gov_vote(self, proposal_id: int, support: int) -> OpResult:
        return self._invoke("Governor", "vote",
                            [val_u64(proposal_id), val_u8(support)],
                            max_gas=20_000_000)

    def gov_queue(self, proposal_id: int) -> OpResult:
        return self._invoke("Governor", "queue",
                            [val_u64(proposal_id)], max_gas=30_000_000)

    def gov_count(self) -> int | None:
        v = self._storage_read("Governor", "pc")
        return int(v) if v is not None else None

    # --- FlashLoan -----------------------------------------------------------

    def flashloan_borrow(self, asset: str, amount_atomic: int,
                         cb_hash: str, data: str = "") -> OpResult:
        return self._invoke("FlashLoan", "flash_loan",
                            [val_hash(asset), val_u64(amount_atomic),
                             val_hash(cb_hash), val_bytes(data)],
                            max_gas=30_000_000)

    def flashloan_fund(self, asset: str, amount_atomic: int) -> OpResult:
        """Fund FlashLoan liquidity via set_fee_bps (admin entry + deposit)."""
        return self._invoke("FlashLoan", "set_fee_bps",
                            [val_u64(9)],
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=10_000_000)

    def flashloan_verify_cb(self, cb_hash: str) -> OpResult:
        return self._invoke("FlashLoan", "verify_callback",
                            [val_hash(cb_hash)], max_gas=10_000_000)

    def flashloan_liquidity(self, asset: str) -> int | None:
        return self._read_int("FlashLoan", "get_available_liquidity",
                              [val_hash(asset)])

    def flashloan_earned(self) -> int | None:
        return self._read_int("FlashLoan", "get_total_earned", [])

    # --- FlashCallback -------------------------------------------------------

    def flashcb_fund(self, asset: str, amount_atomic: int) -> OpResult:
        """Fund FlashCallback via set_flash_loan (sets FL ref + deposits)."""
        cb = self.C("FlashCallback")
        fl = self.C("FlashLoan")
        if not cb or not fl:
            return OpResult(False, reason="FlashCallback/FlashLoan unavailable")
        return self._invoke_raw(cb, CHUNKS["FlashCallback"]["set_flash_loan"],
                                [val_hash(fl)],
                                deposits={asset: {"amount": amount_atomic}},
                                max_gas=10_000_000)

    def flashcb_profit(self, asset: str) -> OpResult:
        cb = self.C("FlashCallback")
        chunk = CHUNKS["FlashCallback"]["claim_profit"]
        return self._invoke_raw(cb, chunk, [val_hash(asset)],
                                max_gas=10_000_000)

    def _invoke_raw(self, contract: str, chunk: int, params,
                    deposits=None, max_gas=10_000_000) -> OpResult:
        if not contract or not self.wallet:
            return OpResult(False, reason="Contract unavailable")
        try:
            tx = self.wallet.invoke(contract, chunk, params,
                                    deposits=deposits or {},
                                    max_gas=max_gas)
        except RPCError as e:
            msg = str(e)
            if "Module error: " in msg:
                msg = msg.split("Module error: ", 1)[1].split(":")[0].strip()
            return OpResult(False, reason=msg[:200])
        except Exception as e:
            return OpResult(False, reason=str(e)[:200])
        return OpResult(True, tx=tx)

    # --- PeerLoan ------------------------------------------------------------

    def pl_create_offer(self, asset_lent: str, amount_atomic: int,
                        interest_bps: int, duration_blocks: int,
                        collateral_asset: str,
                        collateral_amount: int) -> OpResult:
        return self._invoke("PeerLoan", "create_offer",
                            [val_hash(asset_lent), val_u64(amount_atomic),
                             val_u64(interest_bps), val_u64(duration_blocks),
                             val_hash(collateral_asset),
                             val_u64(collateral_amount)],
                            deposits={asset_lent: {"amount": amount_atomic}},
                            max_gas=25_000_000)

    def pl_cancel_offer(self, offer_id: int) -> OpResult:
        return self._invoke("PeerLoan", "cancel_offer",
                            [val_u64(offer_id)], max_gas=15_000_000)

    def pl_accept_offer(self, offer_id: int,
                        collateral_asset: str,
                        collateral_amount: int) -> OpResult:
        return self._invoke("PeerLoan", "accept_offer",
                            [val_u64(offer_id)],
                            deposits={collateral_asset:
                                      {"amount": collateral_amount}},
                            max_gas=25_000_000)

    def pl_repay(self, offer_id: int, total_repay: int) -> OpResult:
        return self._invoke("PeerLoan", "repay",
                            [val_u64(offer_id)],
                            deposits={self.xel_asset: {"amount": total_repay}},
                            max_gas=25_000_000)

    def pl_count(self) -> int | None:
        v = self._storage_read("PeerLoan", "oc")
        return int(v) if v is not None else None

    # --- SyndicatePool -------------------------------------------------------

    def sp_create_pool(self, asset_lent: str, total_amount: int,
                       interest_bps: int, duration_blocks: int,
                       collateral_asset: str,
                       collateral_amount: int) -> OpResult:
        return self._invoke("SyndicatePool", "create_pool",
                            [val_hash(asset_lent), val_u64(total_amount),
                             val_u64(interest_bps), val_u64(duration_blocks),
                             val_hash(collateral_asset),
                             val_u64(collateral_amount)],
                            max_gas=25_000_000)

    def sp_supply(self, pool_id: int, amount_atomic: int,
                  asset: str = None) -> OpResult:
        asset = asset or self.xel_asset
        return self._invoke("SyndicatePool", "supply",
                            [val_u64(pool_id), val_u64(amount_atomic)],
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=20_000_000)

    def sp_activate(self, pool_id: int) -> OpResult:
        return self._invoke("SyndicatePool", "activate_pool",
                            [val_u64(pool_id)], max_gas=25_000_000)

    def sp_repay(self, pool_id: int, amount_atomic: int,
                 asset: str = None) -> OpResult:
        asset = asset or self.xel_asset
        return self._invoke("SyndicatePool", "repay",
                            [val_u64(pool_id), val_u64(amount_atomic)],
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=25_000_000)

    def sp_claim(self, pool_id: int) -> OpResult:
        return self._invoke("SyndicatePool", "claim",
                            [val_u64(pool_id)], max_gas=20_000_000)

    def sp_count(self) -> int | None:
        v = self._storage_read("SyndicatePool", "pc")
        return int(v) if v is not None else None

    # --- SealedBidAuction ----------------------------------------------------

    def au_create(self, asset: str, amount_atomic: int, bid_asset: str,
                  min_bid: int, cdur: int = 1440,
                  rdur: int = 1440) -> OpResult:
        return self._invoke("SealedBidAuction", "create_auction",
                            [val_hash(asset), val_u64(amount_atomic),
                             val_hash(bid_asset), val_u64(min_bid),
                             val_u64(cdur), val_u64(rdur)],
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=25_000_000)

    def au_commit(self, auction_id: int, bid_hash: str) -> OpResult:
        return self._invoke("SealedBidAuction", "commit",
                            [val_u64(auction_id), val_hash(bid_hash)],
                            max_gas=15_000_000)

    def au_reveal(self, auction_id: int, amount: int, nonce: int) -> OpResult:
        return self._invoke("SealedBidAuction", "reveal",
                            [val_u64(auction_id), val_u64(amount),
                             val_u64(nonce)],
                            max_gas=25_000_000)

    def au_settle(self, auction_id: int) -> OpResult:
        return self._invoke("SealedBidAuction", "settle",
                            [val_u64(auction_id)], max_gas=15_000_000)

    def au_declare_winner(self, auction_id: int, winner_addr: str,
                          amount: int) -> OpResult:
        return self._invoke("SealedBidAuction", "declare_winner",
                            [val_u64(auction_id), val_addr(winner_addr),
                             val_u64(amount)],
                            max_gas=20_000_000)

    def au_claim_asset(self, auction_id: int) -> OpResult:
        return self._invoke("SealedBidAuction", "claim_asset",
                            [val_u64(auction_id)], max_gas=15_000_000)

    def au_claim_proceeds(self, auction_id: int) -> OpResult:
        return self._invoke("SealedBidAuction", "claim_proceeds",
                            [val_u64(auction_id)], max_gas=15_000_000)

    def au_count(self) -> int | None:
        v = self._storage_read("SealedBidAuction", "ac")
        return int(v) if v is not None else None

    # --- Timelock ------------------------------------------------------------

    def tl_execute(self, proposal_id: int) -> OpResult:
        return self._invoke("Timelock", "execute_proposal",
                            [val_u64(proposal_id)], max_gas=30_000_000)

    def tl_cancel(self, proposal_id: int) -> OpResult:
        return self._invoke("Timelock", "cancel_proposal",
                            [val_u64(proposal_id)], max_gas=15_000_000)

    # --- VaultChat -----------------------------------------------------------

    def chat_register(self, enc_key: str) -> OpResult:
        return self._invoke("VaultChat", "register_session",
                            [val_hash(enc_key)], max_gas=15_000_000)

    def chat_send_dm(self, to: str, msg_hex: str, ttl: int = 0) -> OpResult:
        return self._invoke("VaultChat", "send_direct_message",
                            [val_addr(to), val_bytes(msg_hex), val_u64(ttl)],
                            max_gas=20_000_000)

    def chat_store_message(self, to: str, msg_hex: str, ttl: int = 0) -> OpResult:
        return self._invoke("VaultChat", "store_message",
                            [val_addr(to), val_bytes(msg_hex), val_u64(ttl)],
                            max_gas=20_000_000)

    def chat_create_group(self, enc_key: str) -> OpResult:
        return self._invoke("VaultChat", "create_group",
                            [val_hash(enc_key)], max_gas=15_000_000)

    def chat_add_member(self, group_id: int, addr: str, enc_key: str) -> OpResult:
        return self._invoke("VaultChat", "add_group_member",
                            [val_u64(group_id), val_addr(addr), val_bytes(enc_key)],
                            max_gas=15_000_000)

    def chat_group_msg(self, group_id: int, msg_hex: str, ttl: int = 0) -> OpResult:
        return self._invoke("VaultChat", "store_group_message",
                            [val_u64(group_id), val_bytes(msg_hex), val_u64(ttl)],
                            max_gas=20_000_000)

    def chat_anchor(self, root: str, count: int, msg_type: int = 0) -> OpResult:
        return self._invoke("VaultChat", "anchor_messages",
                            [val_hash(root), val_u64(count), val_u8(msg_type)],
                            max_gas=20_000_000)

    def chat_stake_bond(self, vlt_atomic: int) -> OpResult:
        return self._invoke("VaultChat", "stake_relayer_bond",
                            [val_u64(vlt_atomic)],
                            deposits={self.vlt_asset: {"amount": vlt_atomic}},
                            max_gas=20_000_000)

    def chat_register_relayer(self, endpoint: str, max_fee: int,
                              max_msgs: int) -> OpResult:
        return self._invoke("VaultChat", "register_as_relayer",
                            [val_str(endpoint), val_u64(max_fee), val_u64(max_msgs)],
                            max_gas=20_000_000)

    def chat_set_fee(self, token: int, fee: int) -> OpResult:
        return self._invoke("VaultChat", "set_relayer_fee",
                            [val_u64(fee), val_u8(token)],
                            max_gas=15_000_000)

    def chat_claim_fees(self) -> OpResult:
        return self._invoke("VaultChat", "claim_relayer_fees",
                            [], max_gas=20_000_000)

    def chat_groups_count(self) -> int | None:
        v = self._storage_read("VaultChat", "gc")
        return int(v) if v is not None else None

    # --- Funding helpers (deposit XEL to any contract) ----------------------

    def fund_contract(self, contract_key: str, asset: str,
                      amount_atomic: int, params: list = None) -> OpResult:
        """Deposit assets to any contract by invoking its deposit entry."""
        deposit_chunk = CHUNKS.get(contract_key, {}).get("deposit")
        if deposit_chunk is None:
            return OpResult(False, reason=f"{contract_key} has no deposit entry")
        p = params if params is not None else [val_hash(asset), val_u64(amount_atomic)]
        return self._invoke(contract_key, "deposit", p,
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=10_000_000)

    def fund_any(self, contract_key: str, entry_fn: str,
                 params: list, asset: str, amount_atomic: int) -> OpResult:
        """Deposit assets to any contract via any entry (entry persists deposits at tx level)."""
        return self._invoke(contract_key, entry_fn, params,
                            deposits={asset: {"amount": amount_atomic}},
                            max_gas=10_000_000)

    # --- RWA (admin asset registration) --------------------------------------

    def rwa_register(self, name: str, symbol: str,
                     decimals: int, supply: int) -> OpResult:
        return self._invoke("AssetVault", "create_asset",
                            [val_str(name), val_str(symbol),
                             val_u8(decimals), val_u64(supply)],
                            max_gas=20_000_000)

    # --- Generic int reader --------------------------------------------------

    def _storage_read(self, contract_key: str, key_str: str):
        """Read a string-keyed storage cell from a contract."""
        contract = self.C(contract_key)
        if not contract or not self.daemon:
            return None
        try:
            return self.daemon.read_key(contract, key_str)
        except Exception:
            return None

    def _read_int(self, contract_key: str, fn: str, params) -> int | None:
        contract = self.C(contract_key)
        chunk = CHUNKS.get(contract_key, {}).get(fn)
        if not contract or chunk is None:
            return None
        try:
            topo = self.p.daemon.get_topo()
            r = self.p.daemon.clientRpc.json_rpc(
                "get_contract_data",
                {"contract": contract,
                 "topoheight": topo,
                 "key": {"type": "map", "value": {
                     "key": val_u64(chunk),
                     "value": {"type": "map", "value": {
                         "key": {"type": "bytes", "value": ""},
                         "value": {"type": "primitive",
                                   "value": {"type": "u64", "value": "0"}}
                     }}
                 }}
                })
            if "result" in r:
                return None
        except Exception:
            return None
        return None

    def _my_addr(self) -> str:
        return self.wallet.get_address()
