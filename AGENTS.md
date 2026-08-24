# XELIS Vault — Operator Notes (AGENTS.md)

## 🚨 FORK + ROLLBACK (2026-08-22) — chaîne canonique rétablie, redéploiement v12R

### ⚠️ FAUX MYSTÈRE "wallet cache corrompu" — résolu : c'était un revert silencieux
- **Symptôme** : soldes VLT gelés après des mints "confirmés" ; warnings
  `DAG reorg detected … deleting changes` à chaque bloc dans le log wallet.
- **Vraie cause** : un mint manuel de `2e15` atomiques (= **20M VLT**) dépassait la
  MAX_SUPPLY 10M → contrat reverté `supmax`. La tx se CONFIRME quand même (nonce
  consommé) mais ne crédite rien ; `WalletClient.invoke` brut NE vérifie PAS le
  revert (seul `Deployer.invoke` le fait via `revert_reason`). Le wallet affichait
  donc correctement 951 VLT.
- Les warnings `DAG reorg detected` sont du BRUIT NORMAL en DAG miné localement
  (coinbase admin à chaque bloc + réordonnancement topo de blocs frères) — présents
  aussi bien avant le rollback. Ne pas les prendre pour un fork.
- **Reconstruction wallet** (faite pendant le debug, utile à savoir) :
  seed récupérable via CLI interactif (`./xelis_wallet --wallet-path … --password …`
  puis commande `seed`, mot de passe redemandé). Recréation: stopper wallet,
  déplacer `db`, relancer avec `--seed "<25 mots>"`, puis RE-TRACKER les assets
  (`track_asset` VLT/xUSD) — le tracking est stocké dans le db, pas dans les keys.
  Backups: `/Users/adrien/xelis/wallet_v125/db.bak_frozen_0215`.



**Ce qui s'est passé** :
- Le nœud officiel `testnet-node.xelis.io` était **stalled à topo 155,716** ; notre daemon
  a miné une branche privée jusqu'à 174,941 (~19k blocs orphelins). Ancêtres communs
  vérifiés identiques aux topos 100k/140k/150k/155k.
- **TOUTES les déploiements v11 ET v12 sont morts** sur la chaîne canonique (audit:
  `get_contract_module` → `no contract module available` pour les 36 hash de
  deployment_state.json ET les hash v12 originaux).
- L'admin garde son historique ancien : **nonce canonique 4688**, solde **57,334 XEL**
  (vs 63,737 sur la branche forkée — la diff = récompenses minières perdues).

**Rollback exécuté** :
- Keeper tué, LaunchAgents stack+daemon déchargés, miner tué.
- Backup data dir → `/Users/adrien/xelis/data_forked_backup_*` (137 Mo).
- Resync from scratch: `./xelis_daemon ... --allow-fast-sync`
  ⚠️ **fast-sync et boost-sync sont MUTUELLEMENT EXCLUSIFS** (sinon erreur `Invalid config sync mode`).
  Fast-sync terminé en 1m37s, bootstrap metadata de 711 contrats externes.
- Daemon tourne via **nohup** (`launchctl bootstrap com.xelisvault.daemon` →
  `Input/output error`, agent à réparer). Log: `/tmp/xelis_daemon_fresh.log`.
- Miner relancé (plist `.disabled`, nohup PID ~69659): **blocs acceptés par le réseau** ✓,
  alignement vérifié local=officiel=155,746 avec hash identiques @155,744. Pas de re-fork.
  Version officielle: `1.25.0-a6ae4cd9` vs notre build patché `1.25.0-a39e295` — compatible.
- Wallet admin **redémarré obligatoirement** après rollback: il croyait nonce=0 alors que
  la chaîne attendait 4688 → `Invalid TX nonce`. Après restart, get_nonce renvoie 4688 ✓.

**Redéploiement complet "v12R" en cours** (orchestrateur deploy/deploy_v12.py) :
- État reset: docs/deployment_state.json vierge ; backup ancien état →
  docs/deployment_state_forked_0822.json.
