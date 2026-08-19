# XELIS Vault — Operator Notes (AGENTS.md)

## Live Environment

- **Network**: testnet (block_version 6 → allows V0|V1; V7 will allow V1 only). Daemon v1.25.0 (`1.25.0-a39e295`, built from local `~/opencode/xelis-blockchain`).
- **Daemon RPC**: `http://127.0.0.1:18081/json_rpc` (no auth)
- **Wallet RPC**: `http://127.0.0.1:18082/json_rpc`, basic auth `wallet:testpass`
- **Admin**: `xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v`
- **Processes**: daemon `./xelis_daemon --network testnet --dir-path /Users/adrien/xelis/data/`, miner (8 threads), wallet v1.25.0 binary `/Users/adrien/xelis/xelis_wallet` (`--wallet-path /Users/adrien/xelis/wallet_v125`).
- **Deployment helper**: `/tmp/deploy_ops.py` (`deploy()`, `invoke()`, `get_data()`, `val_*` value builders).
- **Block time**: ~2.7s. Wait 5–12s between sequential TXs (proof-verification race → `Proof verification error`); nonce race → `Invalid TX ... nonce, got X expected Y` — both fixed by sleeping and retrying once. "Contract not found" right after deploy → wrong hash or too soon; cross-check with `cur_<Name>` in the registry.
- **Registry (ContractRegistry `840b81...`)**: register (entry 3) is ONE-WAY per name (`exists` revert); upgrade (entry 4, admin) enforces 720-block cooldown (`UPGRADE_TOPO_PREFIX`, unlock = register topo + 720). Upgrades preserve `prev_<Name>` for rollback. Names registered (count 33): ContractRegistry, ComplianceModule, VLTToken, xUSD, FaucetContract, XelisVaultMiner, StakedOracle, MinerPool, InterestRateModel, VaultEngine, SavingsRate, FlashLoan, FlashCallback, **VaultSwap** (not "VaultSwapV2"), PSM, LendingMarket, PeerLoan, SyndicatePool, SealedBidAuction, PrivacyMixer, AssetVault, TreasuryVault, RevenueShare, Payroll, InsurancePool, PrivateInsurance, GovernanceVault, Timelock, Governor, GuardianMultisig, OracleGovernance, VaultChat, FounderVesting4y, FounderVesting10y, FeeDistributor, MinerDelegation.
- **Stored contract hashes** (authoritative — registry keys `cur_<Name>`; /tmp/deployed.json): VaultEngine v2 `2c22a613...` (v1 `1a818eff...` prev), StakedOracle v3 `159594c8...` (v2 `68435e...` prev), VaultSwap `03d3adea88c15e41...`, PSM `fb8609b547e52e13...`, LendingMarket `74809c24...`, PeerLoan `39de766f...`, SyndicatePool `6ac66dfa...`, xUSD `87242c12...`, miner `0dc49c50dabf9c97ee...`.
- **VaultEngineV3 (v2) config**: set_registry=40, set_xusd_contract=41, set_xusd_asset=42, set_treasury=43 (Address). Old VE1 minter/burner revoked on xUSD (mi_/bu_ = false).
- **StakedOracle (v3) config**: set_registry=46, set_miner_contract=44, add_feed_entry=10, pause=34 (All, not 33). Miner `register_service` entry 31 takes service_id **1..=8** (`0` → `badservice`); stored key `svc_<contract_hash.to_hex()>` = service id. Oracle holders set_oracle: VaultSwap=37, PSM=23, LendingMarket=29, PeerLoan=15, SyndicatePool=19 (all point to v3).
- **Treasury notes**: all `set_treasury` setters take an **Address** (temp = admin) EXCEPT FeeDistributor (Hash → TreasuryVault). TreasuryVault is a contract (hash) → cannot be set via Address-typed setters; fees accrue to admin wallet until a future fix. TreasuryVault has NO set_registry (guide stale); constructor sets admin+1 signer+quorum 1. RevenueShare `set_vlt_asset` is actually `set_share_token` (entry 8).
- **Contract funding**: mint paths (VLTToken.mint_to_entry=27, xUSD) take Address — to fund a CONTRACT, invoke any of its entries with `deposits: {"<asset_hash>": {"amount": N}}` (ContractDepositBuilder shape; plain int is rejected). Verified on FounderVesting (500k VLT each).
- **VaultChat**: `set_miner_contract`/`set_registry` are pub-fns (All chunks) — NOT externally invokable; miner reward wiring needs the Governor/Timelock proposal path (Timelock.submit_proposal/execute can cross-contract-call All chunks). No registry reference exists in VaultChat.
- **MinerDelegation** (entry set_miner_own_stake=14) is only_miner_contract — configurable only from miner flow. Miner register_service (31) ids: 1=oracle, 2=chat (CHAT_SERVICE_ID), 0 → `badservice`; key `svc_<contract_hash>`.

