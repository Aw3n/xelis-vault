"""Offline regressions for the cached/fanned-out live reads, run against both trees.

Run: venv/Scripts/python.exe -B -m unittest discover -s tests -p test_perf_caches.py

Everything is stdlib + fakes: the bundle lives in a temp dir, the registry is a
Mock, and the HTTP layer is banned, so a test failing here never means "the node
was slow" — it means a cache returned stale data, or two independent reads were
issued one after the other again.
"""
import importlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "scripts", ROOT / "src" / "scripts")
ADDRESS = "xet:offline-operator"
ATOMIC = 100_000_000
REG = "f" * 64


@contextmanager
def isolated_tree(tree):
    """Import one tree's modules, then restore sys.modules/sys.path exactly."""
    names = ("tui", "config", "protocol", "cli_backend", "onboarding",
             "_perf_console", "_perf_xvault")
    saved = {n: sys.modules[n] for n in names if n in sys.modules}
    old_path = sys.path[:]
    try:
        for n in names:
            sys.modules.pop(n, None)
        sys.path[:] = [str(tree)] + [p for p in old_path
                                     if Path(p).resolve() not in TREES]
        importlib.invalidate_caches()
        loaded = {}
        for mod_name, filename in (("_perf_console", "xvault-miner.py"),
                                   ("_perf_xvault", "xvault.py")):
            spec = importlib.util.spec_from_file_location(mod_name, tree / filename)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded[filename] = module
        for n in names[:5]:
            loaded[n] = importlib.import_module(n)
        yield loaded
    finally:
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = old_path


def miner_record():
    """A 15-field `Miner` struct as the daemon returns it."""
    return [ADDRESS, "https://old.invalid", "cd" * 32, str(1000 * ATOMIC), "3",
            "100", "1000", str(12 * ATOMIC), "0", "8200", "17", "9", "20", "0", True]