- Fix bug deploy_v12.py phase3: `admin_addr` indéfini → remplacé par `ADMIN` import.
- Les hash v12R sont consignés au fil des phases dans docs/deployment_state.json +
  section « v12R REDEPLOY » ci-dessous.

## 🔧 FIX v12R — VLT max supply visible protocole (2026-08-22)

L'asset VLT du premier passage v12R a été créé avec `MaxSupplyMode::None` → l'explorer
affichait "no max supply" (le cap 10M n'existait qu'au niveau logique contrat, clé `ms`).

**Fix**: `contracts/token/VLTToken.slx` create_asset →
`MaxSupplyMode::Mintable { max_supply: MAX_SUPPLY }` (=10_000_000 VLT @8dp).
⚠️ Syntaxe Silex: variante avec payload = style STRUCT `Mintable { max_supply: X }`,
PAS `Mintable(X)` (erreur `unexpected type 'MaxSupplyMode'`).
Bytecode recompilé → /tmp/deploy_VLTToken.hex ; entry chunks 4–27 inchangés.
Redéploiement complet relancé depuis la phase 1 (registry neuf ⇒ noms libres).
Ancien état partiel archivé: docs/deployment_state_v12R_partial_maxsupply0.json.
xUSD reste volontairement en MaxSupplyMode::None (stable adossé au collatéral).

## ✅ Tests E2E v12R (2026-08-23, passe complète)

| Flow | Résultat | Notes |
|---|---|---|
| PSM.mint / redeem | ✅ | redeem exige le **contrat xUSD financé en xUSD** (burn depuis SA balance, pattern v12.1 confirmé). Refill: invoke idempotent `xUSD.set_registry`(13) + dépôt attaché |
| VE3 deposit→borrow→repay→withdraw | ✅ cycle complet x2 | health checks validés (2 `unhealthy` correctement levés). COUNTER "n" démarre à 1 → vault#1 = premier |
| SavingsRate deposit/withdraw/claim | ✅ | |
| VaultSwap create_pool/add_liq/swap | ✅ | `cbtrip` = circuit breaker TWAP (max_vol 1000bps) → pour 1er swap sur pool neuf: set_max_volatility_bps(32) temporaire |
| PrivacyMixer deposit ×3 + auto-mix | ✅ | mix auto au 3e dépôt (threshold=3). refund impossible en test: timeout min 17280 blocs (1j) |
| Faucet.distribute | ✅ | **chunk 6** (16=set_guardian!). Arrays RPC: `{"type":"object","value":[val,…]}` |
| GovernanceVault stake/unstake | ✅ | stake ids démarrent à 0; unstake avant lock → "locked" (correct) |
| FounderVesting claim | ✅ | "cliffnotpassed" (correct) |
| MinerDelegation.register_profile | ✅ | `(name:str, description:str, commission_bps:u64)` |
| VaultChat.register_session | ✅ | |
| Oracle prix réel + heartbeats providers | ✅ | $0.2165, rewards protocole XEL reçus par providers (+45 XEL chacun) |

### 🔧 Fixes appliqués pendant la passe
1. **PSM.set_oracle(23) + VS.set_oracle(37) manquaient** → ajoutés à deploy_v12.py
   phase5. Sans eux: PSM.mint revert `err`, swap sans prix.
2. Encodage JSON-RPC des arrays (Silex): variante **`object`** avec value=list de
   ValueCells (`{"type":"object","value":[…]}`); variantes RPC acceptées:
   primitive/bytes/object/map UNIQUEMENT.
3. Maturité balances chiffrées ~60 blocs APRÈS chaque mint — les attaches de
   dépôts échouent (`lowbal`/proof error) si on réutilise des fonds tout frais.

## ✅ Reconfiguration post-v12R (2026-08-23, complète)

