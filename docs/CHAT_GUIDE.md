# VaultChat — Complete Guide

## How It Works (Simple Version)

VaultChat is end-to-end encrypted messaging on XELIS. Nobody — not relayers, not miners, not even the protocol creators — can read your messages.

### Key Concept: One Wallet, One Key

You do NOT need a separate key for chat. The chat key is **derived from your XELIS wallet key**:

```
Your XELIS wallet private key
    │
    ▼
HKDF-SHA256(wallet_key, "xelis-vault-chat-v1")
    │
    ▼
Chat keypair (private + public)
```

- You manage ONE key (your wallet key)
- The chat key is generated automatically
- If you lose your chat key but still have your wallet key → regenerate the same chat key
- If you lose your wallet key → you lose everything (chat + funds)

### Sending a Message — The Full Flow

```
1. Alice types "Hello Bob" in xvault CLI
2. CLI reads Bob's public key from on-chain (VaultChat.get_session)
3. CLI encrypts: ChaCha20-Poly1305("Hello Bob", shared_secret)
4. CLI sends encrypted blob to Alice's chosen relayer (P2P)
5. Relayer stores on-chain: VaultChat.store_message(bob, ciphertext)
6. Relayer forwards P2P to Bob (if online) → <1 second
7. Bob's CLI decrypts with his private key
8. Bob's CLI saves locally: ~/.xelis-vault/chat/messages/inbox/alice.json
```

**Speed:**
- P2P (both online): <1 second
- On-chain storage: ~5 seconds (1 block)
- If Bob is offline: he gets it next time he launches xvault

### Message Routing — Who Carries What

```
Alice chose Relayer A and paid for a plan.

Alice → [encrypted] → Relayer A → [encrypted] → Bob
                         │
                         ├── Stores on-chain (persistence)
                         ├── Anchors Merkle root (earns VLT)
                         └── Syncs message to Relayer B (redundancy)

Bob does NOT need to use the same relayer as Alice.
Bob can use Relayer B, or Relayer C, or no relayer (just on-chain recovery).

Each user picks their OWN relayer. Messages flow:
  Alice → Alice's relayer → on-chain → Bob (reads from chain)
  Alice → Alice's relayer → P2P → Bob's relayer → Bob (if both online)
```

### Free vs Premium — How It Works

**Every user gets 100 FREE messages per day.** This is enforced ON-CHAIN (not client-side). After 100 messages, you need a plan.

### Relayer Pricing — 100% Free Market

Each relayer creates their OWN plans. They can have up to 10 plans simultaneously. They can change prices anytime. They are completely independent.

#### Plan Types

| Type | What it gives | Example |
|------|---------------|---------|
| `per_message` (0) | Pay per message | 0.01 VLT per message |
| `duration` (1) | Unlimited for N blocks | 1 VLT for 30 days |
| `message_pack` (2) | N messages prepaid | 0.5 VLT for 100 messages |

#### How a Relayer Sets Up Plans

```
Relayer A creates 3 plans:

Plan 0: per_message, 0.001 VLT each
Plan 1: duration, 0.1 VLT for 20 days (345600 blocks)
Plan 2: message_pack, 0.05 VLT for 100 messages

Relayer B creates 2 plans:

Plan 0: per_message, 0.01 XEL each
Plan 1: duration, 2 VLT for 30 days

→ Alice compares and chooses Relayer A (cheaper)
→ Bob chooses Relayer B (accepts XEL, Bob has no VLT yet)
```

#### How Users Buy Plans

1. User queries all relayers: `get_plan_count(relayer)` + `get_plan(relayer, id)`
2. User compares prices (visible on-chain, transparent)
3. User calls `buy_plan(relayer, plan_id)`
4. Payment goes **DIRECTLY** to the relayer (no escrow, no middleman)
5. The plan is stored **ON-CHAIN** linked to the user's address
6. The user can't tamper with it (it's on the blockchain)

#### How Plans Are Verified

