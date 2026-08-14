#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault v10.9 — Protocol Simulation Suite
============================================================================
Simule le protocole complet dans différents scénarios pour tester les limites.
In-Memory simulation (pas de blockchain réelle).

Scénarios:
  1. Bootstrapping (10 miners, peu d'activité)
  2. Croissance normale (100 miners, 1000 users)
  3. Attaque Sybil oracle
  4. Bank run / crash XEL
  5. Cas extrêmes (1 miner, 10000 miners)
  6. Manipulation PSM
  7. Liquidation en cascade
============================================================================
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ============================================================================
# CONSTANTS (match contract parameters v10.9)
# ============================================================================

VLT_TOTAL_SUPPLY = 10_000_000 * 10**8  # 10M VLT (atomic)
VLT_ORACLE_BUDGET = 5_500_000 * 10**8  # 5.5M VLT over 10 years
VLT_CHAT_BUDGET = 1_000_000 * 10**8    # 1M VLT over 10 years
MIN_STAKE = 1000 * 10**8               # 1000 VLT
MAX_STAKE_MULTIPLIER = 50               # 50x cap
BLOCKS_PER_YEAR = 6_307_200             # 5s blocks
BLOCKS_PER_DAY = 17_280
DAILY_BUDGET = (VLT_ORACLE_BUDGET / 10) / 365  # VLT/day for oracle

DEFAULT_MIN_CR = 150  # 150% min collateral ratio
LIQ_PENALTY = 10      # 10% liquidation penalty
STABILITY_FEE_APR = 2  # 2% APR
PSM_MINT_FEE = 0.5    # 0.5%
PSM_REDEEM_FEE = 0.1  # 0.1%
SWAP_FEE = 0.3        # 0.3%
MAX_DAILY_MINT_CAP = 100_000 * 10**8   # 100k XEL/day PSM cap
MAX_DEVIATION_BPS = 2000  # 20% max deviation
CB_THRESHOLD_BPS = 2000  # 20% circuit breaker

REPUTATION_TIERS = {
    "Excellent": (8000, 1.5),
    "Good": (5000, 1.0),
    "Warning": (2000, 0.5),
    "Critical": (1000, 0.25),
    "Banned": (0, 0.0),
}

# ============================================================================
# SIMULATION STATE
# ============================================================================

@dataclass
class Miner:
    addr: str
    stake: int  # atomic VLT
    reputation: int = 5000  # start at Good
    total_rewards: int = 0
    total_slashed: int = 0
    active: bool = True
    submissions: int = 0
    valid_submissions: int = 0

@dataclass
class Vault:
    owner: str
    collateral: int  # atomic XEL
    borrow: int      # atomic xUSD
    created_at: int  # block

@dataclass
class ProtocolState:
    # Miners
    miners: Dict[str, Miner] = field(default_factory=dict)
    total_staked: int = 0
    
    # Oracle
    xel_price: int = 19_000000  # $0.19 (atomic, 8 decimals)
    oracle_paused: bool = False
    cb_paused: bool = False
    last_aggregation: int = 0
    
    # Vaults
    vaults: List[Vault] = field(default_factory=list)
    total_collateral: int = 0
    total_borrow: int = 0
    
    # PSM
    psm_xel_reserve: int = 0
    psm_xusd_minted: int = 0
    daily_mint_used: int = 0
    daily_redeem_used: int = 0
    
    # Token economics
    distributed_rewards: int = 0
    xusd_supply: int = 0
    current_block: int = 0
    budget_factor: int = 10000  # 1.0x
    
    # Stats
    total_deposits: int = 0
    total_borrows: int = 0
    total_repays: int = 0
    total_liquidations: int = 0
    total_swaps: int = 0
    
    # Flags
    rewards_frozen: bool = False

    def get_reputation_mult(self, rep):
        for name, (threshold, mult) in REPUTATION_TIERS.items():
            if rep >= threshold:
                return mult, name
        return 0.0, "Banned"

    def advance_blocks(self, n):
        self.current_block += n
        # Reset daily caps
        if self.current_block % BLOCKS_PER_DAY == 0:
            self.daily_mint_used = 0
            self.daily_redeem_used = 0

    def advance_days(self, n):
        self.advance_blocks(n * BLOCKS_PER_DAY)


# ============================================================================
# PROTOCOL FUNCTIONS (simulated)
# ============================================================================

def get_stake_weighted_median(prices_with_stakes):
    """Compute stake-weighted median."""
    if not prices_with_stakes:
        return 0
    # Sort by price
    sorted_ps = sorted(prices_with_stakes, key=lambda x: x[0])
    total_stake = sum(s for _, s in sorted_ps)
    if total_stake == 0:
        return sorted_ps[len(sorted_ps)//2][0]
    
    half = total_stake / 2
    cumul = 0
    for price, stake in sorted_ps:
        cumul += stake
        if cumul > half:
            return price
    return sorted_ps[-1][0]


def deposit_collateral(state, user, xel_amount):
    """Simulate VaultEngine.deposit"""
    vault = Vault(owner=user, collateral=xel_amount, borrow=0, created_at=state.current_block)
    state.vaults.append(vault)
    state.total_collateral += xel_amount
    state.total_deposits += 1
    return vault


def borrow_xusd(state, vault, xusd_amount):
    """Simulate VaultEngine.borrow with health check."""
    collateral_value = (vault.collateral * state.xel_price) // 10**8
    max_borrow = (collateral_value * 100) // DEFAULT_MIN_CR
    if vault.borrow + xusd_amount > max_borrow:
        return False, f"Exceeds max borrow ({max_borrow/10**8:.2f} xUSD)"
    vault.borrow += xusd_amount
    state.total_borrow += xusd_amount
    state.xusd_supply += xusd_amount
    return True, "OK"


def get_health_factor(state, vault):
    """Calculate health factor in bps."""
    if vault.borrow == 0:
        return 999999  # infinite
    collateral_value = (vault.collateral * state.xel_price) // 10**8
    return (collateral_value * 10000) // vault.borrow


def liquidate_vault(state, vault):
    """Simulate liquidation."""
    hf = get_health_factor(state, vault)
    if hf >= 10000:
        return False, "Not liquidatable"
    
    penalty = (vault.collateral * LIQ_PENALTY) // 100
    seized = vault.collateral
    state.total_collateral -= seized
    state.total_borrow -= vault.borrow
    state.xusd_supply -= vault.borrow
    state.total_liquidations += 1
    vault.collateral = 0
    vault.borrow = 0
    return True, f"Liquidated (health was {hf/100:.0f}%)"


def psm_mint(state, user, xel_amount):
    """Simulate PSM.mint."""
    if state.oracle_paused or state.cb_paused:
        return False, "Oracle paused"
    if state.daily_mint_used + xel_amount > MAX_DAILY_MINT_CAP:
        return False, "Daily cap exceeded"
    
    gross_xusd = (xel_amount * state.xel_price) // 10**8
    fee = (gross_xusd * PSM_MINT_FEE) // 100
    net_xusd = gross_xusd - fee
    
    state.psm_xel_reserve += xel_amount
    state.psm_xusd_minted += net_xusd
    state.xusd_supply += net_xusd
    state.daily_mint_used += xel_amount
    return True, f"Minted {net_xusd/10**8:.2f} xUSD"


def psm_redeem(state, user, xusd_amount):
    """Simulate PSM.redeem."""
    if state.oracle_paused or state.cb_paused:
        return False, "Oracle paused"
    
    gross_xel = (xusd_amount * 10**8) // state.xel_price
    fee = (gross_xel * PSM_REDEEM_FEE) // 100
    net_xel = gross_xel - fee
    
    if net_xel > state.psm_xel_reserve:
        return False, f"Insufficient PSM reserve ({state.psm_xel_reserve/10**8:.0f} XEL)"
    
    state.psm_xel_reserve -= net_xel
    state.psm_xusd_minted -= xusd_amount
    state.xusd_supply -= xusd_amount
    state.daily_redeem_used += xusd_amount
    return True, f"Redeemed {net_xel/10**8:.2f} XEL"


def register_miner(state, addr, stake):
    """Simulate XelisVaultMiner.register_miner."""
    if stake < MIN_STAKE:
        return False, f"Stake too low (min {MIN_STAKE/10**8:.0f} VLT)"
    miner = Miner(addr=addr, stake=stake)
    state.miners[addr] = miner
    state.total_staked += stake
    return True, "Registered"


def submit_price(state, miner_addr, price):
    """Simulate StakedOracle.submit_price + aggregate."""
    if state.oracle_paused:
        return False, "Oracle paused"
    if state.cb_paused:
        return False, "Circuit breaker active"
    
    miner = state.miners.get(miner_addr)
    if not miner or not miner.active:
        return False, "Not an active miner"
    
    miner.submissions += 1
    return True, "Submitted"


def aggregate_prices(state, price_submissions):
    """
    Simulate StakedOracle.aggregate with stake-weighted median.
    price_submissions: list of (miner_addr, price)
    """
    prices_with_stakes = []
    for miner_addr, price in price_submissions:
        miner = state.miners.get(miner_addr)
        if miner and miner.active:
            prices_with_stakes.append((price, miner.stake))
    
    if not prices_with_stakes:
        return False, "No valid submissions"
    
    # Stake-weighted median
    new_price = get_stake_weighted_median(prices_with_stakes)
    
    # Circuit breaker check
    if state.xel_price > 0:
        diff = abs(new_price - state.xel_price)
        pct = (diff * 10000) // state.xel_price
        if pct > CB_THRESHOLD_BPS:
            state.cb_paused = True
            return False, f"Circuit breaker triggered ({pct/100:.1f}% deviation)"
    
    state.xel_price = new_price
    state.last_aggregation = state.current_block
    return True, f"Aggregated to ${new_price/10**8:.4f}"


def distribute_rewards(state):
    """Simulate daily reward distribution (stake-weighted)."""
    if state.rewards_frozen:
        return 0, "Rewards frozen"
    
    active_miners = [m for m in state.miners.values() if m.active]
    if not active_miners:
        return 0, "No active miners"
    
    daily_budget = int(DAILY_BUDGET * state.budget_factor / 10000)
    total_distributed = 0
    
    for miner in active_miners:
        # Stake weight
        stake_mult = min(miner.stake / MIN_STAKE, MAX_STAKE_MULTIPLIER)
        
        # Reputation multiplier
        rep_mult, _ = state.get_reputation_mult(miner.reputation)
        
        # Share of budget (proportional to stake)
        share = (miner.stake * daily_budget) // state.total_staked if state.total_staked > 0 else 0
        reward = int(share * rep_mult)
        
        miner.total_rewards += reward
        state.distributed_rewards += reward
        total_distributed += reward
        miner.valid_submissions += 1
    
    return total_distributed, f"Distributed {total_distributed/10**8:.1f} VLT to {len(active_miners)} miners"


def slash_miner(state, miner_addr, severity):
    """Simulate slash_miner."""
    miner = state.miners.get(miner_addr)
    if not miner:
        return 0, "Miner not found"
    
    slash_rates = [1, 2, 5, 10, 50]  # % by severity 0-4
    rep_losses = [50, 200, 500, 1000, 5000]
    
    slash_bps = slash_rates[severity] * 100
    slash_amount = (miner.stake * slash_bps) // 10000
    
    miner.stake -= slash_amount
    miner.total_slashed += slash_amount
    state.total_staked -= slash_amount
    
    rep_loss = rep_losses[severity]
    miner.reputation = max(0, miner.reputation - rep_loss)
    
    if miner.stake < MIN_STAKE:
        miner.active = False
    
    return slash_amount, f"Slashed {slash_amount/10**8:.1f} VLT (sev {severity})"


# ============================================================================
# SCENARIO RUNNER
# ============================================================================

def run_scenario(name, fn):
    """Run a scenario and report results."""
    print(f"\n{'='*70}")
    print(f"  SCENARIO: {name}")
    print(f"{'='*70}\n")
    
    state = ProtocolState()
    results = fn(state)
    
    # Print final stats
    print(f"\n--- Final State ---")
    print(f"  Block:          {state.current_block:,}")
    print(f"  Miners:         {len([m for m in state.miners.values() if m.active])} active")
    print(f"  Total staked:   {state.total_staked/10**8:,.0f} VLT")
    print(f"  XEL price:      ${state.xel_price/10**8:.4f}")
    print(f"  xUSD supply:    {state.xusd_supply/10**8:,.0f}")
    print(f"  Total collateral: {state.total_collateral/10**8:,.0f} XEL")
    print(f"  Total borrow:   {state.total_borrow/10**8:,.0f} xUSD")
    print(f"  PSM reserve:    {state.psm_xel_reserve/10**8:,.0f} XEL")
    print(f"  Rewards distributed: {state.distributed_rewards/10**8:,.0f} VLT")
    print(f"  Deposits:       {state.total_deposits}")
    print(f"  Borrows:        {state.total_borrows}")
    print(f"  Liquidations:   {state.total_liquidations}")
    print(f"  Swaps:          {state.total_swaps}")
    print(f"  Oracle paused:  {state.oracle_paused}")
    print(f"  CB paused:      {state.cb_paused}")
    print(f"  Rewards frozen: {state.rewards_frozen}")
    
    if results:
        print(f"\n--- Results ---")
        for r in results:
            print(f"  {r}")
    
    return state


# ============================================================================
# SCENARIO 1: Bootstrapping (10 miners, minimal activity)
# ============================================================================

def scenario_bootstrap(state):
    results = []
    results.append("📋 10 miners register with 1,000 VLT each")
    
    for i in range(10):
        ok, msg = register_miner(state, f"miner_{i}", MIN_STAKE)
        if not ok:
            results.append(f"  ❌ miner_{i}: {msg}")
    
    results.append(f"  ✅ {len(state.miners)} miners registered")
    results.append(f"  Total staked: {state.total_staked/10**8:.0f} VLT")
    
    # Day 1-7: miners submit prices, earn rewards
    for day in range(7):
        state.advance_days(1)
        
        # Miners submit prices (honest, around $0.19)
        submissions = []
        for i, addr in enumerate(state.miners.keys()):
            price = 19_000000 + (i * 10000)  # slight variation
            submit_price(state, addr, price)
            submissions.append((addr, price))
        
        # Aggregate
        ok, msg = aggregate_prices(state, submissions)
        
        # Distribute rewards
        distributed, rmsg = distribute_rewards(state)
    
    results.append(f"After 7 days:")
    avg_reward = sum(m.total_rewards for m in state.miners.values()) / len(state.miners)
    results.append(f"  Price: ${state.xel_price/10**8:.4f}")
    results.append(f"  Rewards/miner: {avg_reward/10**8:.1f} VLT")
    
    # APY calculation
    apy = (avg_reward * 52 / MIN_STAKE) * 100  # weekly * 52
    results.append(f"  Est. APY: {apy:.0f}%")
    
    # Budget sustainability
    daily_dist = state.distributed_rewards / 7
    budget_days = VLT_ORACLE_BUDGET / daily_dist if daily_dist > 0 else 0
    results.append(f"  Daily distribution: {daily_dist/10**8:.1f} VLT")
    results.append(f"  Budget lasts: {budget_days/365:.0f} years")
    
    if apy > 500:
        results.append("  ⚠️ WARNING: APY too high (>500%) — may attract Sybil attackers")
    if budget_days / 365 < 10:
        results.append("  ⚠️ WARNING: Budget runs out in < 10 years")
    
    return results


# ============================================================================
# SCENARIO 2: Normal Growth (100 miners, 1000 users, 30 days)
# ============================================================================

def scenario_growth(state):
    results = []
    
    # Register 100 miners
    for i in range(100):
        stake = MIN_STAKE + (i * 500 * 10**8)  # varying stakes 1k to 50k
        register_miner(state, f"miner_{i}", stake)
    
    results.append(f"📋 100 miners registered (stakes 1k-50k VLT)")
    results.append(f"  Total staked: {state.total_staked/10**8:,.0f} VLT")
    
    # 1000 users deposit collateral and borrow
    for i in range(100):
        xel = (10 + i * 5) * 10**8  # 10-505 XEL
        vault = deposit_collateral(state, f"user_{i}", xel)
        
        # Borrow 50% LTV
        max_borrow = (xel * state.xel_price) // 10**8 * 50 // 100
        ok, msg = borrow_xusd(state, vault, max_borrow)
    
    results.append(f"📋 100 vaults created")
    results.append(f"  Total collateral: {state.total_collateral/10**8:,.0f} XEL")
    results.append(f"  Total borrow: {state.total_borrow/10**8:,.0f} xUSD")
    
    # PSM activity
    for i in range(50):
        ok, msg = psm_mint(state, f"user_{i}", 100 * 10**8)
    
    results.append(f"📋 50 PSM mints (100 XEL each)")
    results.append(f"  PSM reserve: {state.psm_xel_reserve/10**8:,.0f} XEL")
    results.append(f"  xUSD supply: {state.xusd_supply/10**8:,.0f}")
    
    # Run 30 days
    for day in range(30):
        state.advance_days(1)
        
        # Miners submit prices
        submissions = []
        for addr in list(state.miners.keys())[:50]:  # 50 active per day
            price = 19_000000 + ((day * 10000) if day < 15 else -(day - 15) * 5000)
            submit_price(state, addr, price)
            submissions.append((addr, price))
        
        aggregate_prices(state, submissions)
        distribute_rewards(state)
        
        # Check vaults health
        for vault in state.vaults:
            hf = get_health_factor(state, vault)
            if hf < 10000 and vault.borrow > 0:
                liquidate_vault(state, vault)
    
    results.append(f"After 30 days:")
    avg_reward = sum(m.total_rewards for m in state.miners.values()) / len(state.miners)
    results.append(f"  Rewards/miner: {avg_reward/10**8:.1f} VLT (30 days)")
    results.append(f"  Total distributed: {state.distributed_rewards/10**8:,.0f} VLT")
    results.append(f"  Liquidations: {state.total_liquidations}")
    
    daily_dist = state.distributed_rewards / 30
    budget_years = VLT_ORACLE_BUDGET / (daily_dist * 365) if daily_dist > 0 else 0
    results.append(f"  Budget lasts: {budget_years:.0f} years")
    
    # Check concentration
    sorted_miners = sorted(state.miners.values(), key=lambda m: m.stake, reverse=True)
    top_1_pct = (sorted_miners[0].stake / state.total_staked) * 100 if state.total_staked > 0 else 0
    top_10_stake = sum(m.stake for m in sorted_miners[:10])
    top_10_pct = (top_10_stake / state.total_staked) * 100 if state.total_staked > 0 else 0
    
    results.append(f"  Top 1 miner: {top_1_pct:.1f}% of stake")
    results.append(f"  Top 10 miners: {top_10_pct:.1f}% of stake")
    
    if top_1_pct > 20:
        results.append("  ⚠️ WARNING: Top miner has >20% of stake — concentration risk")
    if top_10_pct > 50:
        results.append("  ⚠️ WARNING: Top 10 miners have >50% — decentralization concern")
    
    return results


# ============================================================================
# SCENARIO 3: Sybil Attack on Oracle
# ============================================================================

def scenario_sybil_attack(state):
    results = []
    
    # Setup: 50 honest miners with 2,000 VLT each
    for i in range(50):
        register_miner(state, f"honest_{i}", 2000 * 10**8)
    
    honest_stake = state.total_staked
    results.append(f"📋 50 honest miners, total stake: {honest_stake/10**8:.0f} VLT")
    
    # Attacker has 100,000 VLT, splits into 100 Sybil miners
    attacker_stake = 100_000 * 10**8
    sybil_count = 100
    per_sybil = attacker_stake // sybil_count
    
    for i in range(sybil_count):
        register_miner(state, f"sybil_{i}", per_sybil)
    
    results.append(f"📋 Attacker: 100 Sybil miners × {per_sybil/10**8:.0f} VLT = {attacker_stake/10**8:.0f} VLT")
    results.append(f"  Total stake: {state.total_staked/10**8:.0f} VLT")
    results.append(f"  Attacker share: {(attacker_stake/state.total_staked)*100:.1f}%")
    
    # Day 1: Honest miners submit correct price
    submissions = []
    for addr in state.miners.keys():
        if "honest" in addr:
            price = 19_000000  # $0.19 (correct)
            submit_price(state, addr, price)
            submissions.append((addr, price))
    
    ok, msg = aggregate_prices(state, submissions)
    results.append(f"\nDay 1 (honest only): Price = ${state.xel_price/10**8:.4f} ✅")
    
    # Day 2: Attacker tries to manipulate — submit $0.50 (2.6x real price)
    submissions = []
    for addr in state.miners.keys():
        if "honest" in addr:
            price = 19_000000
        else:
            price = 50_000000  # $0.50 (manipulated)
        submit_price(state, addr, price)
        submissions.append((addr, price))
    
    # With SIMPLE median (by count): attacker has 100/150 = 66% of votes → controls median
    simple_prices = sorted([p for _, p in submissions])
    simple_median = simple_prices[len(simple_prices)//2]
    
    # With STAKE-WEIGHTED median: attacker has 100k/200k = 50% of stake
    # Need to build (price, stake) tuples from (addr, price) submissions
    prices_with_stakes = []
    for addr, price in submissions:
        miner = state.miners.get(addr)
        if miner and miner.active:
            prices_with_stakes.append((price, miner.stake))
    weighted_median = get_stake_weighted_median(prices_with_stakes)
    
    results.append(f"\nDay 2 (attack):")
    results.append(f"  Simple median (by count): ${simple_median/10**8:.4f} {'❌ MANIPULATED' if simple_median > 30_000000 else '✅'}")
    results.append(f"  Stake-weighted median: ${weighted_median/10**8:.4f} {'❌ MANIPULATED' if weighted_median > 30_000000 else '✅'}")
    
    if weighted_median <= 30_000000:
        results.append(f"  ✅ Stake-weighted median RESISTED the attack!")
        results.append(f"  Attacker has 50% of stake but couldn't push median above $0.30")
    else:
        results.append(f"  ❌ Attack succeeded even with weighted median!")
    
    # Day 3: Attacker tries extreme — $10.00
    state.cb_paused = False
    submissions = []
    for addr in state.miners.keys():
        if "honest" in addr:
            price = 19_000000
        else:
            price = 1_000_000000  # $10.00 (extreme)
        submit_price(state, addr, price)
        submissions.append((addr, price))
    
    ok, msg = aggregate_prices(state, submissions)
    results.append(f"\nDay 3 (extreme attack):")
    results.append(f"  Result: {msg}")
    if state.cb_paused:
        results.append(f"  ✅ Circuit breaker triggered — oracle paused")
    else:
        results.append(f"  Price: ${state.xel_price/10**8:.4f}")
    
    # Day 4: Guardian response
    results.append(f"\nDay 4 (guardian response):")
    results.append(f"  Guardian freezes rewards")
    state.rewards_frozen = True
    dist, dmsg = distribute_rewards(state)
    results.append(f"  Reward distribution: {dmsg}")
    
    results.append(f"  Guardian slashes 10 Sybil miners (severity 4 = 50%)")
    for i in range(10):
        slash_amount, smsg = slash_miner(state, f"sybil_{i}", 4)
    
    attacker_remaining = sum(m.stake for a, m in state.miners.items() if "sybil" in a)
    results.append(f"  Attacker remaining stake: {attacker_remaining/10**8:.0f} VLT (was 100,000)")
    results.append(f"  Attacker slashed: {(attacker_stake - attacker_remaining)/10**8:.0f} VLT")
    
    return results


# ============================================================================
# SCENARIO 4: Bank Run / XEL Crash
# ============================================================================

def scenario_bank_run(state):
    results = []
    
    # Setup: 50 miners, 200 vaults
    for i in range(50):
        register_miner(state, f"miner_{i}", MIN_STAKE)
    
    for i in range(200):
        xel = (50 + i * 10) * 10**8  # 50-2050 XEL
        vault = deposit_collateral(state, f"user_{i}", xel)
        max_borrow = (xel * state.xel_price) // 10**8 * 60 // 100  # 60% LTV
        borrow_xusd(state, vault, max_borrow)
    
    # PSM with 500k XEL reserve
    state.psm_xel_reserve = 500_000 * 10**8
    for i in range(500):
        psm_mint(state, f"psm_user_{i}", 1000 * 10**8)
    
    results.append(f"📋 Setup: 50 miners, 200 vaults, 500k XEL PSM reserve")
    results.append(f"  Collateral: {state.total_collateral/10**8:,.0f} XEL")
    results.append(f"  Borrow: {state.total_borrow/10**8:,.0f} xUSD")
    results.append(f"  xUSD supply: {state.xusd_supply/10**8:,.0f}")
    results.append(f"  PSM reserve: {state.psm_xel_reserve/10**8:,.0f} XEL")
    
    # Day 1: XEL crashes 50% ($0.19 → $0.095)
    old_price = state.xel_price
    state.xel_price = 9_500000  # $0.095
    
    results.append(f"\n💥 XEL CRASH: ${old_price/10**8:.4f} → ${state.xel_price/10**8:.4f} (-50%)")
    
    # Check vault health
    liquidatable = 0
    healthy = 0
    for vault in state.vaults:
        hf = get_health_factor(state, vault)
        if hf < 10000:
            liquidatable += 1
        else:
            healthy += 1
    
    results.append(f"  Vaults below 100% health: {liquidatable}/{len(state.vaults)}")
    results.append(f"  Vaults still healthy: {healthy}/{len(state.vaults)}")
    
    # Liquidate all unhealthy vaults
    for vault in state.vaults:
        if vault.borrow > 0:
            hf = get_health_factor(state, vault)
            if hf < 10000:
                liquidate_vault(state, vault)
    
    results.append(f"  Liquidations: {state.total_liquidations}")
    results.append(f"  Remaining collateral: {state.total_collateral/10**8:,.0f} XEL")
    results.append(f"  Remaining borrow: {state.total_borrow/10**8:,.0f} xUSD")
    
    # PSM bank run: everyone redeems xUSD for XEL
    results.append(f"\n🏃 PSM BANK RUN:")
    redeem_attempts = 0
    successful_redeems = 0
    total_redeemed = 0
    
    # Simulate 1000 users trying to redeem 1000 xUSD each
    for i in range(1000):
        redeem_attempts += 1
        ok, msg = psm_redeem(state, f"user_{i}", 1000 * 10**8)
        if ok:
            successful_redeems += 1
            total_redeemed += 1000 * 10**8
        else:
            break  # PSM reserve exhausted
    
    results.append(f"  Redeem attempts: {redeem_attempts}")
    results.append(f"  Successful: {successful_redeems}")
    results.append(f"  Total XEL redeemed: {total_redeemed/10**8:,.0f} XEL")
    results.append(f"  PSM reserve remaining: {state.psm_xel_reserve/10**8:,.0f} XEL")
    
    if state.psm_xel_reserve == 0:
        results.append(f"  ⚠️ PSM RESERVE EXHAUSTED — xUSD may depeg!")
    
    # Check if xUSD is still backed
    backing_ratio = (state.total_collateral * state.xel_price) // 10**8
    if state.xusd_supply > 0:
        peg_ratio = backing_ratio / state.xusd_supply
        results.append(f"\n  xUSD backing ratio: {peg_ratio*100:.1f}%")
        if peg_ratio < 1.0:
            results.append(f"  ❌ xUSD UNDER-COLLATERALIZED ({peg_ratio*100:.1f}%)")
        else:
            results.append(f"  ✅ xUSD still over-collateralized ({peg_ratio*100:.1f}%)")
    
    return results


# ============================================================================
# SCENARIO 5: Extreme Cases (1 miner, 10000 miners)
# ============================================================================

def scenario_extremes(state):
    results = []
    
    # Case A: Only 1 miner
    results.append("📋 Case A: Only 1 miner")
    register_miner(state, "solo_miner", MIN_STAKE)
    
    submissions = [("solo_miner", 19_000000)]
    ok, msg = aggregate_prices(state, submissions)
    results.append(f"  Aggregation: {msg}")
    
    dist, dmsg = distribute_rewards(state)
    daily = dist
    apy = (daily * 365 / MIN_STAKE) * 100
    results.append(f"  Daily reward: {daily/10**8:.1f} VLT")
    results.append(f"  APY: {apy:.0f}%")
    
    budget_years = VLT_ORACLE_BUDGET / (daily * 365) if daily > 0 else 0
    results.append(f"  Budget lasts: {budget_years:.0f} years")
    
    if apy > 1000:
        results.append("  ⚠️ WARNING: Single miner gets insane APY — Sybil incentive!")
    results.append("  NOTE: 1 miner = centralized oracle — min_providers should prevent this")
    
    # Case B: 10,000 miners
    state2 = ProtocolState()
    results.append(f"\n📋 Case B: 10,000 miners (1,000 VLT each)")
    
    for i in range(10000):
        register_miner(state2, f"miner_{i}", MIN_STAKE)
    
    results.append(f"  Total staked: {state2.total_staked/10**8:,.0f} VLT")
    
    # Simulate 1 day
    submissions = [(f"miner_{i}", 19_000000) for i in range(10000)]
    aggregate_prices(state2, submissions)
    dist, dmsg = distribute_rewards(state2)
    
    per_miner = dist / 10000
    apy = (per_miner * 365 / MIN_STAKE) * 100
    budget_years = VLT_ORACLE_BUDGET / (dist * 365) if dist > 0 else 0
    
    results.append(f"  Daily reward/miner: {per_miner/10**8:.4f} VLT")
    results.append(f"  APY: {apy:.1f}%")
    results.append(f"  Budget lasts: {budget_years:.0f} years")
    
    if apy < 10:
        results.append("  ⚠️ WARNING: APY < 10% — miners may leave")
    if budget_years < 10:
        results.append("  ⚠️ WARNING: Budget runs out in < 10 years")
    
    # Case C: Price manipulation attempt with large stake
    state3 = ProtocolState()
    results.append(f"\n📋 Case C: Large stake attacker (90% of total stake)")
    
    # 10 honest miners with 1,000 VLT each = 10,000 VLT
    for i in range(10):
        register_miner(state3, f"honest_{i}", MIN_STAKE)
    
    # 1 attacker with 90,000 VLT (90% of total)
    register_miner(state3, "attacker", 90_000 * 10**8)
    
    total = state3.total_staked
    attacker_pct = (90_000 * 10**8 / total) * 100
    results.append(f"  Total stake: {total/10**8:.0f} VLT")
    results.append(f"  Attacker: {attacker_pct:.1f}% of total stake")
    
    if attacker_pct > 50:
        results.append(f"  ❌ CRITICAL: Attacker controls >50% of stake — can manipulate oracle!")
        results.append(f"  Mitigation: Guardian can emergency_slash + ban")
        results.append(f"  Mitigation: Circuit breaker (20% deviation)")
        results.append(f"  Mitigation: Governance can increase min_stake")
    else:
        results.append(f"  ✅ Attacker < 50% — stake-weighted median is safe")
    
    return results


# ============================================================================
# SCENARIO 6: PSM Arbitrage + Peg Stress
# ============================================================================

def scenario_psm_stress(state):
    results = []
    
    # Setup
    state.psm_xel_reserve = 1_000_000 * 10**8  # 1M XEL
    state.xel_price = 19_000000  # $0.19
    
    results.append(f"📋 PSM setup: 1M XEL reserve, XEL = ${state.xel_price/10**8:.4f}")
    
    # Normal arbitrage: xUSD slightly off peg
    results.append(f"\n--- Normal arbitrage (xUSD at $1.02) ---")
    # User mints xUSD from PSM ($1.00), sells on AMM ($1.02) = 2% profit
    ok, msg = psm_mint(state, "arb_1", 10_000 * 10**8)
    results.append(f"  Mint 10k XEL: {msg}")
    results.append(f"  PSM reserve: {state.psm_xel_reserve/10**8:,.0f} XEL")
    results.append(f"  xUSD minted: {state.xusd_supply/10**8:,.0f}")
    
    # Stress: massive mint (try to drain PSM)
    results.append(f"\n--- Massive mint attempt (drain PSM) ---")
    total_minted = 0
    attempts = 0
    while state.psm_xel_reserve > 0 and attempts < 1000:
        ok, msg = psm_mint(state, f"drain_{attempts}", 10_000 * 10**8)
        if ok:
            total_minted += 10_000 * 10**8
            attempts += 1
        else:
            break
    
    results.append(f"  Attempts: {attempts}")
    results.append(f"  Total XEL minted against: {total_minted/10**8:,.0f} XEL")
    results.append(f"  PSM reserve: {state.psm_xel_reserve/10**8:,.0f} XEL")
    
    daily_cap_used_pct = (state.daily_mint_used / MAX_DAILY_MINT_CAP) * 100
    results.append(f"  Daily cap used: {daily_cap_used_pct:.1f}%")
    
    if daily_cap_used_pct >= 100:
        results.append(f"  ✅ Daily cap prevented full drain")
    else:
        results.append(f"  ⚠️ Daily cap not hit — PSM may be drainable")
    
    # Redeem stress
    results.append(f"\n--- Massive redeem (bank run on PSM) ---")
    total_redeemed = 0
    redeem_attempts = 0
    while state.psm_xel_reserve > 0 and redeem_attempts < 10000:
        ok, msg = psm_redeem(state, f"runner_{redeem_attempts}", 1000 * 10**8)
        if ok:
            total_redeemed += 1000 * 10**8
            redeem_attempts += 1
        else:
            break
    
    results.append(f"  Redeems: {redeem_attempts}")
    results.append(f"  Total XEL redeemed: {total_redeemed/10**8:,.0f} XEL")
    results.append(f"  PSM reserve: {state.psm_xel_reserve/10**8:,.0f} XEL")
    
    if state.psm_xel_reserve == 0:
        results.append(f"  ❌ PSM DRAINED — xUSD no longer redeemable at $1")
        results.append(f"  Impact: xUSD would trade below $1 on AMM")
        results.append(f"  Mitigation: Daily caps limit drain rate")
    
    return results


# ============================================================================
# SCENARIO 7: Cascade Liquidation
# ============================================================================

def scenario_cascade(state):
    results = []
    
    # Setup: 100 vaults at 60% LTV (health = 167%)
    for i in range(100):
        xel = 100 * 10**8  # 100 XEL each
        vault = deposit_collateral(state, f"user_{i}", xel)
        max_borrow = (xel * state.xel_price) // 10**8 * 60 // 100
        borrow_xusd(state, vault, max_borrow)
    
    results.append(f"📋 100 vaults at 60% LTV (health ~167%)")
    results.append(f"  Collateral: {state.total_collateral/10**8:.0f} XEL")
    results.append(f"  Borrow: {state.total_borrow/10**8:.0f} xUSD")
    
    # Price drops 30% ($0.19 → $0.133)
    state.xel_price = 13_300000
    results.append(f"\n💥 Price drops 30%: ${state.xel_price/10**8:.4f}")
    
    # Check health
    below_100 = 0
    below_150 = 0
    for vault in state.vaults:
        hf = get_health_factor(state, vault)
        if hf < 10000:
            below_100 += 1
        elif hf < 15000:
            below_150 += 1
    
    results.append(f"  Below 100% (liquidatable): {below_100}")
    results.append(f"  Below 150% (at risk): {below_150}")
    
    # Liquidate
    for vault in state.vaults:
        if vault.borrow > 0:
            hf = get_health_factor(state, vault)
            if hf < 10000:
                liquidate_vault(state, vault)
    
    results.append(f"  Liquidations: {state.total_liquidations}")
    results.append(f"  Remaining collateral: {state.total_collateral/10**8:.0f} XEL")
    results.append(f"  Remaining borrow: {state.total_borrow/10**8:.0f} xUSD")
    
    # Check if protocol is solvent
    if state.total_borrow > 0:
        backing = (state.total_collateral * state.xel_price) // 10**8
        ratio = backing / state.total_borrow * 100 if state.total_borrow > 0 else 0
        results.append(f"  Backing ratio: {ratio:.1f}%")
        if ratio < 100:
            results.append(f"  ❌ PROTOCOL INSOLVENT — bad debt!")
        else:
            results.append(f"  ✅ Protocol still solvent")
    else:
        results.append(f"  All debt cleared — no bad debt ✅")
    
    # Second wave: price drops another 20%
    state.xel_price = 10_640000  # $0.1064
    results.append(f"\n💥 Second drop (total -44%): ${state.xel_price/10**8:.4f}")
    
    below_100 = 0
    for vault in state.vaults:
        if vault.borrow > 0:
            hf = get_health_factor(state, vault)
            if hf < 10000:
                below_100 += 1
                liquidate_vault(state, vault)
    
    results.append(f"  Second wave liquidations: {below_100}")
    results.append(f"  Total liquidations: {state.total_liquidations}")
    
    if state.total_borrow > 0:
        backing = (state.total_collateral * state.xel_price) // 10**8
        ratio = backing / state.total_borrow * 100 if state.total_borrow > 0 else 0
        results.append(f"  Final backing ratio: {ratio:.1f}%")
        if ratio < 100:
            results.append(f"  ❌ BAD DEBT: {state.total_borrow/10**8:.0f} xUSD unbacked")
            results.append(f"  Mitigation: Insurance pool covers bad debt")
    
    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("  XELIS Vault v10.9 — Protocol Simulation Suite")
    print("=" * 70)
    
    run_scenario("1. Bootstrapping (10 miners, 7 days)", scenario_bootstrap)
    run_scenario("2. Normal Growth (100 miners, 100 vaults, 30 days)", scenario_growth)
    run_scenario("3. Sybil Attack on Oracle", scenario_sybil_attack)
    run_scenario("4. Bank Run / XEL Crash (-50%)", scenario_bank_run)
    run_scenario("5. Extreme Cases (1 miner, 10000 miners, 90% attacker)", scenario_extremes)
    run_scenario("6. PSM Arbitrage + Peg Stress", scenario_psm_stress)
    run_scenario("7. Cascade Liquidation (-44% crash)", scenario_cascade)
    
    print(f"\n{'='*70}")
    print(f"  ALL SCENARIOS COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
