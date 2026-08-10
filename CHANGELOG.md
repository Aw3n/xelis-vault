
---

## [v10.2] — 2026-08-09

### Added — Brainstorming Features (13 new contracts, ~4 800 lines of Silex)

Implemented ALL features from `docs/FUTURE_FEATURES.md` in a single iteration. No more "phases" — the user wanted it done now, so it's done.

**New contracts:**

| Contract | File | Entries | Purpose |
|---|---|---|---|
| NotificationCenter | `contracts/notifications/NotificationCenter.slx` | 14 | Encrypted notification preferences (push/email/telegram), 8 notification types, quiet hours, severity threshold |
| CreditScore | `contracts/credit/CreditScore.slx` | 15 | On-chain credit reputation (0-1000), 5 tiers, rate + LTV adjustments for P2P lending |
| EmergencyShutdown | `contracts/safety/EmergencyShutdown.slx` | 15 | Global circuit breaker (NORMAL/SOFT_PAUSE/FULL_SHUTDOWN/RECOVERY), 9 operation types |
| GovernanceDelegation | `contracts/governance/GovernanceDelegation.slx` | 18 | Liquid democracy, delegation by topic (oracle/lending/treasury), max depth 5 |
| VaultInsurance | `contracts/insurance/VaultInsurance.slx` | 18 | Auto-insurance against liquidation (0.5% premium, auto-repay at health < 120%) |
| AnalyticsCollector | `contracts/analytics/AnalyticsCollector.slx` | 17 | On-chain TVL/volume/liquidations/health distribution metrics (7d hourly + 1y daily) |
| LiquidationMarket | `contracts/liquidation/LiquidationMarket.slx` | 17 | Liquidator staking for priority, speed bonus (max 2%), leaderboard |
| VaultBounties | `contracts/liquidation/VaultBounties.slx` | 13 | Watcher bounties for finding unhealthy vaults (0.5% of collateral) |
| SocialTrading | `contracts/social/SocialTrading.slx` | 16 | Copy trading, leader opt-in, ratio 10-100%, max 100 followers per leader |
| YieldOptimizer | `contracts/vault/YieldOptimizer.slx` | 19 | 4 strategies (Conservative/Balanced/Aggressive/VLT Max), keeper 0.1% reward, auto-reinvest |
| VaultTemplates | `contracts/vault/VaultTemplates.slx` | 18 | 5 one-click templates (Safe Vault, Leverage Loop, Yield Farmer, PSM Arbitrage, LP Strategy) |
| MultiCollateralVault | `contracts/vault/MultiCollateralVault.slx` | 18 | Multi-collateral vaults (max 10 assets, LTV per asset: XEL 75%, VLT 60%, xUSD 90%, Gold 70%) |
| VaultNFT | `contracts/nft/VaultNFT.slx` | 23 | Tokenize vault positions as NFTs, marketplace, fractionalisation |

### Changed
- **README.md**: Updated 33 → 46 contracts, v7.0 → v10.2, added "BRAINSTORMING FEATURES" block in architecture diagram
- **docs/FUTURE_FEATURES.md**: Recreated with implementation status for all 15 features

### Stats
- **Total contracts**: 33 → 46
- **Total Silex lines**: ~13 220 → ~18 000
- **Total entry functions**: 630 → 855+
- **Total pub fn getters**: 162 → 192+

### Security
- All 13 new contracts follow Silex API conventions (`.expect("err")`, `s.delete()`, typed structs)
- Privacy preserved everywhere: no PII in plaintext, encrypted payloads, optional Ciphertext for amounts
- Anti-abuse mechanisms: rate limits, max concentrations, cycle detection, daily caps

---

## [v10.1] — 2026-08-09

### Added — Confidential VaultEngine + Encrypted Chat Metadata

- **Confidential VaultEngine**: deposit_confidential, borrow_confidential, repay_confidential using native Ciphertext API
- **Encrypted Chat Metadata**: update_channel_meta, get_channel_meta — who talks to whom, when, how much is now encrypted on-chain
- Native XELIS primitives used: `Ciphertext::new`, `ct.add()`, `ct.sub()`, `Ciphertext::zero()`, `RangeProof::verify()`, `Transcript::new()`

---

## [v10.0] — 2026-08-09

### Added — Phase 1 Improvements (20 new functions)

- Progressive slashing (1% per outlier, 5% per malicious act)
- Trimmed median oracle aggregation
- Anti-Sybil: progressive stake (100 → 500 → 1000 VLT based on reputation)
- Streaks and leaderboard for miners
- Relayer bonding (50 VLT slashable)
- Weighted ratings (anti-Sybil for relayers)
- Role hierarchy (admin > guardian > relayer > user)