## Compilation

- Tool: `/Users/adrien/opencode/xelis-compile-tool` (`cargo build --release`, binary `./target/release/xelis_compile_tool`).
- Output hex now = **complete ContractModule** (version byte `01` + module serialized with V1 writer context). Do NOT prepend bytes — deploy as-is.
- Compile env = `build_environment::<DummyProvider>(ContractVersion::V1)`.
- Compile log (stderr) prints `chunk N: <Access>` list → source of truth for entry chunk indices.

## CRITICAL: entry_id = compiled chunk index

`entry_id` in wallet invokes is the **chunk index in the compiled module**, NOT the
source-order counter in `docs/ENTRY_IDS.md`. Chunk layout: hook 0 first, then internal/helper
chunks, then Entry chunks, then All chunks. Indexes differ per contract — always read the
compile log or `docs/entry_chunk_ids.json` (auto-generated map, all 51 contracts, 959 entries).

Example: ComplianceModule `set_registry` = chunk **14** (source order 9). Calling chunk 9
hit `update_merkle_root` → reverted with `notverifier`.

## Wallet RPC (v1.25.0) — build_transaction

Flattened `TransactionTypeBuilder`, **snake_case** keys at top level of params:

```json
{
  "deploy_contract": { "contract": "<hex>", "invoke": { "max_gas": 1000000 } },
  "fee": { "fixed": 100000000 },
  "broadcast": true
}
```

- If the module has a constructor (hook 0), `invoke` is **required** (else `INVALID_CONSTRUCTOR_INVOKE`). No constructor → omit `invoke`.
- Constructor params are NOT supported by DeployContractInvokeBuilder (only max_gas + deposits) — constructors must be param-less.
- Contract hash = deploy transaction hash (confirmed via `ContractDeployEvent`).
- Invoke: `"invoke_contract": { "contract": "<hex>", "max_gas": N, "entry_id": <chunk index>, "parameters": [...], "deposits": {}, "permission": "all" }`.
- Fee guidance: deploy `{"fixed": 100000000}`, invoke `{"fixed": 10000000}`. Gas: 1M for stores, 5M+ for cross-contract / heavy.
- Old (v1.22.2) wallet: enum key `"DeployContract"` + object `{"version","module"}` — obsolete, do not use.

## ValueCell JSON (adjacently tagged)

- u64/u128: `{"type":"primitive","value":{"type":"u64","value":"<decimal string>"}}`
- u8/u16/u32: `{"type":"primitive","value":{"type":"u8","value":1}}` (number)
- bool: `{"type":"primitive","value":{"type":"boolean","value":true}}`
- string: `{"type":"primitive","value":{"type":"string","value":"..."}}`
- Hash: `{"type":"primitive","value":{"type":"opaque","value":{"type":"Hash","value":"<hex>"}}}`
- Address: `{"type":"primitive","value":{"type":"opaque","value":{"type":"Address","value":"xet:..."}}}`
- bytes: `{"type":"bytes","value":"<hex>"}`
- Same shape for `get_contract_data` keys (daemon).

## Daemon RPC reads

- `get_contract_data` `{contract: <hash>, key: <ValueCell>}` → `{data: <ValueCell>, topoheight, previous_topoheight}`; `No data found with requested key` = key never set.
- `get_contract_logs` `{caller: <tx hash>}` → `exit_error` entries reveal reverts (e.g. `notverifier`). Sometimes transient "Data not found on disk" right after execution — retry after a few seconds.
- `get_contract_module`, `get_contract_balance` available. NO simulation/invoke dry-run method on daemon RPC.

## Deployment guide

- Order + config steps: `docs/DEPLOYMENT_GUIDE.md` (13 phases, 37 core contracts; +14 brainstorming contracts exist in repo, 51 total).
- After EACH deployment/config: update `docs/DEPLOYMENTS.md`, commit to GitHub.
- Record tx hashes as contract addresses. Verify state via `get_contract_data` after each config step.
