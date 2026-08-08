# VaultChat — Complete Guide

## The Simple Version (Read This First)

VaultChat is end-to-end encrypted messaging built into XELIS Vault. Nobody — not relayers, not miners, not the protocol team — can read your messages.

### Your Keys Explained (No Confusion)

You already have a XELIS wallet with a private key (protected by your password/seed phrase). VaultChat does **NOT** create a second wallet or a separate set of keys. Instead, it **derives** a chat keypair from your existing wallet key:

```
Your XELIS Wallet Private Key (the one you already have)
    │
    ▼
HKDF-SHA256 Derivation (happens automatically inside xvault)
    │
    ▼
┌──────────────────────────────────┐
│ Chat Private Key                  │  Stored locally at ~/.xelis-vault/chat/keys/identity.json
│ (Used to DECRYPT messages sent   │  Never leaves your computer. Never shared with anyone.
│  to you)                          │
├──────────────────────────────────┤
│ Chat Public Key                   │  Registered on-chain via VaultChat.register_session()
│ (Shared with others so they      │  Anyone can read it to send you encrypted messages.
│  can ENCRYPT messages to you)    │
└──────────────────────────────────┘
```

**Key Points:**
1. **One seed phrase to rule them all:** You only back up your XELIS wallet seed phrase. If you lose your computer, you restore your wallet, and the `xvault` CLI automatically regenerates the exact same chat keys.
2. **No separate backup needed:** Because the chat key is mathematically derived from the wallet key, you never need to back up a "chat seed" separately.
3. **Total privacy:** Your chat private key is stored locally with strict file permissions (`chmod 600`). It is never transmitted over the network.

### Sending a Message — Step by Step

1. **Alice** wants to send "Hello Bob" to **Bob**.
2. Alice's `xvault` CLI reads Bob's Chat Public Key from the XELIS blockchain.
3. Alice's CLI uses **X25519 Diffie-Hellman** to compute a shared secret:
   `Shared_Secret = DH(Alice_Chat_Private_Key, Bob_Chat_Public_Key)`
   *Note: Bob can compute the exact same secret using his private key and Alice's public key.*
4. Alice's CLI encrypts the message using **ChaCha20-Poly1305**:
   `Ciphertext = Encrypt("Hello Bob", Shared_Secret, Random_Nonce, Timestamp)`
5. Alice's CLI sends the Ciphertext to her chosen Relayer (P2P, < 1 second).
6. The Relayer stores the Ciphertext on-chain: `VaultChat.store_message(bob_address, ciphertext)`.
7. The Relayer forwards the Ciphertext to Bob's Relayer (P2P).
8. **Bob** receives the Ciphertext.
9. Bob's CLI decrypts it using his Chat Private Key and Alice's Chat Public Key.
10. Bob reads "Hello Bob". The decrypted message is saved locally.

### Message Speed

| Scenario | Time |
|----------|------|
| P2P delivery (both online) | < 1 second |
| On-chain storage (persistence) | ~5 seconds (1 block) |
| Relayer batch anchor (proof) | ~80 minutes (configurable) |
| Offline user recovery | Next time they launch `xvault` |

### Free vs Premium — The Telecom Model

VaultChat works like telecom operators (Orange, SFR, etc.). Each Relayer is an independent operator.

**1. Free Tier (Limited Slots)**
- Each Relayer offers a limited number of free slots per day (e.g., 100 slots).
- Each slot gives a certain number of free messages (e.g., 50 messages).
- First come, first served. Once daily slots are full, users must pay or wait until tomorrow.
- *Why this prevents abuse:* The Relayer pays the XEL gas fees to store messages on-chain. If a user creates 1,000 wallets, the Relayer still only allows 100 slots and thus limits their own gas cost.

**2. Per-Message Pricing**
- Relayers set a price per message (e.g., 0.01 VLT).

**3. Subscriptions / Message Packs**
- Relayers can sell duration plans (e.g., 1 VLT for 30 days unlimited) or message packs (e.g., 0.5 VLT for 100 messages).
- Users can buy a plan for themselves **or for another wallet** (gifting/company plans).

**Protocol Fee:** When a Relayer collects their fees, 5% goes to the protocol treasury to fund liquidity pools, bug bounties, and development. The Relayer keeps 95%.

### Relayer Sync & Anti-Cheat

- **Sync:** Relayers synchronize *messages* with each other (P2P gossip) for redundancy. They do **not** sync prices.
- **Anti-Cheat (Storage):** If a Relayer claims to be "free" but doesn't store messages on-chain to save gas, users can verify this (`verify_message_stored`). The user rates the Relayer 1 star.
- **Anti-Cheat (Blacklist):** If a Relayer stops anchoring batches, other Relayers blacklist them. Blacklisted Relayers are excluded from the P2P sync network and naturally die off.

### Storage Management

**On-chain (Automatic):**
- Fixed ring buffer: 50 messages per user. Old messages are automatically overwritten.
- Zero storage growth on the blockchain.

**Off-chain (Relayer's Disk):**
- Relayers use tiered storage: Hot (SSD, 7 days) → Warm (HDD, compressed, 90 days) → Cold (Archive).
- Deduplication: The same message synced from 3 Relayers is stored only once.
- Pruning: Relayers automatically delete messages older than their retention period.

### Message Deletion & Groups

- **Delete Message:** Tombstone placed on-chain + local file deleted. Both sender and recipient can delete.
- **Delete Conversation:** Tombstones placed for all messages with a specific peer + local files deleted.
- **Ephemeral Messages:** Auto-delete after a set TTL (2h, 6h, 12h, 24h).
- **Groups:** Admin creates group, adds members by encrypting the group key for each member. If a member is kicked, the admin rotates the group key. The kicked member cannot read new messages.

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
