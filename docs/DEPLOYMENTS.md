# Testnet Deployment Record

Live deployment state on XELIS **testnet** (block_version 6, V0/V1 contracts; daemon v1.25.0).

Operator: `xet:czr9q8k5xlzqdptq7n2vapyjfduldts6tw3e6apl99vknzvmu4zsq8z9j8v`
All contracts deployed as **V1** (version byte `01` embedded in module hex by the compile tool).

> Entry IDs for invokes = **compiled chunk indices** (see `docs/entry_chunk_ids.json`),
> NOT the source-order IDs listed in `docs/ENTRY_IDS.md`.

## Phase 1 — Registry + Compliance

| Step | Contract / Action | Address (tx hash) | Status | Topoheight |
|------|-------------------|-------------------|--------|-----------|
| 1.1 | Deploy ContractRegistry | `840b810c32f24b516ba5d65accef8cb706355e076a2c41ea98f2afce009f1a14` | ✅ deployed, ctor ok (admin/emergency stored, count 0) | 150714 |
| 1.2 | Deploy ComplianceModule | `7d20ea3646e5c308b9153353f68c24e8f161bc43392f092ea138a5498f132f78` | ✅ deployed, ctor ok | — |
| 1.3 | ComplianceModule.set_registry (entry chunk 14, reg = registry hash) | `ec493026ea1e8a1486368b2c49d8d6daf63f5e7b332e78fe9ecc94b9021d9794` | ✅ stored `reg` = registry hash | 150758 |

> Note: an earlier invoke used entry 9 (wrong chunk) → runtime error `notverifier`, no state change.
> Chunk indices are the source of truth for `entry_id`.

## Phase 2 — Token Layer

| Step | Contract / Action | Address (tx hash) | Status | Topoheight |
|------|-------------------|-------------------|--------|-----------|
| 2.1a | Deploy VLTToken | `efd53bfa46d9fbb7494cca716cd86990299851705d408fcbff0e05d00bb09ac6` | ✅ deployed | — |
| 2.1b | VLTToken.create_asset (chunk 9, +10 XEL deposit, 1 XEL burned) | `f581ff769d284f1f7ffaf80b6de8797027d244e822a967d722b621eebb99f1f9` | ✅ **VLT asset = `9d074e1b0c057dbd30897f10117e4feb1d8d6442306bc23ac763c87c9f73b89a`** | 150808 |
| 2.1c | VLTToken.set_registry (chunk 10) | `c93b6d36b01f5c6d06f355ff29dd0ac042fb9ba3ae992b566fa1c3833aaf58cf` | ✅ | 150811 |
| 2.1d | Registry.register "VLTToken" (chunk 3) | `5f45d3c72a6a2c2328446ddb6e852cb8c2b5694ac49630b39c345d5ee2dc8e0d` | ✅ `cur_VLTToken` stored, count=1 | 150812 |
| 2.1e | VLTToken.mint_to_entry (chunk 27): **500,000 VLT (airdrop share) → admin wallet** | `0826f873fb2177deeeac15f3bb8b82d819b5114559b4f702490f7c26c9a65e56` | ✅ admin holds 50,000,000,000,000 atomic; distribution left to operator | 150825 |
| 2.2a | Deploy xUSD | `87242c12262bf4d7144842a06e91d96af53e5ce5b786e10ccb5c687be4658ae8` | ✅ deployed | — |
| 2.2b | xUSD.create_asset (chunk 2, +10 XEL deposit, 1 XEL burned) | `e0b124a5a42914e3e0285f813df91005c4ce1bfd2bc4064f2f5df58c2e95ccfa` | ✅ **xUSD asset = `a04b10a46698c97f3e465882dee5827e62360c30060f33f3604179769bc65100`** | 150842 |
| 2.2c | xUSD.set_registry (chunk 20) | `863f6bc415783406e85e169ebea2e3c78fa06e5ccdd365a36098e87bebb32f4f` | ✅ | 150845 |
| 2.2d | Registry.register "xUSD" (chunk 3) | `97830346f1032ed2517aac7e96471f38b979fef671086af3e0c66d4e0e48fe51` | ✅ `cur_xUSD` stored, count=2 | 150848 |
| 2.3a | Deploy FaucetContract | `7da83d17c4db825083b4ae85ab95ff50654999ebf4847e284bcf11549f14256d` | ✅ deployed | — |
| 2.3b | Faucet.set_registry (chunk 14) | `9f6475eb02c90472eb2e17ec329342d7474d55eefe6b64e2b2e6abf21c156553` | ✅ | 150859 |

> VLT distribution note (operator decision): testnet airdrop contract skipped — the full 500k VLT
> airdrop share is minted to the admin wallet for manual distribution.
> Faucet refill deferred (operator-controlled VLT; refill later if desired).

## Phase 3 — Mining & Oracle

