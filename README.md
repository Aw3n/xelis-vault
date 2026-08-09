<div align="center">

# XELIS Vault

**Privacy-First DeFi on XELIS BlockDAG**

CDP stablecoin · Decentralized oracle · AMM + PSM · Governance · Privacy mixer · E2E chat

[![Network](https://img.shields.io/badge/network-testnet-blue)](https://testnet-explorer.xelis.io/)
[![Contracts](https://img.shields.io/badge/contracts-48%20Silex-blueviolet)](contracts/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

### Install everything in one line

**Linux & macOS:**

```bash
curl -fsSL https://xelisvault.github.io/xelis-vault/install | bash
```

**Windows (PowerShell):**

```powershell
irm https://xelisvault.github.io/xelis-vault/install.ps1 | iex
```

**Windows (Command Prompt):** download [`install.bat`](install.bat) and double-click it.

All three methods install **both** `xvault` (community CLI) and `xvault-miner` (miner dashboard).

> **IMPORTANT — Contracts not yet deployed**
>
> The smart contracts are currently being tested. The official testnet deployment is scheduled for **August 25, 2026**.
>
> Until then, `xvault` and `xvault-miner` will install and run, but **cannot connect to the protocol** (contract addresses are not yet available).
>
> Install now to be ready — once contracts are deployed, simply run `xvault-miner --setup` (or `xvault --setup`) to configure the addresses and start using the protocol.

---

**Miner?** Run `xvault-miner` after install.  
**Community member?** Run `xvault` after install.  
**Want to run a chat relayer?** Run `xvault-relayer` after install.

---

</div>

---

## Quick Start

### Step 1 — Install

**Linux & macOS:**

```bash
curl -fsSL https://xelisvault.github.io/xelis-vault/install | bash
```

**Windows (PowerShell):**

```powershell
irm https://xelisvault.github.io/xelis-vault/install.ps1 | iex
```

**Windows (Command Prompt):** download [`install.bat`](install.bat) and double-click it.

This single command:
- Detects your OS and architecture (Linux, macOS, Windows)
- Clones the repository to `~/.xelis-vault/src` (or `%USERPROFILE%\.xelis-vault\src` on Windows)
- Creates a Python virtualenv with all dependencies
- Installs **two launchers**:
  - `xvault` — community CLI (wallet, vaults, swaps, governance, mixer, chat)
  - `xvault-miner` — miner dashboard (real-time TUI with reputation, rewards, stats)
- Generates config with testnet defaults
- No telemetry, no phone-home, all data stays local

If the launcher directory is not in your PATH, the installer tells you exactly what to do.

### Step 2 — Choose your role

#### For Miners

```bash
xvault-miner
```

Interactive dashboard that shows in real-time:
- **Reputation** (Excellent / Good / Warning / Critical / Banned) with progress bar
- **Stake & rewards** (VLT balance, total earned, total slashed)
- **Submission stats** (valid / total, success rate)
- **Protocol stats** (budget, distribution, budget factor, active miners)
- **Price feeds** (XEL/USD, deviation, sources count, staleness)
- **Service selection** (oracle only, chat only, or both)

Quick start with flags:
```bash
xvault-miner --miner                          # Start mining immediately
xvault-miner --services oracle                # Oracle only
xvault-miner --services chat                  # Chat only
xvault-miner --services both                  # Both (default)
xvault-miner --dry-run                        # Simulate without submitting
```

#### For Community Members

```bash
xvault
```

Interactive menu with:
- **Create or import** a XELIS wallet (auto-downloads official wallet binary)
- **View your balance** (XEL, VLT, xUSD)
- **Manage vaults** (deposit XEL, borrow xUSD, repay, withdraw, liquidate)
- **Swap** (XEL ↔ xUSD via PSM, XEL ↔ VLT via AMM)
- **Govern** (stake VLT, vote on proposals, create proposals)
- **Mix** (private transfers via PrivacyMixer with ZK proofs)
- **Chat** (E2E encrypted messaging anchored on-chain)
- **View stats** (protocol-wide statistics, all public on-chain data)

Quick commands:
```bash
xvault --balance     # Quick balance check
xvault --swap        # Quick swap menu
xvault --vault       # Vault management
xvault --governance  # Governance menu
```

### Uninstall

**Linux & macOS:**

```bash
curl -fsSL https://xelisvault.github.io/xelis-vault/install | bash -s -- --uninstall
```

**Windows (PowerShell):**

```powershell
irm https://xelisvault.github.io/xelis-vault/install.ps1 | iex -Args "--uninstall"
```

---

## Architecture

```
XELIS Vault v10.3 — 48 Silex contracts

┌─────────────────────────────────────────────────────────────┐
│                    CONTRACT REGISTRY                         │
│            (name → hash resolution, upgradeable)              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌──────────────────┐                │
│  │  StakedOracle    │───▶│  XelisVaultMiner  │              │
│  │  (decentralized  │    │  (stake, reput.,  │              │
│  │   median oracle) │    │   rewards, slash) │              │
│  └────┬────────────┘    └───────┬──────────┘                │
│       │                         │                            │
│       │ price                   │ mint VLT                   │
│       ▼                         ▼                            │
│  ┌─────────────┐    ┌──────────────────┐                    │
│  │ VaultEngine  │    │    VLTToken       │                   │
│  │ (CDP, XEL →  │    │  (10M fixed supply)│                   │
│  │  xUSD, stab. │    └──────────────────┘                    │
│  │  fee)        │                                            │
│  └──────┬───────┘    ┌──────────────────┐                    │
│         │            │      xUSD          │                   │
│         │ mint/burn  │  (elastic supply)  │                   │
│         └───────────▶│                    │                   │
│                      └────────┬───────────┘                   │
│                               │                               │
│  ┌─────────────┐    ┌────────┴───────────┐                   │
│  │     PSM      │◀──▶│   VaultSwapV2      │                   │
│  │ (peg stability│   │ (AMM + PSM, TWAP)  │                   │
│  │  xUSD ↔ XEL) │    │  VLT/XEL pool      │                   │
│  └─────────────┘    └────────────────────┘                   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    GOVERNANCE                           │  │
│  │  GovernanceVault → Governor → Timelock → GuardianMultisig│  │
│  │  OracleGovernance (oracle params)                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────┐ │
│  │FlashLoan│ │SealedBid│ │Privacy  │ │Vault   │ │Insurance││
│  │         │ │Auction  │ │Mixer    │ │Chat    │ │Pool     ││
│  └────────┘ └──────────┘ └─────────┘ └────────┘ └────────┘ │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           BRAINSTORMING FEATURES (v10.2)               │  │
│  │  NotificationCenter · CreditScore · EmergencyShutdown  │  │
│  │  GovernanceDelegation · VaultInsurance · Analytics     │  │
│  │  LiquidationMarket · VaultBounties · SocialTrading     │  │
│  │  YieldOptimizer · VaultTemplates · MultiCollateralVault│  │
│  │  VaultNFT (tokenized positions)                        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Oracle: Decentralized & Graceful

XELIS Vault uses **StakedOracle** — a fully decentralized oracle with:

- **Median aggregation** (robust to outliers)
- **Multi-feed support** (XEL/USD, XEL/BTC, etc.)
- **Reputation-weighted rewards** (1.5× Excellent → 0× Banned)
- **Progressive slashing** (1% outlier → 50% malicious)
- **Circuit breaker** (pauses on >20% price movement)
- **Bootstrap mode** (works with 3 miners, scales to 100+)

### Graceful Degradation

The protocol **never stops working**, even if miners leave:

| Active miners | Mode | Behavior |
|--------------|------|----------|
| 0 | Emergency | Last known price used (marked stale) |
| 1–2 | Degraded | Price updates from single miner (no slashing) |
| 3–9 | Bootstrap | Median aggregation, no slashing |
| 10+ | Full | Median + slashing + circuit breaker |

This means: even if the project loses popularity and miners drop, the protocol **continues to function**. DeFi operations (vaults, swaps, PSM) keep using the last known price.

---

## Miner Rewards

```
reward = BASE_REWARD_ORACLE (0.4756 VLT)
       × reputation_multiplier  (1.5× Excellent, 1.0× Good, 0.5× Warning, 0.25× Critical, 0× Banned)
       × budget_factor / 10000  (auto-adjusts every 2 weeks, 0.5×–2× range)
```

| Miners | Est. reward/miner/day | ROI on 100 VLT stake |
|--------|----------------------|---------------------|
| 10 | ~55 VLT | < 2 days |
| 50 | ~11 VLT | ~9 days |
| 100 | ~5.5 VLT | ~18 days |

**Budget: 6,000,000 VLT over 10 years** (60% of total supply).

### Features

- **Auto-slash offline miners** — keepers slash miners who miss heartbeats
- **Reputation temporal decay** — inactive miners slowly lose reputation
- **Compound rewards** — auto re-stake rewards for compound growth
- **Graceful degradation** — protocol works with 1 to 100+ miners

---

## Tokenomics

### VLT Token (10,000,000 fixed supply — no presale, no seed investors)

| Allocation | Amount | % | Purpose |
|------------|--------|---|---------|
| Oracle rewards | 6,000,000 | 60% | Distributed to miners over 10 years |
| Team | 1,000,000 | 10% | 4-year vesting, 1-year cliff |
| Treasury | 1,000,000 | 10% | Governance-controlled |
| DEX liquidity | 1,200,000 | 12% | VLT/XEL pool seeding |
| Community airdrop | 500,000 | 5% | Contributors & helpers |
| Community airdrop (launch) | 200,000 | 2% | Launch community distribution |
| Bug bounty | 100,000 | 1% | Perpetual |

**100% fair launch** — no presale, no seed investors, no VC allocation. The 7% airdrop is distributed to community members, contributors, and helpers who support the protocol.

### xUSD Stablecoin

- **Peg mechanism**: PSM (Peg Stability Module) — mint/redeem xUSD 1:1 with XEL at oracle price
- **Collateral**: VaultEngine CDPs — deposit XEL, borrow xUSD (200% min collateral ratio)
- **Stability fee**: 2% APR on borrows (accrues continuously via global index)
- **Burn mechanisms**: 50% of all slashes burned + 50% of protocol fees burned

### VLT/XEL Liquidity Pool

The AMM pool (`VaultSwapV2`) includes a VLT/XEL pool where:
- Price varies with supply and demand (constant-product formula)
- LPs earn swap fees (30 bps base + 5 bps treasury)
- **Liquidity incentives**: Treasury distributes VLT to LPs proportionally
- Pool strengthens over time as more LPs join and fees compound

---

## CLI Reference

### Miner Dashboard (`xvault-miner`)

| Flag | Description |
|------|-------------|
| `--rpc <url>` | Daemon RPC URL |
| `--wallet-url <url>` | Wallet RPC URL |
| `--miner` | Start mining immediately |
| `--services <choice>` | oracle, chat, or both |
| `--dry-run` | Simulate without submitting |
| `--setup` | Run interactive setup |
| `-y` | Skip prompts |

### Community CLI (`xvault`)

| Flag | Description |
|------|-------------|
| `--setup` | Wallet setup only |
| `--balance` | Quick balance check |
| `--swap` | Quick swap menu |
| `--vault` | Vault management |
| `--governance` | Governance menu |

Full CLI guide: [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [CLI Guide](docs/CLI_GUIDE.md) | Complete guide for `xvault` and `xvault-miner` |
| [Chat Guide](docs/CHAT_GUIDE.md) | How E2E encrypted chat works |
| [Whitepaper](docs/WHITEPAPER.md) | Full technical whitepaper |
| [Miner Guide](docs/MINER_GUIDE.md) | How to become a miner |
| [Provider Guide](docs/PROVIDER_GUIDE.md) | Price data provider setup |
| [User Guide](docs/USER_GUIDE.md) | End-user guide |
| [Reward System](docs/REWARD_SYSTEM.md) | Reward + reputation mechanics |
| [Roadmap](docs/ROADMAP.md) | Development roadmap |
| [Entry IDs](docs/ENTRY_IDS.md) | Auto-generated entry ID table |

---

## Security

- **`pub fn` for cross-contract** — Silex requires `pub fn` for `Contract::call()`. Entry functions fail with "Chunk is not public".
- **2-step emergency withdraw** — 24h delay on all fund-holding contracts
- **ReentrancyGuard** — `non_reentrant()` on all state-changing entries
- **Progressive slashing** — 1% to 50% based on severity
- **Reputation system** — 5-tier multiplier prevents bad actors from earning
- **Circuit breaker** — oracle pauses on >20% price movement
- **Graceful degradation** — protocol works with 1 to 100+ miners

---

## Community

- **Discord:** https://discord.gg/UHpYAWbG
- **Twitter:** https://x.com/xelisvault
- **GitHub:** https://github.com/XelisVault/xelis-vault
- **Testnet Explorer:** https://testnet-explorer.xelis.io/
- **XELIS Blockchain:** https://xelis.io

---

## License

MIT — see [LICENSE](LICENSE).
