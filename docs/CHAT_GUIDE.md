# VaultChat — Complete Guide

## How It Works (Simple Version)

VaultChat is end-to-end encrypted messaging on XELIS. Nobody — not relayers, not miners, not even the protocol creators — can read your messages.

### Key Concept: One Wallet, One Key

You do NOT need a separate key for chat. When you run `xvault`, the chat key is **derived from your XELIS wallet key**:

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

### Sending a Message

1. Alice opens `xvault` → Chat → Send message
2. Alice selects Bob from contacts
3. Alice types "Hello Bob"
4. The CLI:
   - Reads Bob's public key from on-chain (VaultChat.get_session)
   - Derives shared secret: DH(Alice_private, Bob_public)
   - Encrypts: ChaCha20-Poly1305("Hello Bob", shared_secret)
   - Sends encrypted blob to relayer (P2P, <1 second)
   - Stores on-chain: VaultChat.store_message(bob, ciphertext)
   - Saves locally: ~/.xelis-vault/chat/messages/sent/bob.json

5. Bob receives:
   - P2P delivery: <1 second (if online)
   - On-chain recovery: within 5-30 seconds
   - Bob's CLI decrypts with: DH(Bob_private, Alice_public)
   - Saves locally: ~/.xelis-vault/chat/messages/inbox/alice.json

### Message Speed

| Method | Time |
|--------|------|
| P2P (both online) | <1 second |
| On-chain storage | ~5 seconds (1 block) |
| Relayer batch anchor | ~25 seconds (5 blocks) |
| Recovery (offline user) | Next time they launch xvault |

### Free vs Premium

| Tier | Cost | Limit |
|------|------|-------|
| Free | 0 | 100 messages/day |
| Per-message | Relayer's fee (e.g. 0.01 VLT) | Unlimited |
| Subscription | 100x per-message fee | 30 days unlimited |

The first 100 messages each day are **FREE**. After that:
- Pay per message: choose a relayer, pay their fee
- Buy subscription: 30 days of unlimited messages

### Message Recovery

If you switch computers or all relayers disappear:

1. Import your wallet (seed phrase)
2. Launch `xvault` → Chat
3. The CLI:
   - Derives your chat key from wallet key
   - Reads last 50 messages from on-chain (VaultChat.get_message)
   - Decrypts each message with your private key
   - Saves decrypted messages locally

**You never lose messages** as long as:
- You have your wallet seed phrase
- The messages were stored on-chain (within the last 50)

### Message Deletion

| Action | What happens |
|--------|-------------|
| Delete message | Tombstone on-chain + delete local copy (both sides) |
| Delete conversation | Tombstone all messages + delete local files |
| Ephemeral message | Auto-deletes after TTL (2h/6h/12h/24h) |

Both sender AND recipient can delete a message. When one deletes, the other sees a tombstone on next sync and deletes their local copy too.

### Groups

1. **Create group**: Admin generates group key, creates group on-chain
2. **Add members**: Admin encrypts group key for each member's public key
3. **Send message**: Member encrypts with group key, stores on-chain
4. **Kick member**: Admin removes their key + rotates group key
5. **Key rotation**: Admin generates new key, distributes to remaining members. Kicked member can't read new messages.

### Relayers

Relayers are the backbone of the chat system. They:
- Forward messages P2P between users (<1 second)
- Store messages on-chain (persistence)
- Anchor Merkle roots (proof of existence)
- Earn VLT rewards + premium fees

#### Becoming a Relayer

1. A miner registers as relayer: `VaultChat.set_relayer(addr, true)`
2. Sets pricing: `set_relayer_fee(fee, token)` — e.g. 0.01 VLT per message
3. Sends heartbeats every 100 blocks: `relayer_heartbeat()`
4. Users see their reputation + pricing and choose

#### Relayer Reputation System

| Metric | What it measures |
|--------|-----------------|
| Heartbeat uptime | Is the relayer online? |
| Reputation score | How long they've been running |
| User ratings | 1-5 stars from users |
| Messages relayed | Volume handled |
| Subscriptions sold | How many users trust them |

Users can query: `get_relayer_stats(addr)`, `get_relayer_rating(addr)`, `is_relayer_online(addr)`

#### Relayer Sync (How New Relayers Start)

1. Register on-chain: `set_relayer(addr, true)`
2. Set pricing: `set_relayer_fee(fee, token)`
3. Read all on-chain messages (50 per user)
4. Contact existing relayers (P2P gossip)
5. Sync full history from peers
6. Start serving users

#### Competition Model

- Each relayer sets their own price
- Users choose the cheapest/most reliable relayer
- VLT preferred (strengthens token economy)
- XEL accepted (for users who don't have VLT yet)
- Bad relayers lose users (rating system)
- Good relayers earn more (reputation + subscriptions)

### Security Guarantees

| Threat | Protected? | How |
|--------|-----------|-----|
| Message interception | ✅ | E2E encryption (ChaCha20-Poly1305) |
| Relayer reads messages | ✅ | Only encrypted blobs visible |
| Forged sender identity | ✅ | get_caller() verified on-chain |
| Spam | ✅ | 100/day free limit, premium fees |
| Censorship | ✅ | Messages travel P2P (off-chain) |
| Data loss (no relayers) | ✅ | 50 messages stored on-chain |
| Replay attacks | ✅ | Timestamp as associated data |
| Message tampering | ✅ | Tombstones + Merkle roots |

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