| Step | Contract / Action | Address (tx hash) | Status | Topoheight |
|------|-------------------|-------------------|--------|-----------|
| 3.1a | Deploy XelisVaultMiner | `0dc49c50dabf9c97ee2efaa76d17013922a89855f63233821ed6d4c445505cbf` | ✅ | — |
| 3.1b | Miner.set_registry / set_vlt_contract / set_vlt_asset (chunks 44/40/41) | `5489960b…` `31c9c3d3…` `ea8f243b…` | ✅ verified | 150903-150909 |
| 3.1c | Registry.register "XelisVaultMiner" | `a3e724d0cf1a46a0abdf45e75e8ea981cb816b5f8346a86ef2929735556dd6c4` | ✅ | 150910 |
| 3.2a | Deploy StakedOracle **v2** (added `add_feed_entry` wrapper — pub fn chunks are not externally invokable; v1 `c60dea03…` discarded, nothing referenced it) | `68435e505623b3cc4dbfd4d1c23191889f0970df82c3e184db36983dfadd394c` | ✅ | — |
| 3.2b | Oracle.set_registry / set_miner_contract (chunks 46/44) | `c250143d…` `72d05980…` | ✅ | 150960-150961 |
| 3.2c | Oracle.add_feed_entry (chunk 10): "XEL/USD", asset=zero, decimals=8, min=1, max=1e11 | `a6da6cee5bf7fc459aab6f8d5099e870c03993f10f906e25a91d17edc61eee1c` | ✅ feed 0 stored | 150965 |
| 3.2d | Registry.register "StakedOracle" | `b5f8c2bc3ca99c75898bcdb0092983ba229a33ae8838969e48907bde7c129d58` | ✅ | 150966 |
| 3.2e | Miner.register_service (chunk 31): service_id=1 → oracle | `a8b5227e8d5d5bf038074a2c85c57625ee9b8db9fe3ce03d44eb813ee1e12c77` | ✅ `svc_<oracle>=1` | 150970 |
| 3.3a | Deploy MinerPool | `86895d2f16fc293f3e29234b9daa6a0482be4a061e76265af049baa13e9bd275` | ✅ | — |
| 3.3b | MinerPool.set_registry / set_miner_contract / set_vlt_asset (chunks 27/25/26) | `5185bacd…` `4ac12cc0…` `2e705faa…` | ✅ verified | 150976-150980 |
| 3.3c | Registry.register "MinerPool" | `b48dae9de1674bfada944e6275ca819f6f2b3ee900d810c2bdf444565917e144` | ✅ | 150984 |

> Guide corrections applied (v11.x sources): `add_feed` → `add_feed_entry` wrapper added to
> StakedOracle (chunk 10); `set_authorized_service` → `register_service` (chunk 31).
> Registry count: 5.

## Phase 4 — Lending Core

| Step | Contract / Action | Address (tx hash) | Status | Topoheight |
|------|-------------------|-------------------|--------|-----------|
| 4.1a | Deploy InterestRateModel | `172214c5d10f967f73e3c12832b74a6b17ce05aa9d656936ce4be0d1fbd6e2de` | ✅ | — |
| 4.1b | IRM.set_rates (chunk 10): base=50, multiplier=1000, jump=5000, kink=8000 | `f77f9e3992d2b34b36c3f4557d244ee8388a7f2951e366a80d4c40cc205c27d1` | ✅ | 150988 |
| 4.1c | Registry.register "InterestRateModel" | `ed6d1ab019e290bf2572367d1dd419c315a0a936b230e988e769abb37978707c` | ✅ | 150994 |
| 4.2a | Deploy VaultEngineV3 | `1a818effa8a4eb5bac9ed4675e1be8abe93d438cc14d6297635bbeb75e471a53` | ✅ | — |
| 4.2b | VE.set_registry / set_xusd_contract / set_xusd_asset (chunks 40/41/42) | `f0758c00…` `c6dc8e44…` `d50ccfe9…` | ✅ verified | 151004-151008 |
| 4.2c | VE.set_treasury (chunk 43) — **temp = admin wallet** (TreasuryVault arrives Phase 8; mutable via set_treasury) | `e8046723…` | ✅ | 151013 |
| 4.2d | Registry.register "VaultEngine" | `61e05447988d41ffd347dca7e84a04506ef77113baa0bf74d1a57a91b5c0e742` | ✅ | 151016 |
| 4.2e | xUSD.set_minter / set_burner → VaultEngine (chunks 18/19) | `ab3d5d30…` `655c9240…` | ✅ `mi_`/`bu_` = true | 151017-151020 |
| 4.3a | Deploy SavingsRate | `a275a8e2cc97db7d5fb519c5d9a952fcaa9c36e55a5870339b468c7acc68c043` | ✅ | — |
| 4.3b | Savings.set_registry / set_xusd_contract / set_xusd_asset (chunks 17/14/15) | `d76557f6…` `f996b572…` `ef5a99c2…` | ✅ | 151036-151040 |
| 4.3c | Savings.set_treasury (chunk 16, temp=admin) | `38bcbcdb…` | ✅ | 151042 |
| 4.3d | xUSD.set_minter → SavingsRate | `76c3e250…` | ✅ `mi_`=true | 151048 |
| 4.3e | Registry.register "SavingsRate" | `014dc32aa2a91f317eb816269ec8eb6a1b1665ab75f8521ad729536480e487b3` | ✅ | 151050 |
| 4.4a | Deploy FlashCallback / FlashLoan | `f151220561b7d956fbd32b236111b6fc6c152c6a1d384c94b8bd5ea4fc76ea60` / `7dcbf096f4d6f30366316e38736eb75124a9b8054624a974d4cadae7f5edf729` | ✅ | — |
| 4.4b | FlashLoan.set_registry / set_treasury (chunks 14/13) | `75562737…` `34d785d2…` | ✅ | 151058-151062 |
| 4.4c | FlashLoan.verify_callback → FlashCallback (chunk 23) | `64c077dd…` | ✅ `vcb_`=true | 151068 |
| 4.4d | Registry.register "FlashLoan" / "FlashCallback" | `19a4452a…` `22d3c0f1…` | ✅ | 151069-151072 |

> Treasury is temporarily the admin wallet for VE/Savings/FlashLoan — swap to TreasuryVault when it deploys (Phase 8).
> Registry count: 10.

## Phase 5+ — Pending

Following `docs/DEPLOYMENT_GUIDE.md`.