| Élément | État |
|---|---|
| Config oracle/miner | hsb=500 (chunk 56), hi=900 (34), ht=4000 (35) ✓ |
| Faucet | VLT wiring (12/13), claims 100XEL+100VLT (7), financé **40k XEL + 500k VLT** ✓ |
| Providers p1/p2/p3 | fund 1100 VLT + 5 XEL chacun → `register_miner` (15) stake 1000 VLT mask=1 ✓ |
| PSM réserve XEL | **100 XEL** via invoke get_reserves_entry(10)+deposit ✓ |
| protocol.py | VLT/XUSD assets + 36 CONTRACT_HASHES v12R ✓ |
| cli_backend.py | _FALLBACK régénéré depuis deployment_state.json ✓ |
| Keeper oracle | nohup `scripts/oracle_keeper3.py`, **prix réel** CoinEx+MEXC médiane $0.2107, submit x3 OK, feed `fg_0=[21070000,…]` ✓ |

⚠️ Pièges rencontrés (NE PAS REFAIRE):
- `Faucet.refill_vlt` (chunk 5) prend **1 param u64** ET le transfert se fait en attachant
  le dépôt au même invoke (l'entry ne fait qu'émettre l'event).
- Pour créditer un contrat en XEL/VLT: invoquer n'importe quelle entry **sans param**
  du contrat cible (ex chunk 10 get_reserves_entry pour PSM) avec `deposits={…}`.
- Les warnings wallet `DAG reorg detected … deleting changes` sont normaux en DAG
  miné localement — voir section « FAUX MYSTÈRE » ci-dessus.

## ✅ v12R REDEPLOY — hash définitifs (2026-08-22, après fix max supply)

| ContractRegistry | `19161543b9e5aef00c5a3e226058b946d847c78941f0c89e9b996c6332204970` |
| ComplianceModule | `1c0f143207c24d3b3e7fd04000cd1425e498505171de45ca980238e9f71c7f4a` |
| VLTToken | `020f228fbd61e3a6cd2d570083e14c02f7073f293c79ee4059359b896e217d84` |
| xUSD | `4836190ca2f2278cfc3e8ad8c7e05bbd0070de253c64615f6eea2c19885063a1` |
| FaucetContract | `0169707c19522269e8126edf36066e2c83c384e8c31f8072667f7cfad06631ec` |
| XelisVaultMiner | `6c70647e233dd634aa05cd6bdca06b521947c4c682d7decac0700d8a79d4b024` |
| StakedOracle | `e89bc25043c320fdac9c2030bc99e4b5bd94c9e0043132d10f66cd93576fa515` |
| MinerPool | `de744e0ccf45252070eb8fe83d0d16d36736ab7af1014a69405f358fb63c439b` |
| InterestRateModel | `e9f716b07628fb8793adf3e20142348082a5021d671f316dad1e02cfb70f9c6d` |
| VaultEngineV3 | `844cab735a8156f55c3055c2ff56a6824ad6d55b32f7dfb866655bde2bfa2054` |
| SavingsRate | `139caff55ca74911eb0c2631e5aab623a53ee56c7b24143328ecef3a610a9738` |
| FlashCallback | `a84fc6d305b4ed1a6e15c310461799172272ec1cabf209316e724c3ede420f40` |
| FlashLoan | `f8505eb95c5bb070e4f2a7f2d80826e13d140d2ee03b6bfdfaf1b7772c4be9f4` |
| VaultSwapV2 | `5defc37154200f1cabb5b5fa43510565ab791e34b20f2cf4132ec7d9ac4e2041` |
| PSM | `977ddf73305dd21c29ffbe69dc2bdb29a12a62f4ff8bbc3140cafd4b51d5c2e1` |
| LendingMarket | `cb8f489382368b2f1b27bffcba346ede50aa180ebefac89ac444995bc95255bc` |
| PeerLoan | `ec1ed4f280fef7cd7b13cb0231be12cfb53ddc57b38eaa822e00497221d82d36` |
| SyndicatePool | `5980cbd860081e613d32fd86d1c474fd798c8a7da262177078ad2eeb8dcb5cb0` |
| SealedBidAuction | `ac0c5a4e22a8348d3e98ff6183fdab23117f06f4a154098c1d7c84b24c3097f5` |
| PrivacyMixer | `d54cc19be3d16a86a3849be4389e44a9c123ebb0042a88e94f4e91893f940ab8` |
| AssetVault | `d16f7671f3e5399e1da826f9c4743f6fd5161e54048c945da6bea25d1032ff64` |
| TreasuryVault | `01d3851249e13354465766306e65be15497a9a9df6f46e35fe417879c4a5ab84` |
| RevenueShare | `49c363dae4d32473d6d3c26ce0482cf735f7d656c665094002c1d21a6978c94b` |
| Payroll | `44ce12fb3d143f360c84664fe4849f01fb31ce5b45aebda38b037c70b4079b30` |
| GovernanceVault | `52cb2f100984319c7f41bbec03fb3e7679279eafdd4abb44ff5d8fdd7631cf97` |
| Timelock | `b925d8e30ccd7bcffdc1376a6aecd8daaaa71603a3d0a4c9413d9e4a8ed11082` |
| GuardianMultisig | `9792a5894877a5982c9efdfb91f94c1536fe5f21c017a56c59691776413e4929` |
| Governor | `608eec92282bcba466e88d7e70d616be5653e9a120997866d738838e783862c3` |
| OracleGovernance | `bab86ca4a01c3250ce90b5c5d569b87ab221a212321848e104eb89500c28c953` |
| VLT asset | `3f1f9a3c0a90a0a548670a069e8edad5c0c20914b20b289426b2857c6715f58f` |
| XUSD asset | `be39794c4a32f231d410c8be3a4d9e80455c667d902c5edf8527dea52533356e` |



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
| PSM.mint XEL→xUSD | ✅ | 0.0595 puis +10.0485 xUSD (deposit même tx OBLIGATOIRE) |
| PSM.redeem xUSD→XEL | ✅ | nécessite xUSD contract financé (voir bug burn) |
| VE3 deposit/borrow/repay/withdraw | ✅ | CYCLE COMPLET vault#1: 2 XEL collatéral, borrow 0.03, repay full, withdraw OK |
| VaultSwap create_pool / add_liquidity / swap | ✅ | pool XEL/xUSD 0.4:1.98 @ prix oracle; swap 0.002 XEL OK |
| VaultSwap.psm_mint / psm_redeem | ❌ | bug forward+re-read → v12.2 |
| SavingsRate deposit/withdraw | ✅ | 0.015 déposé, 0.01 retiré |
| Faucet refill/set_claim_amounts/distribute | ✅ | claim réduit à 1 XEL + 5 VLT/user (default 100 XEL trop gros) |

### Pièges rencontrés pendant les tests (NE PAS REFAIRE)
- **Unités prix**: oracle 4,950,000 raw = 0.0495 $/XEL → 203 XEL ≈ 10 xUSD
  (PAS 2 !). min_out en RAW xUSD 8dp.
- **VaultSwap CB**: `toobig` = swap > max_swap_pct du pool; `cbtrip` = écart
  prix exécution vs TWAP > max_volatility_bps (default 1000). Sur un mini-pool,
  même 5% du pool trip le CB → swiper ≤1% du pool ou élargir la config (entry 32).
- **Address[] en paramètre RPC**: format tableau ValueCell =
  `{"type":"object","value":[val_addr(x), …]}` (ValueCell::Object(CellArray),
  xelis-vm/types/src/values/cell/mod.rs; Map = paires clé/valeur, PAS un tableau).
- **Lire une valeur retournée par un contrat**: la faire `return` depuis une
  entry probe → visible dans get_contract_logs champ `exit_code`.
- **Maturité UTXO ~60+ blocs**: après chaque mint/gros crédit, attendre ~4 min
  avant de re-déposer ("not enough funds … available: X" au BUILD).
- **VE3**: COUNTER_KEY="n" démarre à 1 → premier vault = v_1; repay brûle
  depuis le solde du contrat xUSD (comme PSM.redeem) → financer xUSD contract
  avant gros repay; treasury=admin ⇒ fees récupérées par l'admin au borrow.
- **Faucet**: refill_xel=4, distribute=6 (Address[] format object);
  defaults claim 100 XEL/user → set_claim_amounts(7) recommandé.

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
- **Processes (post-rollback 2026-08-22)**: daemon `./xelis_daemon --network testnet --dir-path /Users/adrien/xelis/data/ --rpc-bind-address 127.0.0.1:18081 --allow-fast-sync` via **nohup** (LaunchAgent `.daemon` cassé: `Input/output error`). Miner 8 threads via nohup (blocs acceptés par le réseau officiel ✓). Wallets admin 18082 + providers 18086/18087/18088 tournent en continu et se reconnectent au daemon. LaunchAgents: `com.xelisvault.daemon`, `.stack`, `.keeper`, `.miner.plist.disabled`, `.provider18082/18084/18085`. **Unloaded the keeper+providers on 2026-08-20 (they spammed StakedOracle entry 16 submit_price → `alreadysub` every block, flooding the mempool and blocking admin txs from confirming). Restart only after fixing the subscribe-once logic.**
- **Wallet nonce**: after a daemon restart or chain rollback the wallet's stored nonce lags (ou diverge) ; restart le wallet puis vérifier `get_nonce` == nonce attendu par la chaîne avant tout build. Pendant les déploiements, poll `get_nonce` entre txs.
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

# INCIDENT 2026-08-23 ~09:30-10:40 — "fork" testnet: nœud officiel GELÉ, pas nous
Symptôme: explorer/officiel figé à topo 170999 (37a286a7) pendant que notre daemon avançait (171962+).
Diagnostic: dernier bloc commun = 170999 EXACTEMENT (get_block_at_topoheight, PAS get_block qui n'existe pas).
Le nœud officiel refuse TOUT depuis 171000: blocs vides ET transactions (mempool=0 malgré 31MB envoyés).
Bloc 171000 = bloc vide sans tx → rien d'empoisonné, leur node est gelé/buggé en interne.
Le testnet dépend de notre hashrate: sans nos blocs la chaîne publique est à l'arrêt total.
Décision: rester sur NOTRE branche (plus lourde), miner+keeper relancés dessus.
Dès que le node officiel débloquera, le DAG convergera vers la branche la plus lourde = la nôtre.
Vérif convergence: comparer hash get_block_at_topoheight(171000) local (d76f76c1…) vs officiel.
État critique safe des deux côtés: tous les déploiements v12R + config sont ≤170999.
Seules les txs post-170999 seraient à rejouer si un jour on abandonnait notre branche (non prévu).
RPC daemon utile: p2p_status (best/median/our_topoheight), get_peers (bytes_recv/sent).
Miner PID nohup /tmp/miner.log; keeper nohup /tmp/oracle_keeper.log (plist .keeper obsolète, ne pas utiliser).

# RÉSOLUTION SYNC 2026-08-24 — daemon aligné via fast-sync + monitor auto-reset
Cause racine du blocage genesis-resync: txs historiques testnet à preuves ZK invalides selon code actuel
(bloc 42865 tx e50b4d30… nonce 324, puis nonce-drift be4eeec1… @47k). Aucun full-resync possible.
Solution finale (choix owner): daemon compilé depuis commit EXACT a6ae4cd9 (branche dev = leur build 1.25.0,
master est resté étiqueté 1.24.0!) + DB vierge + --allow-fast-sync vers 74.208.251.149 → aligné instantané.
⚠️ Le n° de version du binaire DOIT matcher le node officiel (get_info.version).
Monitor permanent: scripts/sync_monitor.py (nohup, log /tmp/sync_monitor.log) — compare local↔officiel
chaque minute; fork/stall persistant → wipe data/testnet + re-fastsync auto (cooldown 20 min).
Superviseur PTY dispo si commandes prompt nécessaires: /tmp/daemon_pty.py + echo cmd > /tmp/dcmd.
Miner/keeper/wallets: relancer SEULEMENT une fois le node officiel dégelé et stable.
