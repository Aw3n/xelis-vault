# VaultChat — Complete Guide (v8.0)

## The Telecom Operator Model

VaultChat works like telecom operators. Each relayer is an independent business.

### How It Actually Works

```
Alice sends "Hello" to Bob. Alice uses Relayer A. Bob uses Relayer B.

1. Alice's CLI encrypts "Hello" with Bob's public key
2. Alice's CLI sends to Relayer A (P2P, <1 second)
3. Relayer A:
   - Checks: does Alice have free credits or a paid plan? (on-chain)
   - If yes: adds message to their local batch
   - Every ~80 minutes: stores batch on-chain + anchors Merkle root
   - Forwards P2P to Relayer B (so Bob gets it instantly)
4. Relayer B:
   - Receives P2P from Relayer A
   - Forwards to Bob (<1 second if online)
   - Syncs message into their own storage (redundancy)
5. Bob receives: P2P (<1s) OR on-chain (next launch)
```

### Why Batching?

Each on-chain transaction costs gas (XEL). Storing each message individually would be expensive.

```
WITHOUT batching: 100 messages = 100 transactions = 100 × gas = expensive
WITH batching:    100 messages = 1 batch = 1 transaction = 100× cheaper

Relayer collects 100 messages over 80 minutes
→ Stores them all in ONE on-chain transaction
→ Anchors ONE Merkle root
→ Cost: 1 × gas (not 100 × gas)
```

Relayers set their own batch interval:
- Fast relayer: every 100 blocks (~8 min) → more reliable, more expensive
- Slow relayer: every 1000 blocks (~80 min) → cheaper, slightly less fresh
- Very slow: every 20160 blocks (~1 week) → cheapest, messages delayed

Users choose based on their needs (speed vs price).

### Free Tier — Limited Slots (First Come First Served)

Each relayer offers a LIMITED number of free slots per day.

```
Relayer A offers: 100 free slots/day, each with 50 free messages

7:00 AM: Alice claims slot #1 → gets 50 free messages
7:30 AM: Bob claims slot #2 → gets 50 free messages
...
3:00 PM: Slot #100 claimed by Zack → gets 50 free messages
3:01 PM: Dave tries → "No free slots left today, try tomorrow or buy a plan"
         Dave buys a plan instead ($0.01 VLT/message)

Next day: All slots reset, first come first served again
```

**Why this prevents abuse:**
- 100 slots/day = maximum 100 × 50 = 5000 free messages/day per relayer
- Even with 1000 wallets, you can only claim 100 slots
- The relayer pays gas for on-chain storage → self-regulates
- Relayer can reduce slots if abused (set to 10/day, or 0)

### Pricing — 100% Free Market

Each relayer creates up to 10 plans. They can change prices anytime.

**Plan types:**
| Type | What it gives | Example |
|------|---------------|---------|
| 0 (per_message) | Pay per message | 0.01 VLT per message |
| 1 (duration) | Unlimited for N blocks | 1 VLT for 30 days |
| 2 (message_pack) | N messages prepaid | 0.5 VLT for 100 messages |

**Buy for yourself OR for someone else:**
```
Alice buys a plan for Bob:
  buy_plan(relayer_A, plan_1, bob_address)
  → Alice pays
  → Bob gets the plan
  → Bob can send messages via Relayer A
```

This enables:
- Companies paying for employees
- Friends gifting subscriptions
- Family plans (one person pays for everyone)

### Relayer Reliability Score

The score is based on **batch count**, NOT individual messages.

```
Relayer A: 1000 batches anchored → score = 1000 → very reliable
Relayer B: 10 batches anchored → score = 10 → new relayer
Relayer C: 0 batches anchored → score = 0 → NOT reliable
```

**Why batch count (not message count)?**
- A relayer with no users sends 0 messages but still anchors empty batches
- This proves they're online and doing their job
- They don't lose reputation for having few users

**is_relayer_reliable(relayer):**
- Checks: has the relayer anchored a batch within 2× their interval?
- If interval = 1000 blocks, they have 2000 blocks before "unreliable"
- This gives grace period for network issues

### Blacklist System (Relayers Self-Police)

```
Relayer C says "free!" but never anchors batches on-chain.

1. Relayer A notices: C hasn't anchored in 3× their interval
2. Relayer A blacklists C: blacklist_relayer(C, "not_anchoring")
3. Relayer B does the same
4. Users check: get_blacklist_count(C) → 2 relayers blacklisted C
5. Users avoid C
6. C's messages are NOT synced by A or B (excluded from P2P)
7. C is isolated → effectively dead

→ Bad relayers are naturally eliminated by the community
```

### Anti-Cheat Summary

| Cheat | How it's prevented |
|-------|-------------------|
| Multi-wallet free abuse | Limited free slots per day (first come first served) |
| Relayer doesn't store on-chain | User verifies: `verify_message_stored()` |
| Relayer never anchors | Reliability score = 0, blacklisted by others |
| Relayer fakes reliability | Batch count is on-chain (can't fake) |
| User forges plan | Plans stored on-chain, verified by relayer |
| User sends without paying | Relayer checks on-chain before relaying |
| Relayer reads messages | E2E encryption (can't read) |
| Relayer forges sender | `store_message` uses `get_caller()` as sender |

### Key Recovery

Your chat key is **derived from your XELIS wallet key**:
```
wallet_key → HKDF-SHA256 → chat_key
```

- One key to manage (wallet key / seed phrase)
- If you lose chat key: regenerate from wallet key
- If you lose wallet key: you lose everything (keep your seed safe!)

### Message Speed

| Scenario | Time |
|----------|------|
| Both online (P2P) | <1 second |
| On-chain batch storage | Every 80 min (configurable by relayer) |
| Offline user recovery | Next time they launch xvault |
| Switch computer | Import seed → derive key → read on-chain |

### File Structure

```
~/.xelis-vault/chat/
├── keys/
│   └── identity.json          # Chat keypair (derived from wallet)
├── messages/
│   ├── inbox/                 # Received (decrypted)
│   ├── sent/                  # Sent (decrypted)
│   └── groups/                # Group messages
├── contacts.json              # Address book
├── pending/                   # Queued for relayer
└── relayer_peers.json         # Known relayer endpoints
```