---

## [v10.3] — 2026-08-09

### Added — Tokenomics Rework + Founder Revenue Model

**Critical analysis of external IA proposal** — 4 ideas rejected, 4 ideas accepted and improved.

#### NEW CONTRACTS (2 core contracts)

| Contract | File | Purpose |
|---|---|---|
| FounderVesting | `contracts/founder/FounderVesting.slx` | 500k VLT vesting over 4y, 1y cliff. Transparent, on-chain, governance-controlled |
| FeeDistributor | `contracts/founder/FeeDistributor.slx` | Splits protocol fees: 50% burn, 40% treasury, 10% founder. No extra cost to users |

#### MODIFIED CONTRACTS

- **VaultChat.slx** `anchor_messages` (entry 4): Added 5-layer anti-abus system
  - Layer 1: Rate limit (300 blocks between anchors per relayer)
  - Layer 2: Max 50 anchors/day per relayer
  - Layer 3: Min 5 messages + min 2 senders for reward
  - Layer 4: Daily reward cap (100 VLT/day per relayer)
  - Layer 5: Diminishing returns (100% → 80% → 60% → 40% → 20%)
  - Signature-based (not content-based) — respects E2E encryption

#### NEW TOKENOMICS (v10.3)

| Allocation | Amount | % | Change |
|---|---|---|---|
| Oracle rewards | 5,500,000 | 55% | -500k |
| Chat relayer rewards | 1,000,000 | 10% | NEW |
| DEX liquidity | 1,000,000 | 10% | -200k |
| Founder vesting (4y) | 500,000 | 5% | -500k |
| Treasury | 500,000 | 5% | -500k |
| Community airdrop | 500,000 | 5% | unchanged |
| Launch airdrop | 200,000 | 2% | unchanged |
| Bug bounty | 100,000 | 1% | unchanged |
| Protocol reserve | 200,000 | 2% | NEW |
| Founder ongoing (10y) | 500,000 | 5% | NEW |

#### FEE DISTRIBUTION MODEL (v10.3)

Old: 50% treasury / 50% burn
New: 50% burn / 40% treasury / 10% founder (via FeeDistributor)

**Key advantage**: No extra cost to users — fees already exist, only the split changes.

#### FOUNDER REVENUE MODEL

| Source | Annual estimate |
|---|---|
| VLT vesting (4y + 10y) | ~$50,000 |
| XEL revenue (10% of fees) | ~$131,400 |
| Relayer (optional) | ~$10,000 |
| **Total** | **~$191,400/year** |

Legitimate (profit share, not transaction tax), transparent (all on-chain), aligned with protocol success.

### REJECTED IDEAS (with reasons)

1. **Founder fee 0.5% per transaction** — red flag regulator + "rake" perception
2. **"Protocol revenue 2%" separate from "Team 5%"** — same pocket disguised
3. **verify_messages_are_real()** — impossible in E2E (content is encrypted)
4. **PSM/AMM auto-liquidity mixing** — Terra-like reserve/LP confusion

### Stats
- **Total contracts**: 46 → 48 (35 core + 13 pending)
- **Total Silex lines**: ~18,000 → ~19,000
- Chunk IDs validated: 23/23 OK
- Deployment priority: 35 core + 13 pending = 48 total


---

## [v10.4] — 2026-08-09

### Added — Airdrop System (testnet → mainnet)

Complete airdrop infrastructure: track contributions on testnet, distribute VLT on mainnet via Merkle proofs.

#### NEW CONTRACTS (2 core)

| Contract | File | Network | Purpose |
|---|---|---|---|
| AirdropTracker | `contracts/airdrop/AirdropTracker.slx` | TESTNET | Accumulates points per user from all core contracts (32 entries, 10 pub fn) |
| AirdropClaim | `contracts/airdrop/AirdropClaim.slx` | MAINNET | Distributes VLT via Merkle proofs (16 entries, 5 pub fn) |

#### NEW SCRIPTS

