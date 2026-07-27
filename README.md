# XELIS Vault — Privacy-First DeFi on XELIS BlockDAG

> **v5.0** — Core contracts deployed and verified on testnet | MIT License

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Overview

XELIS Vault is a decentralized finance protocol on the **XELIS BlockDAG** — a privacy-focused Layer-1 with homomorphic-encrypted balances and native confidential assets.

The protocol provides:

| Product | Contracts | What it does |
|---------|-----------|--------------|
| **xUSD Stablecoin** | `xUSD`, `PSM`, `VaultEngine` | Borrow xUSD against XEL collateral; redeem via PSM at oracle price |
| **AMM + PSM** | `VaultSwapV2` | Constant-product AMM with integrated PSM for xUSD/XEL swaps |
| **Price Oracle** | `PriceOracle` | On-chain XEL/USD price feed with propose-execute timelock |
| **VLT Token** | `VLT` | Governance token — fixed supply 10M, pre-minted to GovernanceVault |

---

## Deployed Contracts (Testnet)

All contracts have been deployed, configured, and tested with full mint→redeem cycles.

| Contract | Address | Status | Verified |
|----------|---------|--------|----------|
| **PriceOracle** | `083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6` | ✅ Live | propose_price(entry 2), execute_price(entry 3), get_price(entry 4) |
| **xUSD** | `909576c1fcd889ec443b63a4ce014bf756fcb8afd74c8c0ee902cac03384e3fc` | ✅ Full cycle | mint → burn tested |
| **xUSD Asset** | `d8bd79a2aa33ad4a6fa0ac2b2440515124445ecce0468e070a8a09bb5ea9442f` | ✅ Created | Custom asset on XELIS |
| **VaultEngine** | `667b165c8c9cd6cc3464378799e38b172e0f2e912f4b5c6202d37a8da3939bcc` | ✅ Full cycle | deposit → borrow → repay → withdraw tested |
| **PSM (Stability Module)** | `9f2667447b9a850ba4b260c19cd2c3786bc4a3c5559a08332a9e13bfa47191ae` | ✅ Full cycle | mint xUSD → redeem XEL at oracle price |
| **VaultSwapV2** | `1b6699398e2acecbdd1fd372952696cfc37b99eb1dcac45a7216661f96c60422` | ✅ Full cycle | create pool → psm_mint → psm_redeem tested |
| **VLT (v4 legacy)** | `f1f40d151849f93dea6d78fddc8aa189a3b39f0606926bc1aa933d85e878ee86` | ⏸ Legacy | Asset: `6a529801...` — incompatible with XelisVaultMiner |
| **VLTToken v5** | `7be7519ee8b540b40268a9c02d03bff89f1269bd3f46acff44d75c88dd6d9d56` | ✅ New VLT | Minter pattern, asset: `09b367e4...` |
| **XelisVaultMiner v2** | `fd370918fe99b8dd04804e3731b1b1aa6d73595a9a336b59d67063c2b52758d4` | ✅ Configured | VLT, asset, treasury set |
| **Timelock v5** | `bf6c0004993d50d0edc31eb38cebad38aa95e522040c9ea1d48cdea2eb2df597` | ✅ Deployed | Governance delay lock |
| **GovernanceVault v5** | `830ddfd85eb8ccd44678719cd32633806eba44aa4b455b3785ba04fb3a0b4aa9` | ✅ Configured | VLT contract + asset set |
| **Governor v5** | `f8a5880d02616085b26fa4d2a5888bf3328d8ab679af1ed0c90d693bff09a119` | ✅ Configured | GovVault + Timelock set |
| **GuardianMultisig v5** | `4c5783d36173e309fa47c746c37f865accf08c1a4dfee92ba84cc08392326e4a` | ✅ Configured | Timelock set |

---

## How It Works

### The xUSD Stablecoin

```
                  ┌──────────────┐     oracle price      ┌──────────────┐
                  │  VaultEngine  │◄──────────────────────│ PriceOracle  │
                  │  (CDP engine) │                       │ (XEL/USD)    │
                  └──────┬───────┘                       └──────────────┘
                         │
             deposit XEL │ borrow xUSD
             ↓           │ ↓
                  ┌──────┴───────┐     mint/burn xUSD     ┌──────────────┐
                  │    xUSD      │◄──────────────────────►│     PSM      │
                  │   (token)    │                         │ (stability)  │
                  └──────────────┘                         └──────┬───────┘
                                                                  │
                                                          mint xUSD │ redeem XEL
                                                          at oracle │ at oracle
                                                                  ↓
                                                            ┌──────────────┐
                                                            │    User      │
                                                            │  (you)       │
                                                            └──────────────┘
```

