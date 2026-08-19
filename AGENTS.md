# XELIS Vault — Operator Notes (AGENTS.md)

## Live Environment

- **Network**: testnet (block_version 6 → allows V0|V1; V7 will allow V1 only). Daemon v1.25.0 (`1.25.0-a39e295`, built from local `~/opencode/xelis-blockchain`).
- **Daemon RPC**: `http://127.0.0.1:18081/json_rpc` (no auth)
- **Wallet RPC**: `http://127.0.0.1:18082/json_rpc`, basic auth `wallet:testpass`
- **Admin**: `xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v`
- **Processes**: daemon `./xelis_daemon --network testnet --dir-path /Users/adrien/xelis/data/`, miner (8 threads), wallet v1.25.0 binary `/Users/adrien/xelis/xelis_wallet` (`--wallet-path /Users/adrien/xelis/wallet_v125`).
- **Deployment helper**: `/tmp/deploy_ops.py` (`deploy()`, `invoke()`, `get_data()`, `val_*` value builders).

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
