# XELIS Vault — Operator Notes (AGENTS.md)

## ⚠️ LEÇON N°1 — get_deposit_for_asset est TRANSITOIRE (par-tx) — v12.1

Découverte clé du 2026-08-22 (validée par contrats probe déployés) :

- `get_deposit_for_asset(asset)` ne voit que les deposits passés **dans le MÊME tx**
  que l'entry exécutée. Retourne `None` sinon → `.expect("err")` panique `"err"`.
- Un « pré-dépôt » fait dans un tx SÉPARÉ crédite la **balance du contrat**
  (`get_contract_balance` l'affiche) mais **PAS le tracker per-caller**.
- `transfer_contract(A→B)` ne crédite PAS non plus le tracker du caller chez B :
  tout pattern « forward puis re-lecture du dépôt » cross-contract est **impossible**.

### Patterns qui FONCTIONNENT (validés on-chain)
```python
# PSM.mint (chunk 8) — deposit intégré au MÊME invoke :
p.wallet.invoke(PSM, 8, [val_u64(xel_amt), val_u64(min_out)],
                deposits={"0"*64: {"amount": xel_amt}})
# PSM.redeem (chunk 9) — idem avec l'asset xUSD en deposit
```
✅ mint 0.0595 xUSD + redeem 800k raw testés OK sur v12.1 (admin).

### Patterns CASSÉS en v12.1 (fix code requis en v12.2)
- `VaultSwapV2.psm_mint/psm_redeem` → `PSM.mint_cross/redeem_cross` : mint_cross
  relit `get_deposit_for_asset` alors que les fonds arrivent par `transfer_contract`
  → panic `"err"` systématique. Fix: lire `get_balance_for_asset` dans *_cross,
  ou faire porter le dépôt par le tx d'origine et ne plus relire.
- `PSM.redeem` : `burn_tokens` (chunk 5) brûle depuis la balance du **contrat xUSD**
  (pas du dépôt PSM). Workaround testnet: financer le contrat xUSD en xUSD
  (invoke entry quelconque + deposits). Fix propre: `transfer_contract(xusd_hash, …)`
  avant `call(5)` dans redeem.
- Dépôts orphelins: les pré-dépôts ratés ont laissé ~8 XEL de réserve dans PSM
  (utile pour les redeems, comptabilisé comme réserve).

## 🔧 Config oracle/miner ajustée on-chain (2026-08-22, admin)

| Clé | Contrat | Ancien | Nouveau | Entry |
|---|---|---|---|---|
| `hsb` hard_stale | StakedOracle | 100 blocs | **500** (~22 min) | chunk 56 |
| `hi` hb_interval | Miner | 100 | **900** | chunk 34 |
| `ht` hb_timeout | Miner | 300 | **4000** | chunk 35 |

Keeper (`scripts/oracle_keeper3.py`) recalibré économie:
- submit_price + poke `aggregate_now` toutes les **300 blocs** (~13.5 min < hsb)
- heartbeats toutes les **1000 blocs** (~45 min, entre interval 900 et timeout 4000)
- fee fixe **0.001 XEL/tx** (wallet accepte jusqu'à 0.0001; marge ×10)
- burn total ≈ **0.4 XEL/jour pour les 3 providers** (avant: ~8 XEL/h !)
- jitter ±1% (spread < max_dev 500bps), top-up providers: 50 XEL chacun le 08-22

## 🐛 Deadlock alreadysub (design oracle)

Si TOUS les miners soumettent avant l'ouverture de la fenêtre d'agrégation,
personne ne peut re-déclencher `try_aggregate` (le check `alreadysub` précède)
→ cycle bloqué indéfiniment (`sc_N=3`, cy figé). Le keeper poke donc
`aggregate_now` (chunk 17, sans access-control) AVANT chaque round de soumissions.
Fix contrat possible: déplacer try_aggregate avant le check, ou entry publique dédiée.

## 🧪 Résultats tests flux v12.1 (2026-08-22, admin wallet)

| Flux | Statut | Notes |
|---|---|---|
| Oracle E2E (submit→agg→rewards VLT) | ✅ | fg_0 frais chaque cycle keeper |
| PSM.mint XEL→xUSD | ✅ | 0.0595 xUSD (deposit même tx OBLIGATOIRE) |
| PSM.redeem xUSD→XEL | ✅ | nécessite xUSD contract financé (voir bug burn) |
| VaultSwap.psm_mint | ❌ | bug forward+re-read → v12.2 |
| VE3.deposit (vault 2 XEL) | ✅ | vault créé, borrow/repay/withdraw à tester |

## 🛠️ Techniques de debug contract (éprouvées)

- `get_contract_logs {caller: <tx>}` montre `exit_error` mais **sans localisation**.
- **Contrats probe** = meilleur bissecteur : déployer un mini-.slx qui appelle
  directement le chunk suspecté (ex: `/tmp/probe_minter.slx` a validé xUSD chunk 4).
  - Compile: `xelis_compile_tool <in.slx> <out.hex>` (chunk map sur stderr)
  - Deploy: build_transaction `deploy_contract` fee 1e8, hash = tx hash
  - `set_minter(Hash, bool)` prend **2 params** (hash + enabled)
- Balance asset wallet: RPC wallet `get_balance` avec `params: {"asset": <hash>}`
  (sans params = XEL total).
- **Maturité UTXO**: xUSD fraîchement minté non spendable pendant ~60+ blocs
  → attendre ou tester des montants réduits.
- Daemon n'expose pas le revert reason via get_transaction; passer par logs/probe.

## Live Environment

- **Network**: testnet (block_version 6 → allows V0|V1; V7 will allow V1 only). Daemon v1.25.0 (`1.25.0-a39e295`, built from local `~/opencode/xelis-blockchain`).
- **Daemon RPC**: `http://127.0.0.1:18081/json_rpc` (no auth)
- **Wallet RPC**: `http://127.0.0.1:18082/json_rpc`, basic auth `wallet:testpass`
- **Admin**: `xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v`
- **Processes**: daemon `./xelis_daemon --network testnet --dir-path /Users/adrien/xelis/data/`, miner (8 threads), wallet v1.25.0 binary `/Users/adrien/xelis/xelis_wallet` (`--wallet-path /Users/adrien/xelis/wallet_v125`). LaunchAgents: `com.xelisvault.daemon`, `.miner`, `.stack`, `.keeper`, `.provider18082/18084/18085`. **Unloaded the keeper+providers on 2026-08-20 (they spammed StakedOracle entry 16 submit_price → `alreadysub` every block, flooding the mempool and blocking admin txs from confirming). Restart only after fixing the subscribe-once logic.**
- **Wallet nonce**: after a daemon restart the wallet's stored nonce lags the chain; poll `get_nonce` (wallet RPC) between txs and wait for it to advance, or restart the wallet (fast with `--precomputed-tables-path`).
- **Deployment helper**: `/tmp/deploy_ops.py` (`deploy()`, `invoke()`, `get_data()`, `val_*` value builders).
- **Block time**: ~2.7s. Wait 5–12s between sequential TXs (proof-verification race → `Proof verification error`); nonce race → `Invalid TX ... nonce, got X expected Y` — both fixed by sleeping and retrying once. "Contract not found" right after deploy → wrong hash or too soon; cross-check with `cur_<Name>` in the registry.
- **Registry (ContractRegistry `840b81...`)**: register (entry 3) is ONE-WAY per name (`exists` revert); upgrade (entry 4, admin) enforces 720-block cooldown (`UPGRADE_TOPO_PREFIX`, unlock = register topo + 720). Upgrades preserve `prev_<Name>` for rollback. Names registered (count 33): ContractRegistry, ComplianceModule, VLTToken, xUSD, FaucetContract, XelisVaultMiner, StakedOracle, MinerPool, InterestRateModel, VaultEngine, SavingsRate, FlashLoan, FlashCallback, **VaultSwap** (not "VaultSwapV2"), PSM, LendingMarket, PeerLoan, SyndicatePool, SealedBidAuction, PrivacyMixer, AssetVault, TreasuryVault, RevenueShare, Payroll, InsurancePool, PrivateInsurance, GovernanceVault, Timelock, Governor, GuardianMultisig, OracleGovernance, VaultChat, FounderVesting4y, FounderVesting10y, FeeDistributor, MinerDelegation.
- **Current `cur_<Name>` hashes (registry authoritative, 2026-08-21)**:
  - VaultEngine: `4c10cf5f37b77c31a099819cf13bde43fe45e374fcf13c5c5f7578978ef969c9`
  - PSM: `3456fc47707447403b2bff56d8052e706575665d79fcf121c930d068ba1e6d11` (mint works; redeem fixed in source - `burn_tokens` called directly)
  - VaultSwap: `dbff590caeb56d7d287279772a322ef62170616abfafa24f7a0bf2d2262a02c7`
  - PrivacyMixer: `534c86a90ee1acac2da96b786fe00311d2e176608488668220c8bef9e96825bb`
  - SavingsRate: `5839e0158fb0965030b7a8575b4db38c22b6d69a3f0bb6262f322db9a07f55b0` (reentrancy fixed: `release_reentrancy()` added)
  - GovernanceVault: `65138ab138ff0f3a73852b54767e23b84c20a110bc62f59ca09b678eaef71d56`
  - InsurancePool: `bc74bae34e763895ed5795ba540ba1e60926777782b84b9d815707835962b8da` (newly deployed 2026-08-21, ADMIN_KEY=`adm`, configured & registered)
  - xUSD: `87242c12262bf4d7144842a06e91d96af53e5ce5b786e10ccb5c687be4658ae8`
  - xUSD asset: `a04b10a46698c97f3e465882dee5827e62360c30060f33f3604179769bc65100`
  - StakedOracle v3: `159594c8a5a856c9bc1063271ce8930500f1cab6fcc0e2bf604c78561ec09605`
  - Registry: `840b810c32f24b516ba5d65accef8cb706355e076a2c41ea98f2afce009f1a14`
- **VaultEngineV3 config**: set_registry=40, set_xusd_contract=41, set_xusd_asset=42, set_treasury=43 (Address). **xUSD perms (chunks 18=set_minter, 19=set_burner; set_minter also sets bu_)**: registered True for VaultEngine `4c10cf5f...`, PSM `3456fc47...`, VaultSwap `dbff590c...` (2026-08-20). Without burner → `notburner` on repay/redeem; without minter → `notminter` on mint_split (skip only if caller == xUSD admin).
- **StakedOracle (v3) config**: set_registry=46, set_miner_contract=44, add_feed_entry=10, pause=34 (All, not 33). Miner `register_service` entry 31 takes service_id **1..=8** (`0` → `badservice`); stored key `svc_<contract_hash.to_hex()>` = service id. Oracle holders set_oracle: VaultSwap=37, PSM=23, LendingMarket=29, PeerLoan=15, SyndicatePool=19 (all point to v3).
- **Treasury notes**: all `set_treasury` setters take an **Address** (temp = admin) EXCEPT FeeDistributor (Hash → TreasuryVault). TreasuryVault is a contract (hash) → cannot be set via Address-typed setters; fees accrue to admin wallet until a future fix. TreasuryVault has NO set_registry (guide stale); constructor sets admin+1 signer+quorum 1. RevenueShare `set_vlt_asset` is actually `set_share_token` (entry 8).
- **Contract funding**: mint paths (VLTToken.mint_to_entry=27, xUSD) take Address — to fund a CONTRACT, invoke any of its entries with `deposits: {"<asset_hash>": {"amount": N}}` (ContractDepositBuilder shape; plain int is rejected). Verified on FounderVesting (500k VLT each).
- **VaultChat**: `set_miner_contract`/`set_registry` are pub-fns (All chunks) — NOT externally invokable; miner reward wiring needs the Governor/Timelock proposal path (Timelock.submit_proposal/execute can cross-contract-call All chunks). No registry reference exists in VaultChat.
- **MinerDelegation** (entry set_miner_own_stake=14) is only_miner_contract — configurable only from miner flow. Miner register_service (31) ids: 1=oracle, 2=chat (CHAT_SERVICE_ID), 0 → `badservice`; key `svc_<contract_hash>`.
- **VM patch (CRITICAL)**: `ExitValue::is_success()` in `xelis_common/src/contract/vm.rs` returns `true` for all `ExitCode` (not just 0). Non-zero returns from entry points are **values** (ids, amounts), never errors. Errors use `require()` → `ExitError`. Applied 2026-08-20, daemon rebuilt & restarted.
- **PSM fix (2026-08-21)**: `redeem` now calls `burn_tokens` (chunk 5) directly instead of `transfer_contract` + `call(5)` — the caller's deposit is already in PSM balance. Redeem works for small amounts (< PSM XEL reserve).
- **InsurancePool (new 2026-08-21)**: deployed `bc74bae3...`, ADMIN_KEY=`adm` (was `a` conflicting with ASSET_KEY), set_asset=xUSD, set_registry=REG, registered as cur_InsurancePool. Stake/unstake work.
- **SavingsRate fix**: `release_reentrancy()` added before `return 0` in deposit/withdraw (reentrancy guard was stuck on `RG_ENTERED`).
- **FaucetContract fix**: `distribute` entry is chunk 16 (not 6), takes `Address[]` via sequence ValueCell.
- **VM nonce sync**: `WalletClient.invoke` waits for wallet nonce to catch up to daemon nonce before building, then waits for nonce advance after confirm.
- **xUSD UTXO maturity**: freshly minted xUSD not spendable immediately (~60+ blocks / ~3 min). Tests use 180s waits and partial amounts.

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

# v11.5 BUILD LOG (Super Z audit fixes applied + compile fixes)

## Compilation status — 34/34 core contracts OK (commit adb13f0 + local fixes)

Fixes applied on top of adb13f0 (Silex requires fn/const defined BEFORE use; len() returns u32):

1. **AirdropTracker.slx**: moved `fn build_leaderboard_index` before `entry finalize_distribution`
   (was called at line 623, defined at 721 → "No matching function found").
   Also: `require(!s.load(K).unwrap_or(false))` split into typed let + require;
   `emit_event(... s.load(QUALIFIED_COUNT_KEY).unwrap_or(0).to_string(...))` split into typed let.
2. **FeeDistributor.slx**: moved `fn is_authorized_fee_source` before `fn only_protocol_contract`;
   loop var `let i: u64` → `u32` (names.len() is u32).
3. **VaultChat.slx**: moved `const RELAYER_BOND_PREFIX` + `const MIN_RELAYER_BOND` from line ~2229
   to top constants section (used at line 521 by set_relayer F-13 fix).
4. **FaucetContract.slx**: `xel_amount * addresses.len()` → `* (addresses.len() as u64)` (2 sites).

AnalyticsCollector NOT in the 38-core deploy list (DO NOT DEPLOY YET) — left untouched.

## Next: regenerate docs/entry_chunk_ids.json for the 34 core contracts, then deploy
## per docs/DEPLOYMENT_GUIDE.md phases 1–8,10–13 (Phase 9 Insurance SKIPPED per owner).

## ✅ Chunk map régénéré (docs/entry_chunk_ids.json)
34 contrats core, 1031 chunks Entry/All mappés depuis le compile tool (sortie sur STDERR,
pas stdout — piège subprocess). Bytecodes dans /tmp/deploy_<Name>.hex et /tmp/chunkmap_<Name>.hex.

## PROCHAINE ÉTAPE: déploiement phases 1-8, 10-13 (Phase 9 Insurance SKIPPED)

# v12 FULL REDEPLOY (v11.5 code) — en cours
Orchestrateur: deploy/deploy_v12.py (--phase N), état: docs/deployment_state.json.
AirdropTracker patché v11.6: set_authorized_recorder(Hash,bool) + only_authorized_recorder
via get_contract_caller()/to_hex() (l'ancien check Address ne pouvait jamais matcher un contrat).
PHASE 1 ✅ ContractRegistry=ec60bb78…83194 | ComplianceModule=3eb327fd…69ed (+set_registry ok)
PHASE 2 ✅ VLTToken=0b0f5cfb…9524 VLT_ASSET=daa3981d…f387d | xUSD=8154335a…771c8 XUSD_ASSET=0daf60ef…ac85c | Faucet=0baaa0c6…36d5a
⚠️ Bug substring dans deploy_v12.py extract_new_asset — state XUSD corrigé à la main. NE PAS réutiliser tel quel.
PHASE 3 ✅ Miner=ba27f8e6…af3e7 Oracle=15247c0a…9f27 (+feed XEL/USD svc1) MinerPool=ee96c17b…73c35
deploy_v12.py: invoke() resumable via STATE["steps"] (label@contract12). Fixes: val_u8 decimals, register_service(u8,hash).
PHASE 4 ✅ IRM=3ccdfce4…068c(rates 50/1000/5000/8000) VE=b916b7a4…5ec9(minter+burner xUSD) Savings=4841e688…1c88(minter) FL=a9d2c504…e4bb CB=8cae8f57…bcdb4(+set_flash_loan chunk4 ajouté au script)
VE: oracle résolu via registry "StakedOracle" — pas de set_oracle.
PHASE 6 ✅ LendingMarket=01c57670…bda2 PeerLoan=132e270d…0942 SyndicatePool=4a04cdc0…6e1b
⚠️ Pas de set_irm sur LM v11.5 (IRM par pool dans create_pool) — écart vs guide documenté.
PHASE 11 ✅ VaultChat v11.6=0bfc1b24…2097 (nouveau chunk set_vlt_asset=96; ancien 1be87b9e… abandonné)
Admin wallet: 700 000 VLT (airdrop testnet, distribution manuelle). Relayer bond 100 VLT (double stake cosmétique).
VLTToken.mint_to_entry=27 ; wallet doit tracker l'asset avant tout dépôt VLT.
PHASE 12 ✅ FV4y=7e64b686…abec(⚠️1M VLT, excès 500k verrouillé) FV10y=b4f48448…fd04(500k) FeeDistributor=fb26448c…95df MinerDelegation=1a7723fe…90f6f
phase12 patchée: instances par hash explicite (cache deploy() fusionnait les 2 vestings).
PHASE 13 ✅ AirdropTracker v11.6=e1f0ec8f…eb8d1 + 7 recorders (Hash) — DÉPLOIEMENT COMPLET
protocol.py: VLT/XUSD assets + 37 CONTRACT_HASHES v12. docs/DEPLOYMENTS_V12.md complet.