1. **Deposit XEL** into VaultEngine → creates a vault
2. **Borrow xUSD** against your XEL collateral (max ~66% LTV)
3. **Swap xUSD for XEL** via PSM at oracle price (0.5% mint fee, 0.1% redeem fee)
4. **Trade on VaultSwapV2** — constant-product AMM with TWAP-based dynamic fees
5. **Repay** your loan to unlock your XEL collateral

### The Price Oracle

```
  PriceOracle (083f50b2...)
  ├── entry 2: propose_price(price)     ← submit a new XEL/USD price
  ├── entry 3: execute_price()          ← activate after 3-block timelock
  └── entry 4: get_price(asset)         ← read current price (cross-contract)

  The daemon (xelis_vault_miner.py) runs this cycle automatically:
    1. Fetch XEL/USD from CoinGecko + MEXC
    2. propose_price(atomic_price)     → entry 2
    3. Wait 3 blocks
    4. execute_price()                 → entry 3
```

### Entry IDs Reference

Because `entry_id` in the XELIS VM = direct chunk index (not sequential entry
number), here are the actual callable entry IDs for each contract:

**PriceOracle**
| ID | Entry | Parameters |
|----|-------|------------|
| 0 | fn constructor | — |
| 1 | fn only_admin | — |
| **2** | **propose_price** | **(price: u64)** |
| **3** | **execute_price** | **()** |
| **4** | **get_price** | **(asset: Hash) → u64** |

**xUSD** (909576c1...)
| ID | Entry | Parameters |
|----|-------|------------|
| **3** | **mint_tokens(to, amount)** | (Address, u64) — cross-contract |
| **4** | **mint_split(to, amount, treasury, fee)** | (Address, u64, Address, u64) |
| **5** | **burn_tokens(amount)** | (u64) — cross-contract |
| 9 | set_vault_contract | (Hash) |
| 13 | set_psm | (Hash) |
| 19 | set_burner | (Hash) |

**VaultEngine** (667b165c...)
| ID | Entry | Parameters |
|----|-------|------------|
| 10 | deposit | (collateral: Hash, amount: u64) |
| 11 | borrow | (vault_id: u64, amount: u64) |
| 12 | repay | (vault_id: u64, amount: u64) |
| 13 | withdraw | (vault_id: u64, amount: u64) |
| 16 | get_queue | () |
| 17 | set_oracle_contract | (Hash) |
| 18 | set_xusd_contract | (Hash) |
| 19 | set_xusd_asset | (Hash) |
| 20 | set_treasury | (Address) |
| 27 | get_vault | (id: u64) |
| 28 | get_health | (id: u64) |
| 36 | is_paused | () |

**PSM** (9f266744...)
| ID | Entry | Parameters |
|----|-------|------------|
| **8** | **mint** | **(xel_amount: u64, min_xusd_out: u64)** |
| **9** | **redeem** | **(xusd_amount: u64, min_xel_out: u64)** |
| 21 | set_xusd_contract | (Hash) |
| 22 | set_xusd_asset | (Hash) |
| 23 | set_oracle | (Hash) |
| 24 | set_treasury | (Address) |

**VaultSwapV2** (1b669939...)
| ID | Entry | Parameters |
|----|-------|------------|
| 16 | create_pool | (asset_a: Hash, asset_b: Hash, is_psm: bool) |
| 17 | add_liquidity | (asset_a: Hash, asset_b: Hash, amount_a: u64, amount_b: u64) |
| 18 | swap | (asset_in: Hash, asset_out: Hash, amount_in: u64, min_out: u64) |
| **19** | **psm_mint** | **(xel_amount: u64, min_xusd_out: u64)** |
| **20** | **psm_redeem** | **(xusd_amount: u64, min_xel_out: u64)** |

---

## Quick Start

### Prerequisites

- Python 3.10+
- `requests` library (`pip install requests`)
- XELIS daemon + wallet running

### Connect to Testnet

```bash
# Run a local daemon (recommended)
./xelis_daemon --network testnet --rpc-bind-address 127.0.0.1:18081

# Or use public testnet node
# RPC:   https://testnet-node.xelis.io/json_rpc
# Explorer: https://testnet-explorer.xelis.io/

# Run the wallet (if running price oracle)
./xelis_wallet --daemon-address http://127.0.0.1:18081 \
  --network testnet --rpc-bind-address 127.0.0.1:18082
```

