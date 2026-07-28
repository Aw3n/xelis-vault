# XELIS Vault — Privacy-First DeFi on XELIS BlockDAG

**XELIS Vault** is a decentralized finance protocol built on [XELIS](https://xelis.io), a privacy-focused Layer-1 blockchain featuring homomorphically-encrypted balances and native confidential assets.

The protocol suite includes a **CDP stablecoin engine** (xUSD), an **automated market maker** with integrated stability module (VaultSwap + PSM), a **governance framework** (VLT → Governor → Timelock), and a **miner rewards system** that distributes VLT to operators who maintain the oracle and other protocol services.

---

## Contract Addresses (Testnet)

| Contract | Address | Description |
|----------|---------|-------------|
| **PriceOracle v2.1** | `764ad585c2f484e54ea9dd06a7fb8b81397ba2487d37298f27edce3747d836dd` | XEL/USD price feed with propose-execute timelock and `distribute_reward` integration |
| **VaultEngine** | `667b165c8c9cd6cc3464378799e38b172e0f2e912f4b5c6202d37a8da3939bcc` | CDP engine — deposit XEL, borrow xUSD |
| **xUSD** | `909576c1fcd889ec443b63a4ce014bf756fcb8afd74c8c0ee902cac03384e3fc` | xUSD stablecoin token |
| **xUSD Asset** | `d8bd79a2aa33ad4a6fa0ac2b2440515124445ecce0468e070a8a09bb5ea9442f` | Native XELIS asset |
| **PSM v5.1** | `9f2667447b9a850ba4b260c19cd2c3786bc4a3c5559a08332a9e13bfa47191ae` | Stability module — mint/redeem xUSD at oracle price |
| **VaultSwapV2** | `1b6699398e2acecbdd1fd372952696cfc37b99eb1dcac45a7216661f96c60422` | AMM with TWAP-based fees + integrated PSM |
| **XelisVaultMiner v2.1** | `21ed1297c7ed4001a4a7c9a4bb89b10da0b0f3ad0312545a5af4a761200af207` | Miner registration, heartbeat, and `distribute_reward` for VLT emissions |
| **VLTToken v5.1** | `7275c55d711789b1b746cd4695b04c0e393a0db74ecf72360c5544b73368cfab` | Governance token — 10M fixed supply, minter whitelist pattern |
| **VLT Asset** | `2de72ed3ea2d8ff30e6df57ba3a4d993dedfa8636d207d43d09e33615bfde2c6` | Native XELIS asset |
| **Timelock v5** | `bf6c0004993d50d0edc31eb38cebad38aa95e522040c9ea1d48cdea2eb2df597` | Governance timelock |
| **GovernanceVault v5** | `830ddfd85eb8ccd44678719cd32633806eba44aa4b455b3785ba04fb3a0b4aa9` | Staking + voting power |
| **Governor v5** | `f8a5880d02616085b26fa4d2a5888bf3328d8ab679af1ed0c90d693bff09a119` | Proposal + voting |
| **GuardianMultisig v5** | `4c5783d36173e309fa47c746c37f865accf08c1a4dfee92ba84cc08392326e4a` | Emergency multisig |

All contracts are deployed, configured, and tested with end-to-end cycles on testnet.

---

## Quick Start

### Prerequisites

- Python 3.10+
- `requests` library (`pip install requests`)
- Access to a XELIS daemon and wallet (testnet or mainnet)

### Run the All-in-One Daemon

```bash
python3 scripts/xelis_vault_miner.py \
  --rpc http://127.0.0.1:18081 \
  --wallet-url http://127.0.0.1:18082
```

The daemon handles:

- **Price Oracle**: Fetches XEL/USD from CoinGecko + MEXC, proposes via `propose_price` (entry 2), executes after 3-block timelock via `execute_price` (entry 3), which triggers `distribute_reward` on the miner contract to mint VLT rewards
- **Miner Registration**: Registers your address as a miner on XelisVaultMiner with a 100 VLT stake
- **Heartbeat**: Periodically calls `submit_heartbeat` (entry 16) to maintain active status
- **Reputation Monitoring**: Tracks your miner reputation and warns if it falls below Good tier

### CLI Options

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

### Example: Register as a Miner

```bash
python3 scripts/xelis_vault_miner.py \
  --rpc http://127.0.0.1:18081 \
  --wallet-url http://127.0.0.1:18082 \
  --endpoint https://my-miner.example.com:8080 \
  --miner
```

You will be prompted for your miner address.

---

## Reward Flow

```
  PriceOracle v2.1
  ├─ propose_price(price)          # entry 2
  ├─ execute_price()               # entry 3 (after 3-block timelock)
  └──► XelisVaultMiner v2.1
       └─ distribute_reward()      # pub fn at chunk 18
           ├─ Validates miner is registered + active
           ├─ Calculates dynamic reward (reputation × base rate)
           ├─ Checks budget cap (distributed ≤ total_budget)
           └──► VLTToken v5.1
                └─ mint_to()       # pub fn at chunk 4
                    └─ VLT minted to miner address
```

When the price oracle executes a new price, it calls `Contract::call(18, ...)` on the miner contract. The miner validates the caller (must be an authorized service), checks the miner's registration and reputation, calculates a dynamic reward, and mints VLT tokens directly to the miner's wallet.

**Tested on testnet**: First successful distribution minted 71,347,030 VLT (0.71 VLT) to the miner wallet.

---

## Contract Entry IDs

Entry IDs in the XELIS VM correspond to direct chunk indices in the compiled bytecode. `fn` and `hook` chunks occupy positions and shift subsequent entry IDs.

### PriceOracle v2.1 (`764ad585...`)

| ID | Type | Entry | Parameters |
|----|------|-------|------------|
| 2 | entry | `propose_price` | `(price: u64)` |
| 3 | entry | `execute_price` | `()` |
| 4 | pub fn | `get_price` | `(asset: Hash) → u64` |
| 5 | entry | `get_price_entry` | `(asset: Hash) → u64` |
| 6 | entry | `cancel_pending` | `()` |
| 7 | entry | `set_miner_contract` | `(mc: Hash)` |
| 8 | entry | `set_timelock_blocks` | `(blocks: u64)` |

### XelisVaultMiner v2.1 (`21ed1297...`)

| ID | Type | Entry | Parameters |
|----|------|-------|------------|
| 10 | entry | `register_miner` | `(endpoint: string, pubkey: Hash, services: u8)` |
| 11 | entry | `enable_service` | `(service_id: u8)` |
| 16 | entry | `submit_heartbeat` | `()` |
| 18 | pub fn | `distribute_reward` | `(miner: Address, svc: u8, valid: bool)` — cross-contract target |
| 26 | entry | `register_service` | `(svc_id: u8, contract: Hash)` |
| 35 | entry | `set_vlt_contract` | `(vc: Hash)` |
| 36 | entry | `set_vlt_asset` | `(va: Hash)` |
| 37 | entry | `set_treasury` | `(t: Address)` |

### VLTToken v5.1 (`7275c55d...`)

| ID | Type | Entry | Parameters |
|----|------|-------|------------|
| 4 | pub fn | `mint_to` | `(to: Address, amount: u64)` — cross-contract target |
| 5 | entry | `burn_own` | `(amount: u64)` |
| 7 | entry | `set_minter` | `(contract: Hash, enabled: bool)` |
| 9 | entry | `create_asset` | `()` — requires 1 XEL deposit |

---

## Architecture

```
xelis-vault/
├── contracts/              # Silex smart contract source (.slx)
│   ├── amm/               # PSM.slx, VaultSwapV2.slx
│   ├── oracle/            # PriceOracle.slx
│   ├── miner/             # XelisVaultMiner.slx
│   ├── token/             # VLTToken.slx
│   ├── vault/             # VaultEngine.slx
│   ├── governance/        # GovernanceVault, Governor, Timelock, GuardianMultisig
│   └── ...                # 33 contracts total
├── scripts/
│   ├── xelis_vault_miner.py   # All-in-one daemon
│   └── price_bot.py           # Standalone price oracle bot
├── .env                   # Contract addresses
└── README.md
```

---

## Security

- **Cross-contract calls require `pub fn`**: `Contract::call()` validates `Access::All`. Calling `entry` functions fails with "Chunk is not public". All cross-contract targets (`distribute_reward`, `mint_to`, `get_price`) must be declared `pub fn`.
- **`get_caller()` returns the original wallet source address** even during nested cross-contract calls. Use `get_contract_caller()` to identify the immediate calling contract.
- **`transfer_contract` before `burn_tokens`**: When a contract receives xUSD as a deposit and needs to burn it, the deposited tokens must first be forwarded to the xUSD contract via `transfer_contract(xusd_hash, amount, xusd_asset)` before calling `burn_tokens`. The xUSD contract checks its own balance, not the caller's deposit.
- **Hash parameters require `opaque` type**: Use `{"type": "opaque", "value": {"type": "Hash", "value": "hex..."}}` for any Hash that will be stored in Storage and later loaded. Using `string` type stores the value as a string, causing a type mismatch on retrieval.
- **`entry_id` = chunk index**: All `fn` and `hook` declarations occupy chunk positions and shift subsequent entry IDs. Always count from the beginning of the file.

---

## License

MIT — see [`LICENSE`](LICENSE).

## Links

- XELIS Blockchain: [https://xelis.io](https://xelis.io)
- Testnet Explorer: [https://testnet-explorer.xelis.io/](https://testnet-explorer.xelis.io/)
- XELIS GitHub: [https://github.com/xelis-project/xelis-blockchain](https://github.com/xelis-project/xelis-blockchain)
