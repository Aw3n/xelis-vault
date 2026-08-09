
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
