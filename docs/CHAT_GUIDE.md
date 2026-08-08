# VaultChat — Complete Guide

## How It Works — The Telecom Operator Analogy

VaultChat works like telecom operators (Orange, SFR, Bouygues). Each relayer is an independent operator.

### Key Principle: Each Relayer is Independent

```
RELAYER A (cheap)           RELAYER B (premium)       RELAYER C (free)
├── 0.001 VLT / message     ├── 0.01 VLT / message    ├── 100 free/day
├── 20 days = 0.1 VLT       ├── 30 days = 1 VLT        ├── then 0.005 VLT/msg
├── 100 msgs = 0.05 VLT     ├── 500 msgs = 2 VLT       ├── No subscriptions
├── 100 free/day             ├── 0 free (all paid)      ├── Must anchor every 500 blocks
└── Anchors every 1000 blocks └── Anchors every 500      └── Pays gas for free users
    blocks                       blocks
```

### What Each Relayer Decides (100% Free)

| Decision | Who decides | Can change anytime? |
|----------|------------|-------------------|
| Price per message | Relayer | YES |
| Subscription prices | Relayer | YES |
| Free daily limit (0-1000) | Relayer | YES |
| Which token (VLT or XEL) | Relayer | YES |
| Anchor frequency | Relayer | YES |
| Number of plans (up to 10) | Relayer | YES |

### What All Relayers MUST Do (Protocol Rules)

| Rule | How it's enforced |
|------|------------------|
| Store messages on-chain | Users verify: `verify_message_stored()` |
| Anchor Merkle roots | Users check: `is_relayer_reliable()` |
| Forward messages to other relayers | P2P sync (gossip protocol) |
| Send heartbeats | `relayer_heartbeat()` every 100 blocks |
| Respect plans bought by users | Plans stored on-chain, can't be tampered |

### Anti-Abuse: Why Free Abuse Doesn't Work

**Problem**: User creates 10 wallets → 1000 free messages/day

**Why it doesn't work**:
```
1. Each "free" message costs the RELAYER gas (XEL) to store on-chain
2. Relayer pays: store_message() → gas XEL
3. User pays: 0 (free tier)
4. If 10 wallets × 100 free = 1000 messages → relayer pays 1000 × gas
5. Relayer sees: "this address used 100 free, that one used 100 free..."
6. Relayer can: set free limit to 0, or require small XEL deposit
7. Relayer can: track IP/endpoint to limit abuse
8. Natural balance: relayer adjusts free tier based on abuse

→ The FREE TIER is a RELAYER COST, not a protocol cost
→ Relayers self-regulate (like telecom operators)
```

### Anti-Cheat: Relayer Doesn't Store On-Chain

**Problem**: Relayer says "free!" but doesn't store messages on-chain (saves gas)

**Why it doesn't work**:
```
1. Alice sends a message via "free" relayer C
2. Alice checks: VaultChat.verify_message_stored(alice, slot) → FALSE
3. Alice's message is NOT on-chain → not persisted → will be lost
4. Alice rates relayer C: 1 star
5. Other users check: get_relayer_rating(C) → 1.00
6. Other users check: is_relayer_reliable(C) → FALSE (no anchors)
7. Users avoid relayer C
8. Relayer C has no customers → disappears

→ Bad relayers are naturally eliminated by the rating system
→ Users can ALWAYS verify their messages are on-chain
```

### Message Flow — Step by Step

```
1. Alice (uses Relayer A) sends "Hello" to Bob (uses Relayer B)

2. Alice's CLI:
   a. Encrypts "Hello" with Bob's public key
   b. Sends to Relayer A (P2P, <1 second)

3. Relayer A:
   a. Checks: does Alice have free credits or a paid plan? (on-chain)
   b. If yes: stores on-chain: store_message(bob, ciphertext)
   c. Anchors batch: anchor_messages(merkle_root)
   d. Forwards P2P to Relayer B (so Bob gets it instantly)

4. Relayer B:
   a. Receives P2P from Relayer A
   b. Forwards to Bob (P2P, <1 second)
   c. Syncs the message into their own storage (redundancy)

5. Bob receives:
   a. P2P from Relayer B: <1 second (if online)
   b. OR on-chain: next time Bob launches xvault

6. If Relayer A disappears:
   a. Bob still gets the message from on-chain (stored by A before disappearing)
   b. OR from Relayer B (who synced it)
   c. Alice switches to another relayer

7. If ALL relayers disappear:
   a. Bob reads last 50 messages from on-chain
   b. No new messages until a relayer appears
   c. Messages are NOT lost (on-chain storage)
```

### Relayer Registry — How to Find Relayers

```
1. User queries: get_relayer_registry_count() → "5 relayers available"
2. For each relayer: get_relayer_from_registry(index) → address + endpoint
3. For each relayer: get_relayer_profile(address) →
   ├── Is registered?
   ├── Is online? (heartbeat)
   ├── Reputation score
   ├── User rating (1-5 stars)
   ├── Plans sold
   ├── Number of pricing plans
   └── Free daily limit
4. For each relayer: get_plan(relayer, 0..N) → plan details
5. User compares and chooses the best one
6. User calls buy_plan(relayer, plan_id) or just starts using free tier
```

### Key Recovery — If You Lose Everything

**Your chat key is derived from your XELIS wallet key.**

```
Scenario: Computer crashes, no backup of chat keys

1. You have your XELIS seed phrase (12/24 words)
2. You restore your wallet: xelis_wallet restore --seed "your seed"
3. You launch: xvault
4. The CLI:
   a. Reads your wallet private key
   b. Derives chat key: HKDF-SHA256(wallet_key, "xelis-vault-chat-v1")
   c. The SAME chat key is regenerated (deterministic)
   d. Reads last 50 messages from on-chain
   e. Decrypts each with your regenerated private key
   f. Saves decrypted messages locally

→ You recover EVERYTHING with just your seed phrase
→ No separate backup needed for chat
```

### Security Summary

| Threat | Protected? | How |
|--------|-----------|-----|
| Message interception | YES | E2E encryption (ChaCha20-Poly1305) |
| Relayer reads messages | YES | Only encrypted blobs visible |
| Forged sender identity | YES | get_caller() verified on-chain |
| Free tier abuse (multi-wallet) | YES | Relayer pays gas → self-regulates |
| Relayer doesn't store on-chain | YES | User verifies + rating system |
| Relayer disappears | YES | On-chain storage + other relayers |
| Censorship | YES | P2P off-chain + on-chain storage |
| Message tampering | YES | Tombstones + Merkle roots |
| Replay attacks | YES | Timestamp as associated data |
| User cheats on plan | YES | Plans stored on-chain |
| Relayer cheats on payment | Direct | Payment is direct (no escrow) |
| Lose chat key | YES | Regenerate from wallet seed |

### File Structure

```
~/.xelis-vault/chat/
├── keys/
│   └── identity.json          # Chat keypair (derived from wallet)
├── messages/
│   ├── inbox/                 # Received messages (decrypted)
│   │   └── xelis1abc....json
│   ├── sent/                  # Sent messages (decrypted)
│   │   └── xelis1xyz....json
│   └── groups/                # Group messages (decrypted)
├── contacts.json              # Address book
├── pending/                   # Messages queued for relayer
└── relayer_peers.json         # Known relayer endpoints
```
