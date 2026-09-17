"""Offline regressions for the local transaction ledger (no RPC, no files in HOME)."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "scripts", ROOT / "src" / "scripts")


def load_ledger(tree):
    old_path = sys.path[:]
    saved = sys.modules.pop("tx_ledger", None)
    try:
        sys.path[:] = [str(tree)] + [p for p in old_path
                                     if Path(p).resolve() not in TREES]
        importlib.invalidate_caches()
        return importlib.import_module("tx_ledger")
    finally:
        sys.path[:] = old_path
        sys.modules.pop("tx_ledger", None)
        if saved is not None:
            sys.modules["tx_ledger"] = saved


class LedgerCases:
    def setUp(self):
        super().setUp()
        self.ledger = load_ledger(self.tree)
        temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(self.ledger, "LEDGER_DIR", temp))
        self.enterContext(patch.object(self.ledger, "LEDGER_PATH", temp / "tx_history.json"))

    def test_record_is_idempotent_and_keeps_full_tx_hash(self):
        self.ledger.record("xet:owner", "a" * 64, action="mint")
        self.ledger.record("xet:owner", "a" * 64, action="mint")
        entries = self.ledger.all_entries()
        self.assertEqual([e["tx_hash"] for e in entries], ["a" * 64])

    def test_entries_visible_only_to_their_wallet_owner(self):
        self.ledger.record("xet:owner", "a" * 64)
        self.assertEqual(len(self.ledger.all_entries("xet:owner")), 1)
        self.assertEqual(self.ledger.all_entries("xet:other"), [])
        self.assertEqual(len(self.ledger.all_entries()), 1)

    def test_limit_returns_newest_entries_in_order(self):
        for i in range(3):
            self.ledger.record("xet:owner", f"{i:064x}")
        self.assertEqual([e["tx_hash"][-1] for e in self.ledger.all_entries(limit=2)],
                         ["1", "2"])


class SourceLedgerTests(LedgerCases, unittest.TestCase):
    tree = ROOT / "scripts"


class RuntimeLedgerTests(LedgerCases, unittest.TestCase):
    tree = ROOT / "src" / "scripts"


if __name__ == "__main__":
    unittest.main()
