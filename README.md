<div align="center">

# XELIS Vault

**Privacy-First DeFi on XELIS BlockDAG**

CDP stablecoin · Decentralized oracle · AMM + PSM · Governance · Privacy mixer · E2E chat

[![Testnet](https://img.shields.io/badge/testnet-live-success)](https://testnet-explorer.xelis.io/)
[![Contracts](https://img.shields.io/badge/contracts-36%20Silex-blue)](contracts/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-whitepaper-orange)](docs/WHITEPAPER.md)

---

### Start mining in one line

```bash
curl -fsSL https://xelisvault.github.io/install | bash
```

Then:

```bash
xvault --miner
```

---

[Getting Started](#getting-started) · [Contracts](#contracts) · [Docs](#documentation) · [Community](#community)

</div>

---

## Getting Started

### 1. Install

```bash
curl -fsSL https://xelisvault.github.io/install | bash
```

That's it. The installer:
- Checks Python 3.10+ and git
- Clones the repo to `~/.xelis-vault/src`
- Creates a venv and installs dependencies
- Generates `~/.xelis-vault/config/config.json` with testnet defaults
- Installs an `xvault` launcher in `~/.local/bin`

**No telemetry. No phone-home. No wallet data leaves your machine.**

### 2. Run

```bash
# Interactive guided setup
xvault -i

# Or start directly as a miner
xvault --miner

# With custom RPC / wallet / endpoint
xvault \
  --rpc http://127.0.0.1:18081 \
  --wallet-url http://127.0.0.1:18082 \
  --endpoint https://my-miner.example.com:8080 \
  --miner
```

### 3. Earn

The daemon handles everything:
- **Price oracle** — fetches XEL/USD from CoinGecko + MEXC, proposes via `propose_price`, executes after 3-block timelock
- **Miner registration** — stakes 100 VLT, registers on `XelisVaultMiner`
- **Heartbeat** — calls `submit_heartbeat` every 100 blocks to stay active
- **Reputation** — monitors your tier (Excellent / Good / Warning / Critical / Banned)
- **Rewards** — VLT minted to your wallet on every valid price execution

First reward on testnet: **0.71 VLT** minted per valid submission at Excellent tier.

### Uninstall

```bash
curl -fsSL https://xelisvault.github.io/install | bash -s -- --uninstall
```

---

## Contracts

36 Silex contracts deployed on XELIS testnet:

| Contract | Address | Role |
|----------|---------|------|
| **PriceOracle v2.1** | `764ad585...` | XEL/USD price feed with propose-execute timelock |
| **VaultEngine** | `667b165c...` | CDP engine — deposit XEL, borrow xUSD |
| **xUSD** | `909576c1...` | xUSD stablecoin token |
| **PSM v5.1** | `9f266744...` | Peg stability module — mint/redeem xUSD 1:1 |
| **VaultSwapV2** | `1b669939...` | AMM with TWAP fees + integrated PSM |
| **XelisVaultMiner v2.1** | `21ed1297...` | Miner registration, heartbeat, reward distribution |
| **VLTToken v5.1** | `7275c55d...` | Governance token — 10M fixed supply |
| **GovernanceVault** | `830ddfd8...` | VLT staking + voting power |
| **Governor** | `f8a5880d...` | Proposals + voting |
| **Timelock** | `bf6c0004...` | Governance timelock |
| **GuardianMultisig** | `4c5783d3...` | Emergency multisig |

Full entry ID table: [`docs/ENTRY_IDS.md`](docs/ENTRY_IDS.md)

---

## Reward Flow

```
PriceOracle v2.1
├─ propose_price(price)              # entry 2
├─ execute_price()                   # entry 3 (after 3-block timelock)
└──► XelisVaultMiner v2.1
    └─ distribute_reward()           # pub fn, chunk 18
        ├─ Validate miner registered + active
        ├─ Calculate dynamic reward
        │   (base × reputation × budget_factor)
        ├─ Check budget cap
        └──► VLTToken v5.1
            └─ mint_to()             # pub fn, chunk 4
                └─ VLT minted to miner
```

**Reward formula:**

```
dynamic_reward = BASE_REWARD_ORACLE
               × reputation_multiplier   (1.5x Excellent, 1.0x Good, 0.5x Warning, 0.25x Critical, 0x Banned)
               × budget_factor / 10000   (auto-adjusts every 2 weeks, clamped 0.5x - 2x)
```

Default at Excellent tier: **~0.71 VLT per valid price submission**.

Full economics: [`docs/REWARD_SYSTEM.md`](docs/REWARD_SYSTEM.md)

---

## CLI Reference

| Flag | Description |
|------|-------------|
| `--rpc <url>` | Daemon JSON-RPC URL (default: `http://127.0.0.1:18081`) |
| `--wallet-url <url>` | Wallet JSON-RPC URL (default: `http://127.0.0.1:18082`) |
| `--wallet-user <user>` | Wallet RPC username (default: `wallet`) |
| `--wallet-pass <pass>` | Wallet RPC password (default: `testpass`) |
| `--endpoint <url>` | Public endpoint URL (required for miner registration) |
| `--miner` | Enable miner mode (registration + heartbeats) |
| `--no-oracle` | Disable price oracle updates |
| `--dry-run` | Log actions without submitting transactions |
| `-y` | Skip interactive prompts |
| `-i` | Interactive shell mode |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Whitepaper](docs/WHITEPAPER.md) | Full technical whitepaper (8,600+ words) |
| [Miner Guide](docs/MINER_GUIDE.md) | How to become a miner and earn VLT |
| [Provider Guide](docs/PROVIDER_GUIDE.md) | Price data provider setup |
| [User Guide](docs/USER_GUIDE.md) | End-user guide (lending, swap, governance) |
| [Reward System](docs/REWARD_SYSTEM.md) | Reward + reputation mechanics |
| [Roadmap](docs/ROADMAP.md) | Development roadmap (Q3 2026 → 2028+) |
| [Audit Report](docs/AUDIT_v5.0_REMEDIATION.md) | Security audit + remediation |
| [Entry IDs](docs/ENTRY_IDS.md) | Auto-generated entry ID table |

---

## Architecture

```
xelis-vault/
├── contracts/              # 36 Silex smart contracts
│   ├── amm/                # PSM, VaultSwapV2
│   ├── oracle/             # PriceOracle, StakedOracle
│   ├── miner/              # XelisVaultMiner, MinerPool
│   ├── token/              # VLTToken
│   ├── usd/                # xUSD
│   ├── vault/              # VaultEngine, VaultEngineV3
│   ├── governance/         # GovernanceVault, Governor, Timelock, GuardianMultisig
│   ├── lending/            # LendingMarket, PeerLoan, SyndicatePool
│   ├── flashloan/          # FlashLoan, FlashCallback
│   ├── auction/            # SealedBidAuction
│   ├── privacy/            # PrivacyMixer
│   ├── chat/               # VaultChat
│   └── ...
├── scripts/
│   ├── xelis_vault_miner.py    # All-in-one daemon
│   ├── price_provider.py       # Price data provider
│   ├── aggregation_keeper.py   # Aggregation trigger
│   └── custom_sources.example.json
├── deploy/                 # Deployment scripts
├── tests/                  # Integration tests
├── docs/                   # Documentation
├── install.sh              # One-line installer
└── install.py              # Python installer (alternative)
```

---

## Security

- **Cross-contract calls require `pub fn`** — `Contract::call()` validates `Access::All`. Calling `entry` functions fails with "Chunk is not public".
- **`get_caller()` returns the original wallet source** even during nested cross-contract calls. Use `get_contract_caller()` for the immediate calling contract.
- **`transfer_contract` before `burn_tokens`** — deposited xUSD must be forwarded to the xUSD contract before burning.
- **Hash parameters require `opaque` type** — using `string` causes type mismatch on storage retrieval.
- **2-step emergency withdraw** — 24h delay on all fund-holding contracts.
- **ReentrancyGuard** — `non_reentrant()` on all state-changing entries that hold funds.

Full audit: [`docs/AUDIT_v5.0_REMEDIATION.md`](docs/AUDIT_v5.0_REMEDIATION.md)

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