When a user sends a message:
1. The relayer checks on-chain: `has_active_plan(user, relayer)` → is the subscription valid?
2. The relayer checks on-chain: `get_remaining_credits(user, relayer)` → any message pack credits left?
3. The relayer checks on-chain: `get_free_messages_remaining(user)` → still in free tier?
4. If any check passes → relay the message
5. If none passes → reject (user needs to buy a plan or wait for free reset)

**The user CANNOT cheat** because everything is on-chain. The relayer doesn't trust the client — it reads the blockchain.

### Relayer Sync — How It Works

**Relayers sync MESSAGES, not PRICES.**

```
Relayer A has: [msg1, msg2, msg3, msg4, msg5]
Relayer B has: [msg1, msg2, msg3]

Sync process:
1. B contacts A: "I have msg1, msg2, msg3. What do you have?"
2. A responds: "I also have msg4, msg5"
3. B downloads msg4, msg5
4. B verifies: do msg4, msg5 match the Merkle root on-chain? → YES
5. B now has: [msg1, msg2, msg3, msg4, msg5]

PRICES ARE NEVER SYNCED.
- Relayer A charges 0.001 VLT/msg
- Relayer B charges 0.01 XEL/msg
- They don't care about each other's prices
- They only sync messages (for redundancy)

If A disappears:
- B still has all messages
- A's users switch to B (or any other relayer)
- A's pricing plans are irrelevant (A is gone)

If A comes back:
- A syncs messages from B (catches up)
- A sets new prices (whatever they want)
- Users decide whether to use A again
```

**There are NO conflicts because:**
- Prices are per-relayer (stored under each relayer's address)
- Messages are shared (same Merkle root for everyone)
- Plans are per-user-per-relayer (Alice has a plan with A, Bob has a plan with B)

### Relayer Reputation

| Metric | What it measures | How to check |
|--------|-----------------|--------------|
| Online status | Is relayer alive? | `is_relayer_online(addr)` |
| Uptime score | How long running | `get_relayer_reputation(addr)` |
| User ratings | 1-5 stars | `get_relayer_rating(addr)` |
| Plans sold | How many users trust them | `get_relayer_stats(addr)` |
| Plans offered | What they charge | `get_plan_count(addr)` + `get_plan(addr, id)` |

### Message Recovery

If you switch computers or all relayers disappear:

1. Import your wallet (seed phrase)
2. Launch `xvault` → Chat
3. The CLI:
   - Derives your chat key from wallet key (automatic)
   - Reads last 50 messages from on-chain: `get_message(your_addr, 0..49)`
   - Decrypts each message with your private key
   - Saves decrypted messages locally

You never lose messages as long as you have your seed phrase.

### Message Deletion

| Action | What happens |
|--------|-------------|
| Delete message | Tombstone on-chain + delete local copy (both sides) |
| Delete conversation | Tombstone all messages + delete local files |
| Ephemeral message | Auto-deletes after TTL (2h/6h/12h/24h) |

Both sender AND recipient can delete a message.

### Groups

1. **Create group**: Admin generates group key, creates group on-chain
2. **Add members**: Admin encrypts group key for each member's public key
3. **Send message**: Member encrypts with group key, stores on-chain
4. **Kick member**: Admin removes their key + rotates group key
5. **Key rotation**: Admin generates new key, distributes to remaining members
6. Kicked member can't read new messages (different key)

### Security Guarantees

| Threat | Protected? | How |
|--------|-----------|-----|
| Message interception | YES | E2E encryption (ChaCha20-Poly1305) |
| Relayer reads messages | YES | Only encrypted blobs visible |
| Forged sender identity | YES | get_caller() verified on-chain |
| Spam | YES | 100/day free limit, premium fees |
| Censorship | YES | Messages travel P2P (off-chain) |
| Data loss (no relayers) | YES | 50 messages stored on-chain |
| Replay attacks | YES | Timestamp as associated data |
| Message tampering | YES | Tombstones + Merkle roots |
| User cheats on plan | YES | Plans verified on-chain by relayer |
| Relayer cheats on payment | NO (direct) | Payment is direct, no escrow |

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
├── contacts.json              # Address book (address + public keys)
├── pending/                   # Messages queued for relayer
└── relayer_peers.json         # Known relayer endpoints
```
