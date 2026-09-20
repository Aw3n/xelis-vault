#!/usr/bin/env python3
"""Shared configuration loader for xvault and xvault-miner."""
from __future__ import annotations

import json
import os
from pathlib import Path

VAULT_DIR = Path.home() / ".xelis-vault"
CONFIG_PATH = VAULT_DIR / "config" / "config.json"

DEFAULTS = {
    "rpc_url": "https://testnet-node.xelis.io",
    "wallet_url": "http://127.0.0.1:18082",
    "wallet_user": "wallet",
    "wallet_pass": "testpass",
    "miner_address": "",
    "miner_endpoint": "",
    "services": "both",
    "compound": False,
    "contracts": {},
}


class Config:
    def __init__(self):
        self.data = dict(DEFAULTS)
        # Monotone même via __init__ (l'écran Settings recharge par ce chemin).
        self._version = getattr(self, "_version", 0) + 1
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                stored = json.loads(CONFIG_PATH.read_text())
                for k, v in stored.items():
                    self.data[k] = v
            except Exception:
                pass

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.data, indent=2))
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass
        # Les écrans mettent en cache le Backend construit à partir de `data` :
        # ce compteur est la seule trace qu'il faut le reconstruire.
        self._version += 1

    def get(self, key, default=""):
        return self.data.get(key, default)

    def reset(self):
        self.data = dict(DEFAULTS)
        self.save()

    @property
    def contracts(self):
        return self.data.get("contracts", {})