### Run the All-in-One Daemon

The `xelis_vault_miner.py` script handles everything:

```bash
python3 scripts/xelis_vault_miner.py \
  --rpc http://127.0.0.1:18081 \
  --wallet-url http://127.0.0.1:18082
```

This will:
1. Fetch XEL/USD price from CoinGecko + MEXC
2. Propose the price to the PriceOracle (entry 2)
3. Execute after the 3-block timelock (entry 3)
4. Repeat every 100 blocks

Options:
- `--dry-run` — log actions without submitting transactions
- `--verbose` — DEBUG-level logging
- `--enable-miner` — also handle XelisVaultMiner registration + heartbeats

### Interact with Contracts via Curl

```bash
# Read current XEL/USD price from oracle
curl -X POST http://127.0.0.1:18081/json_rpc \
  -H "Content-Type: application/json" \
  -d '{"method":"call_contract_read","params":{"contract":"083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6","entry_id":4,"args":["0000000000000000000000000000000000000000000000000000000000000000"]},"id":1}'

# Check vault health
curl -X POST http://127.0.0.1:18081/json_rpc \
  -H "Content-Type: application/json" \
  -d '{"method":"call_contract_read","params":{"contract":"667b165c8c9cd6cc3464378799e38b172e0f2e912f4b5c6202d37a8da3939bcc","entry_id":28,"args":[1]},"id":1}'
```

### Wallet RPC: Invoke Contract Example

```bash
# Propose price on the oracle
curl -u wallet:testpass http://127.0.0.1:18082/json_rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"build_transaction","params":{"invoke_contract":{"contract":"083f50b2eab5958ddacbb3c8e4e8943987d3bd337d7a56ae0763f6020734f8d6","entry_id":2,"parameters":[{"type":"primitive","value":{"type":"u64","value":"31176300"}}],"deposits":{},"max_gas":500000,"permission":"all"},"fee":{"fixed":10000000},"broadcast":true},"id":1}'
```

**Important parameter formats:**
- **u64**: `{"type": "primitive", "value": {"type": "u64", "value": "123"}}`
- **Hash**: `{"type": "primitive", "value": {"type": "opaque", "value": {"type": "Hash", "value": "hex..."}}}`
- **Address**: `{"type": "primitive", "value": {"type": "opaque", "value": {"type": "Address", "value": "xet:..."}}}`
- **permission**: must be `"all"` for any contract that makes cross-contract calls

---

## Repository Structure

```
xelis-vault/
├── contracts/           # Silex smart contract source code
│   ├── amm/             # PSM.slx, VaultSwapV2.slx
│   ├── oracle/          # PriceOracle.slx
│   ├── usd/             # xUSD.slx
│   ├── vault/           # VaultEngineV3.slx
│   ├── token/           # VLTToken.slx
│   ├── governance/      # GovernanceVault, Governor, Timelock, ...
│   ├── lending/         # LendingMarket, PeerLoan, ...
│   ├── insurance/       # InsurancePool, PrivateInsurance
│   └── ...              # 33 contracts total
├── scripts/
│   └── xelis_vault_miner.py   # All-in-one daemon (price oracle + miner)
├── docs/                # Whitepaper, guides, audit reports
├── install.py           # Environment setup
└── README.md            # This file
```

---

## Security Notes

- **`transfer_contract` before `burn_tokens`**: When a contract receives xUSD
  as a deposit and wants to burn it, it must first forward the tokens to the
  xUSD contract via `transfer_contract(xusd_hash, amount, xusd_asset)` before
  calling `burn_tokens`. The `burn_tokens` function checks the xUSD contract's
  own balance, not the caller's deposit. Without forwarding, it fails with
  "lowbal". Both PSM and VaultSwapV2 include this fix.

- **`entry_id` = chunk index**: The entry_id parameter is the direct chunk
  index in the compiled bytecode. `fn` and `hook` functions occupy chunk
  positions and shift entry_id values. Always refer to the entry ID tables
  above.

- **Cross-contract calls**: Use `pub fn` (not `entry`) for functions that
  will be called from other contracts via `Contract::call()`. The VM requires
  Access::All permissions.

- **Stable balance**: Custom assets (xUSD) need 24 blocks (~2 min) of
  confirmation before they can be used as deposits in a new transaction.

---

## License

MIT — see [`LICENSE`](LICENSE).
