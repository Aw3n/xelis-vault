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

## Phase 2+ — Pending

Following `docs/DEPLOYMENT_GUIDE.md`.