class PerfCacheCases:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(tempfile.mkdtemp(prefix="perf-home-"))
        self.tmp = Path(tempfile.mkdtemp(prefix="perf-tmp-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stack.enter_context(patch.object(Path, "home", return_value=self.home))
        self.stack.enter_context(patch.object(sys, "dont_write_bytecode", True))
        mods = self.stack.enter_context(isolated_tree(self.tree))
        self.cb = mods["cli_backend"]
        self.tui = mods["tui"]
        self.config_module = mods["config"]
        self.protocol = mods["protocol"]
        self.console = mods["xvault-miner.py"]
        self.xv = mods["xvault.py"]
        self.onboarding = mods["onboarding"]
        # Aucun de ces tests ne doit toucher le réseau.
        self.stack.enter_context(patch.object(self.protocol, "_post",
                                              side_effect=AssertionError("network I/O banned")))
        self.stack.enter_context(patch.object(self.protocol.WalletClient, "_call",
                                              side_effect=AssertionError("network I/O banned")))
        self.cb.clear_network_caches()
        self.addCleanup(self.cb.clear_network_caches)

    # -- bundle ------------------------------------------------------------
    def write_bundle(self, contracts, mtime):
        path = self.tmp / "testnet.json"
        path.write_text(json.dumps({"contracts": contracts}))
        os.utime(path, ns=(mtime, mtime))
        return path

    def test_bundle_reparses_only_when_the_file_moves(self):
        path = self.write_bundle({"psm": "a" * 64}, 1_000_000)
        with patch.object(self.cb, "_bundle_candidates", return_value=[path]):
            self.assertEqual(self.cb.load_bundle()["contracts"]["psm"], "a" * 64)
            # réécriture à horodatage identique = contenu invisible, puis
            # mtime avancé = relecture. C'est le contrat du cache.
            self.write_bundle({"psm": "b" * 64}, 1_000_000)
            self.assertEqual(self.cb.load_bundle()["contracts"]["psm"], "a" * 64)
            os.utime(path, ns=(2_000_000, 2_000_000))
            self.assertEqual(self.cb.load_bundle()["contracts"]["psm"], "b" * 64)

    def test_bundle_cache_is_not_poisoned_by_callers(self):
        path = self.write_bundle({"psm": "a" * 64}, 1_000_000)
        with patch.object(self.cb, "_bundle_candidates", return_value=[path]):
            first = self.cb.load_bundle()
            first["contracts"]["psm"] = "tampered"
            self.assertEqual(self.cb.load_bundle()["contracts"]["psm"], "a" * 64)
            self.assertIsNot(first, self.cb.load_bundle())

    def test_bundle_absent_is_empty_and_clear_forces_a_re_read(self):
        path = self.tmp / "missing.json"
        with patch.object(self.cb, "_bundle_candidates", return_value=[path]):
            self.assertEqual(self.cb.load_bundle(), {})
        path = self.write_bundle({"psm": "a" * 64}, 1_000_000)
        with patch.object(self.cb, "_bundle_candidates", return_value=[path]):
            self.cb.load_bundle()
            self.write_bundle({"psm": "c" * 64}, 1_000_000)
            self.cb.clear_network_caches()
            self.assertEqual(self.cb.load_bundle()["contracts"]["psm"], "c" * 64)

    # -- registry resolution ----------------------------------------------
    def backend_stub(self, url="https://node.invalid/json_rpc", registry=REG):
        b = object.__new__(self.cb.Backend)
        b.daemon = MagicMock()
        b.daemon.url = url
        b.contracts = {"registry": registry}

        def read_key(contract, key):
            name = key[4:]
            if name not in self.cb._REGISTRY_NAMES.values():
                return None
            return "ab" * 32

        b.daemon.read_key.side_effect = read_key
        return b

    def test_registry_resolves_once_per_ttl_per_node(self):
        b = self.backend_stub()
        names = len(self.cb._REGISTRY_NAMES)
        b._resolve_via_registry()
        first = b.daemon.read_key.call_count
        self.assertEqual(first, names)
        b._resolve_via_registry()
        self.assertEqual(b.daemon.read_key.call_count, names,
                         "une résolution fraîche ne doit pas re-sonder le nœud")
        self.assertEqual(b.C("psm"), "ab" * 32)
        # TTL expiré -> nouvelle résolution
        for key in list(self.cb._REGISTRY_CACHE):
            stamp, resolved = self.cb._REGISTRY_CACHE[key]
            self.cb._REGISTRY_CACHE[key] = (stamp - self.cb._REGISTRY_TTL - 1, resolved)
        b._resolve_via_registry()
        self.assertEqual(b.daemon.read_key.call_count, names * 2)

    def test_registry_cache_is_keyed_by_node_and_survives_per_instance_state(self):
        b1 = self.backend_stub(url="https://one.invalid/json_rpc")
        b2 = self.backend_stub(url="https://two.invalid/json_rpc")
        b1._resolve_via_registry()
        b2._resolve_via_registry()
        self.assertEqual(b1.daemon.read_key.call_count, len(self.cb._REGISTRY_NAMES))
        self.assertEqual(b2.daemon.read_key.call_count, len(self.cb._REGISTRY_NAMES))
        # une résolution fraîche profite à la nouvelle instance du MÊME nœud
        b3 = self.backend_stub(url="https://one.invalid/json_rpc")
        b3._resolve_via_registry()
        self.assertEqual(b3.daemon.read_key.call_count, 0)

    def test_failed_registry_resolution_is_never_cached(self):
        b = self.backend_stub()
        b.daemon.read_key.side_effect = self.cb.RPCError("node offline")
        b._resolve_via_registry()
        self.assertEqual(self.cb._REGISTRY_CACHE, {},
                         "un échec ne doit pas geler les adresses pendant le TTL")
        b.daemon.read_key.side_effect = lambda contract, key: (
            "ab" * 32 if key[4:] in self.cb._REGISTRY_NAMES.values() else None)
        b._resolve_via_registry()
        self.assertEqual(len(self.cb._REGISTRY_CACHE), 1)

    def test_partial_registry_pass_is_never_cached(self):
        b = self.backend_stub()
        calls = []

        def cut_second(contract, key):
            calls.append(key)
            if len(calls) == 2:
                raise self.cb.RPCError("node cut mid-read")
            return "ab" * 32

        b.daemon.read_key.side_effect = cut_second
        b._resolve_via_registry()
        self.assertEqual(self.cb._REGISTRY_CACHE, {},
                         "une passe interrompue ne doit pas geler le reste en repli")
        b.daemon.read_key.side_effect = lambda contract, key: "ab" * 32
        b._resolve_via_registry()
        self.assertEqual(len(self.cb._REGISTRY_CACHE), 1)

    def test_registry_cache_is_bounded(self):
        b = self.backend_stub()
        for i in range(self.cb._REGISTRY_MAX):
            self.cb._REGISTRY_CACHE[(f"https://flood-{i}.invalid", REG)] = (time.time(), {})
        b._resolve_via_registry()
        self.assertLessEqual(len(self.cb._REGISTRY_CACHE), 2)

    # -- fetch_live --------------------------------------------------------
    def live_backend(self, reads):
        b = MagicMock()
        b.address = ADDRESS
        b.has_wallet = True
        b.daemon.topoheight.return_value = 1250
        for name, value in reads.items():
            getattr(b, name).side_effect = value
        return b

    def test_fetch_live_issues_independent_reads_at_once(self):
        # Cinq lectures, une barrière à cinq : séquentiel, personne n'avance.
        barrier = threading.Barrier(5, timeout=15)

        def concurrent(value):
            def read(*a, **k):
                barrier.wait()
                return value
            return read

        b = self.live_backend({
            "balances": concurrent({"XEL": ATOMIC}),
            "my_miner": concurrent(miner_record()),
            "miner_stats": concurrent({"total_staked": 2 * ATOMIC}),
            "price": concurrent((20_000_000, 1200, False)),
            "chat_relayer_status": concurrent({"active": True}),
        })
        live = self.console.fetch_live(b)
        self.assertTrue(live["connected"], live["error"])
        self.assertEqual(live["balances"], {"XEL": ATOMIC})
        self.assertEqual(live["miner"]["reputation"], 8200)
        self.assertEqual(live["feeds"][0]["age"], 50)
        self.assertEqual(live["relayer"], {"active": True})

    def test_first_read_in_priority_order_wins_when_later_reads_fail_first(self):
        stats_failure = self.cb.RPCError("stats exploded")

        def balances():
            time.sleep(0.2)
            raise self.cb.RPCError("balances exploded")

        b = self.live_backend({
            "balances": balances,
            "my_miner": lambda: miner_record(),
            "miner_stats": lambda: (_ for _ in ()).throw(stats_failure),
        })
        live = self.console.fetch_live(b)
        self.assertFalse(live["connected"])
        self.assertIn("balances exploded", live["error"])
        self.assertNotIn("stats", live["error"])
        self.assertEqual(live["miner"], {})

    def test_slow_node_does_not_double_a_refresh(self):
        """La latence d'un rafraîchissement ~= la lecture la plus lente, pas leur somme."""
        def slow(value):
            def read(*a, **k):
                time.sleep(0.3)
                return value
            return read

        b = self.live_backend({
            "balances": slow({"XEL": ATOMIC}),
            "my_miner": slow(miner_record()),
            "miner_stats": slow({}),
            "price": slow((20_000_000, 1200, False)),
            "chat_relayer_status": slow({"active": True}),
        })
        started = time.monotonic()
        live = self.console.fetch_live(b)
        elapsed = time.monotonic() - started
        self.assertTrue(live["connected"], live["error"])
        self.assertLess(elapsed, 1.0,
                        f"reads still serial: {elapsed:.2f}s for 5 x 0.3s")

    # -- terminal clear ----------------------------------------------------
    def test_clear_writes_ansi_instead_of_forking_the_console_command(self):
        buf = io.StringIO()
        with patch.object(self.tui, "_VT_CLEAR", True), \
                patch.object(self.tui.os, "system") as system, \
                redirect_stdout(buf):
            self.tui.clear()
        self.assertEqual(buf.getvalue(), "\033[H\033[2J")
        system.assert_not_called()

    def test_clear_keeps_the_shell_fallback_for_a_console_that_cannot_reset(self):
        buf = io.StringIO()
        with patch.object(self.tui, "_VT_CLEAR", False), \
                patch.object(self.tui.os, "system", return_value=0) as system, \
                redirect_stdout(buf):
            self.tui.clear()
        self.assertEqual(buf.getvalue(), "")
        system.assert_called_once()

    # -- wallet liveness probe --------------------------------------------
    def wallet_cfg(self):
        cfg = self.config_module.Config()
        binary = self.tmp / "xelis_wallet"
        binary.write_text("")
        cfg.data.update({"wallet_binary": str(binary), "wallet_path": str(self.tmp),
                         "wallet_password": "fake-wallet-secret",
                         "wallet_rpc_port": 19082})
        return cfg

    def test_wallet_probe_is_cached_then_verified_again(self):
        cfg = self.wallet_cfg()
        probes = []
        with patch.object(self.xv.onboarding, "rpc_call",
                          side_effect=lambda *a, **k: probes.append(1) or "xet:fake"), \
                patch.object(self.xv.onboarding, "launch_wallet",
                             side_effect=AssertionError("must not relaunch")) as launch:
            self.addCleanup(self.xv._WALLET_ALIVE_CACHE.clear)
            self.xv._WALLET_ALIVE_CACHE.clear()
            self.assertTrue(self.xv.ensure_wallet_alive(cfg))
            self.assertTrue(self.xv.ensure_wallet_alive(cfg))
            self.assertEqual(len(probes), 1, "sonde relancée à chaque tour de menu")
            self.assertEqual(launch.call_count, 0)
            key = next(iter(self.xv._WALLET_ALIVE_CACHE))
            stamp, state = self.xv._WALLET_ALIVE_CACHE[key]
            self.xv._WALLET_ALIVE_CACHE[key] = (stamp - self.xv._WALLET_ALIVE_TTL - 1, state)
            self.assertTrue(self.xv.ensure_wallet_alive(cfg))
            self.assertEqual(len(probes), 2)

    def test_wallet_probe_is_skipped_without_a_complete_configuration(self):
        cfg = self.wallet_cfg()
        cfg.data["wallet_password"] = ""      # sonde jamais émise : pas d'entrée en cache
        with patch.object(self.xv.onboarding, "rpc_call") as rpc:
            self.assertFalse(self.xv.ensure_wallet_alive(cfg))
        rpc.assert_not_called()
        self.assertEqual(self.xv._WALLET_ALIVE_CACHE, {})

    # -- configuration versioning -----------------------------------------
    def test_config_version_moves_on_save_and_on_reload(self):
        cfg = self.config_module.Config()
        before = cfg._version
        cfg.save()
        self.assertEqual(cfg._version, before + 1)
        cfg.__init__()
        self.assertGreater(cfg._version, before + 1,
                           "un rechargement doit invalider le Backend en cache")


class SourcePerfCacheTests(PerfCacheCases, unittest.TestCase):
    tree = TREES[0]


class InstalledPerfCacheTests(PerfCacheCases, unittest.TestCase):
    tree = TREES[1]


def load_tests(loader, tests, pattern):
    # Source d'abord : une copie installée désynchronisée ne doit pas masquer
    # une régression du dépôt.
    return unittest.TestSuite(loader.loadTestsFromTestCase(cls) for cls in (
        SourcePerfCacheTests, InstalledPerfCacheTests))


if __name__ == "__main__":
    unittest.main()
