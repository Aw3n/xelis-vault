
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