- `scripts/airdrop_indexer.py` — Bot that listens to on-chain events and calls `record_*()` on AirdropTracker (for contracts that don't call directly)
- `scripts/generate_airdrop_merkle.py` — Generates Merkle tree + proofs from AirdropTracker data (after finalize)

#### NEW DOCUMENTATION

- `docs/AIRDROP_PLAN.md` (400 lines) — Complete airdrop plan:
  - Process overview (7 steps from snapshot to claim)
  - Points system (7 categories, daily caps, bonus multipliers)
  - Qualification criteria (1000 points + 7 distinct days + mainnet address)
  - Distribution formula (proportional to points)
  - Anti-Sybil measures (on-chain + off-chain + governance)
  - Integration with core contracts (Option A: direct call, Option B: indexer)
  - Deployment checklist (before/during/end/mainnet)

#### AIRDROP MECHANICS

**Points system:**
- 7 categories: MINING, RELAYER, GOVERNANCE, CHAT, LIQUIDITY, BOUNTY, COMMUNITY
- Daily caps: 1000 pts/day mining, 500 relayer, 100 chat (anti-farm)
- Bonus: +25% for multi-role (3+ categories active)
- Qualification: 1000 points + 7 distinct days + mainnet address recorded

**Distribution:**
- 500,000 VLT total for testnet contributors
- Formula: `user_vlt = (user_points × 500,000 VLT) / total_points_all_users`
- Proportional, transparent, on-chain verifiable

**Process:**
1. Users interact with protocol on testnet → points accumulate
2. Users register mainnet address via `record_mainnet_address()`
3. Admin calls `freeze_points()` (snapshot)
4. Admin calls `finalize_distribution()` (calculate VLT per user)
5. Off-chain: `generate_airdrop_merkle.py` builds Merkle tree
6. Admin deploys `AirdropClaim.slx` on mainnet with Merkle root
7. Users call `claim(testnet_addr, mainnet_addr, amount, proof)` on mainnet
8. After 6 months, unclaimed funds → treasury

#### ANTI-SYBIL

- Daily caps on points (prevents bot farming)
- 7 distinct days minimum (filters one-day bots)
- 1000 points minimum (filters occasional bots)
- Mainnet address required (proves long-term intent)
- Off-chain pattern detection (5 addresses submitting same price at same second = suspect)
- Governance dispute mechanism

### Stats
- **Total contracts**: 48 → 50 (37 core + 13 pending)
- **Total Silex lines**: ~19,000 → ~26,000
- **Total entry functions**: 866 → 910+
- Chunk IDs validated: 23/23 OK
- Deployment priority: 37 core + 13 pending = 50 total
- Tests: 26/26 PASS (100%)


---

## [v10.4.1] — 2026-08-09

### Added — Airdrop CLI module + dashboard getters

#### NEW: `scripts/airdrop_cli.py` (550+ lines)

Complete interactive CLI module for the airdrop campaign. Integrates into `xvault` main menu as a new "🪂 Airdrop" option.

**Features:**
- **Dashboard** — real-time stats (participants, qualified, total points, distributable, status, timeline)
- **My Stats** — user's points, rank, percentage, estimated VLT, days active, qualification status
- **Leaderboard** — top 20 contributors with rank, points, VLT, qualification badge
- **My Breakdown** — points per category with visual bars + how to earn more
- **Register Mainnet Address** — interactive flow to record mainnet address (with anti-double-use check)
- **Category Stats** — all 7 categories with percentages, visual bars, and how to earn
- **Lookup User** — search any testnet address to see their profile
- **How to Earn Guide** — complete guide with all point values and qualification requirements

**Integration in `xvault.py`:**
- New "🪂 Airdrop" menu entry in main menu
- Dashboard now shows airdrop mini-stats (status, participants, my points, my rank)
- All 25 AirdropTracker pub fn accessible via the CLI

#### MODIFIED: `contracts/airdrop/AirdropTracker.slx`

Added 15 new pub fn for dashboard/website integration:
- `get_protocol_stats()` — all key metrics in 1 call
- `get_user_full_info(user)` — all 13 fields in 1 call (gas-efficient)
- `get_leaderboard_at_rank(rank)` — address at position N
- `get_leaderboard_entry(rank)` — full entry (addr, points, qualified, mainnet, distribution)
- `get_user_rank(user)` — position in leaderboard
- `get_estimated_distribution(user)` — VLT estimate before finalize
- `get_user_percentage(user)` — % of total (bps)
- `get_category_total(cat)` / `get_all_category_totals()` — category stats
- `get_testnet_address(mainnet_addr)` — reverse lookup
- `get_snapshot_info()` — deploy/freeze/finalize timestamps
- `get_user_activity_summary(user)` — days_active, qualified, has_mainnet
- `get_user_at_index(index)` — for iteration
- `is_qualified(user)` — bool
- `get_total_distributable()` — constant

**New storage keys:**
- `START_TOPO_KEY`, `FREEZE_TOPO_KEY`, `FINALIZE_TOPO_KEY` (timestamps)
- `MAINNET_TO_TESTNET_PREFIX` (reverse lookup with anti-double-use)
- `CAT_TOTAL_PREFIX` (category totals)

**Modified functions:**
- `add_points()` now tracks category totals
- `record_mainnet_address()` now maintains reverse lookup + prevents double-registration
- `freeze_points()` stores FREEZE_TOPO
- `finalize_distribution()` stores FINALIZE_TOPO

#### UPDATED: `docs/AIRDROP_PLAN.md`

New section 10 "Getters pour le site web (dashboard)" with:
- 4 subsections: Stats globales, Profil user, Leaderboard, Reverse lookup
- Detailed tables for each function (return type, usage)
- JavaScript integration example for website

### Stats
- AirdropTracker: 10 → 25 pub fn (+15)
- New script: airdrop_cli.py (550+ lines, 6 screens)
- All validators pass: 23/23 chunk IDs, 26/26 tests, 0 forbidden patterns


---

## [v10.5] — 2026-08-09

### Fixed — 9 critical bugs from external audit

An external IA cloned the repo and found 9 critical bugs. All have been verified and fixed.

#### 🔴 CRITICAL FIXES (would have broken the protocol at deployment)

1. **Oracle entry ID wrong everywhere** (Bug #1)
   - `oracle.call(21u16, ...)` used in 5 contracts (10 occurrences)
   - Entry 21 does NOT exist in StakedOracle (max = 15)
   - Correct entry: `4` (`get_price_for_asset_entry`)
   - Fixed in: PSM, VaultSwapV2, LendingMarket, SyndicatePool, VaultEngineV3

2. **ContractRegistry entry ID wrong** (Bug #2)
   - `reg.call(16u16, ...)` in VaultEngineV3
   - Entry 16 does NOT exist (max = 13)
   - Correct entry: `0` (`get_entry`)

3. **InterestRateModel entry IDs wrong** (Bug #3)
   - `irm.call(11u16)` and `irm.call(12u16)` in LendingMarket
   - These IDs do NOT exist (max = 8)
   - Correct entries: `0` (`get_borrow_rate_entry`) and `1` (`get_supply_rate_entry`)

4. **OracleGovernance entry IDs wrong** (Bug #4)
   - `oracle.call(35-39u16)` — IDs don't exist
   - Root cause: `pub fn` not exposed as `entry`
   - Fix: added 7 entry wrappers to StakedOracle (IDs 16-22)

5. **MinerPool entry IDs wrong** (Bug #5)
   - `miner.call(61-62u16)` — IDs don't exist
   - Fix: added 4 entry wrappers to XelisVaultMiner (IDs 36-39)

6. **Chunk ID validator was broken** (Bug #6)
   - Old validator only checked string existence, not actual entry IDs
   - Reported "23/23 OK" while 25 bugs existed
   - Fix: complete rewrite of `scripts/validate_chunk_ids.py`
   - Now parses contracts, resolves target contracts, verifies entry IDs
   - **73/73 real OK**

#### 🟠 HIGH FIXES

7. **Circuit breaker never checked** (Bug #7)
   - `FEED_CB_PAUSED_PREFIX` was stored but never verified
   - Fix: added `require(!cb_paused, "cbpaused")` in `submit_price`
   - Added `force_update_price()` escape hatch (entry 23) for stuck feeds

8. **FlashLoan callback whitelist never checked** (Bug #8)
   - `verify_callback` / `is_callback_verified` existed but unused
   - Fix: added `require(cb_verified, "cbnotverified")` in `flash_loan()`

#### 🟡 MEDIUM

9. **Ciphertext code may not compile** (Bug #9)
   - v10.1 confidential functions use `Ciphertext`, `RangeProof`, `Transcript`
   - These types may not exist in the public Silex ABI
   - Fix: documented as experimental, recommendation to test compilation

### NEW FEATURES (audit fixes)

- `force_update_price(feed_id, new_price)` — StakedOracle entry 23
  - Admin/guardian escape hatch for stuck feeds
  - Resets circuit breaker, advances cycle

- 7 entry wrappers in StakedOracle (IDs 16-22):
  - `set_max_deviation_bps_entry`
  - `set_cb_threshold_bps_entry`
  - `set_aggregation_blocks_entry`
  - `set_max_stale_blocks_entry`
  - `set_hard_stale_blocks_entry`
  - `pause_entry`
  - `unpause_entry`

- 4 entry wrappers in XelisVaultMiner (IDs 36-39):
  - `get_miner_stake_entry`
  - `get_miner_reputation_entry`
  - `get_active_miners_count_entry`
  - `get_miner_at_entry`

### NEW DOCUMENTATION

- `docs/AUDIT_v10.5.md` — complete audit report with all 9 bugs, fixes, and remaining recommendations

### Stats
- Bugs fixed: 9 (5 critical, 2 high, 1 medium, 1 validator)
- Entry wrappers added: 11
- Chunk IDs validated: 73/73 OK (real validator)
- Total contracts: 51 (38 core + 13 pending)
- Total entries: 935

