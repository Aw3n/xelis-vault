"""Offline keeper regressions. No wallets, processes, or network transactions.

Run: python -B -m unittest discover -s tests -p test_oracle_keeper.py -v
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]


def load_keeper(relative_path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    old_path = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


SOURCE = load_keeper("scripts/oracle_keeper3.py", "keeper_source_test")
RUNTIME = load_keeper("src/scripts/oracle_keeper3.py", "keeper_runtime_test")


class KeeperTests:
    """Exercise both shipped copies with the same mocked scenarios."""

    def setUp(self):
        self.logger = self.start_patch("log")
        self.sleep = self.start_patch("time.sleep")
        self.save_cache = self.start_patch("_save_cached_price")
        self.factory = self.start_patch("Protocol")
        for method in ("get", "post"):
            guard = patch.object(self.k.requests, method,
                                 side_effect=AssertionError("network forbidden in keeper tests"))
            guard.start()
            self.addCleanup(guard.stop)

    def start_patch(self, name, **kwargs):
        target = self.k
        parts = name.split(".")
        for part in parts[:-1]:
            target = getattr(target, part)
        patcher = patch.object(target, parts[-1], **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def protocol(self, address="xet:test"):
        pw = Mock()
        pw.wallet.address.return_value = address
        pw.wallet._call.return_value = {"hash": "tx"}
        pw.wait.return_value = {"hash": "tx", "executed_in": "block"}
        pw.daemon.get_contract_logs.return_value = [
            {"type": "exit_code", "value": {"contract": "miner", "code": 0}}]
        return pw

    def providers(self, *last_heartbeats, interval=900, timeout=4000):
        providers = []
        records = {"hi": interval, "ht": timeout}
        for idx, last in enumerate(last_heartbeats):
            addr = f"xet:provider{idx}"
            records["miner_" + addr] = [addr, "url", "pubkey", 1000, 1, 0,
                                       last, 0, 0, 1000, 0, 0, 0, 0, True]
            pw = self.protocol(addr)
            pw.daemon.read_key.side_effect = lambda contract, key: records.get(key)
            providers.append(self.k.Provider(f"provider{idx}", pw, addr))
        return providers, records

    def config(self):
        return {"rpc_url": "https://configured.invalid",
                "wallet_url": "http://127.0.0.1:19082",
                "wallet_user": "custom-user", "wallet_pass": "custom-pass",
                "miner_address": "xet:test"}

    def test_config_wires_only_configured_wallet_and_rpc_override(self):
        for override in (None, "https://override.invalid/json_rpc"):
            with self.subTest(override=override):
                self.factory.reset_mock()
                self.factory.return_value = self.protocol()
                with patch.object(Path, "read_text", return_value=json.dumps(self.config())):
                    providers = self.k.load_wallets(ROOT / "unused-config.json", override)
                self.factory.assert_called_once_with(
                    wallet_url="http://127.0.0.1:19082",
                    wallet_auth=("custom-user", "custom-pass"),
                    daemon_url=override or "https://configured.invalid")
                self.assertEqual(len(providers), 1)
                self.assertEqual(providers[0].address, "xet:test")
                providers[0].protocol.wallet._call.assert_not_called()

    def test_config_mismatched_wallet_is_rejected_before_writes(self):
        pw = self.protocol("xet:different")
        self.factory.return_value = pw
        with patch.object(Path, "read_text", return_value=json.dumps(self.config())):
            with self.assertRaisesRegex(RuntimeError, "does not match.*miner_address"):
                self.k.load_wallets(ROOT / "unused-config.json", None)
        pw.wallet._call.assert_not_called()

    def test_config_invalid_or_missing_identity_never_uses_standalone(self):
        for data in ("invalid json", "[]", '{}', '{"miner_address": ""}'):
            with self.subTest(data=data), patch.object(Path, "read_text", return_value=data):
                with self.assertRaises(ValueError):
                    self.k.load_wallets(ROOT / "unused-config.json", None)
        self.factory.assert_not_called()

    def test_standalone_keeps_three_providers_and_supports_rpc_override(self):
        for rpc in (None, "https://standalone.invalid"):
            with self.subTest(rpc=rpc):
                self.factory.reset_mock()
                self.factory.side_effect = [self.protocol(f"xet:{idx}") for idx in range(3)]
                wallets = self.k.load_wallets(None, rpc)
                self.assertEqual(len(wallets), 3)
                self.assertEqual(self.factory.call_args_list, [
                    call(wallet_url=url, wallet_auth=("wallet", "testpass"),
                         daemon_url=rpc or self.k.DAEMON_URL)
                    for url, idx in self.k.PROVIDERS])

    def test_send_requires_confirmation_before_inspecting_logs(self):
        for confirmation in (None, False, {}):
            with self.subTest(confirmation=confirmation):
                pw = self.protocol()
                pw.wait.return_value = confirmation
                self.assertFalse(self.k.send(pw, "miner", 21, []))
                pw.daemon.get_contract_logs.assert_not_called()
        pw = self.protocol()
        pw.wait.side_effect = TimeoutError("not confirmed")
        self.assertFalse(self.k.send(pw, "miner", 21, []))
        self.assertTrue(self.logger.called)

    def test_send_rejects_unknown_reverted_nonzero_and_unrelated_exits(self):
        bad_logs = [
            [], [{"type": "event", "value": "heartbeat"}],
            [{"type": "exit_code", "value": {"code": 1}}],
            [{"type": "exit_code", "value": {}}],
            [{"exit_code": False}],
            [{"type": "exit_error", "value": {"err": {"message": "toosoon"}}}],
            [{"exit_error": "inactive"}],
            [{"type": "exit_code", "value": {"contract": "another", "code": 0}}],
            [{"exit_code": 0}, {"exit_error": "reverted"}],
        ]
        for logs in bad_logs:
            with self.subTest(logs=logs):
                pw = self.protocol()
                pw.revert_reason.return_value = None
                pw.daemon.get_contract_logs.return_value = logs
                self.assertFalse(self.k.send(pw, "miner", 21, []))
                self.assertLessEqual(pw.daemon.get_contract_logs.call_count, 6)

    def test_send_accepts_explicit_zero_and_waits_for_delayed_logs(self):
        for logs in ([{"exit_code": 0}],
                     [{"type": "exit_code", "value": 0}],
                     [{"type": "exit_code", "value": {"contract": "miner", "code": "0"}}]):
            with self.subTest(logs=logs):
                pw = self.protocol()
                pw.daemon.get_contract_logs.side_effect = [[], [{"type": "event"}], logs]
                self.assertTrue(self.k.send(pw, "miner", 21, []))
                self.assertEqual(pw.daemon.get_contract_logs.call_count, 3)
                self.assertEqual(pw.wallet._call.call_count, 1)
                pw.wait.assert_called_once_with("tx", timeout=120)

    def test_send_build_or_log_failure_is_reported(self):
        pw = self.protocol()
        pw.wallet._call.return_value = {}
        self.assertFalse(self.k.send(pw, "miner", 21, []))
        pw.wait.assert_not_called()
        pw = self.protocol()
        pw.daemon.get_contract_logs.side_effect = ConnectionError("daemon offline")
        self.assertFalse(self.k.send(pw, "miner", 21, []))
        self.assertIn("daemon offline", self.logger.call_args.args[0])

    def test_heartbeat_obeys_chain_interval_at_exact_boundary(self):
        wallets, records = self.providers(1000, interval=20)
        send = self.start_patch("send", return_value=True)
        self.k.heartbeat_round(wallets, "miner", 21, 1019)
        send.assert_not_called()
        self.k.heartbeat_round(wallets, "miner", 21, 1020)
        send.assert_called_once_with(wallets[0].protocol, "miner", 21, [])
        self.assertEqual(wallets[0].confirmed_heartbeat, 1020)

    def test_failed_wallet_retries_next_pass_without_delaying_successful_wallet(self):
        wallets, records = self.providers(1000, 1000)
        send = self.start_patch("send", side_effect=[True, False, True])
        self.k.heartbeat_round(wallets, "miner", 21, 1900)
        self.assertEqual([p.confirmed_heartbeat for p in wallets], [1900, 0])
        self.k.heartbeat_round(wallets, "miner", 21, 1910)
        self.assertEqual([p.confirmed_heartbeat for p in wallets], [1900, 1910])
        self.assertEqual(send.call_args_list, [
            call(wallets[0].protocol, "miner", 21, []),
            call(wallets[1].protocol, "miner", 21, []),
            call(wallets[1].protocol, "miner", 21, [])])

    def test_failed_confirmation_does_not_advance_heartbeat(self):
        wallets, records = self.providers(1000)
        pw = wallets[0].protocol
        pw.wait.return_value = False
        self.k.heartbeat_round(wallets, "miner", 21, 1900)
        self.assertEqual(wallets[0].confirmed_heartbeat, 0)
        pw.wait.return_value = {"hash": "tx"}
        self.k.heartbeat_round(wallets, "miner", 21, 1910)
        self.assertEqual(wallets[0].confirmed_heartbeat, 1910)
        self.assertEqual(pw.wallet._call.call_count, 2)

    def test_restart_and_external_heartbeat_refresh_prevent_toosoon(self):
        wallets, records = self.providers(1800)
        send = self.start_patch("send", return_value=False)
        self.k.heartbeat_round(wallets, "miner", 21, 2000)
        send.assert_not_called()  # A new keeper must respect the existing chain HB.
        self.k.heartbeat_round(wallets, "miner", 21, 2700)
        self.assertEqual(send.call_count, 1)
        records["miner_" + wallets[0].address][6] = 2705  # A delayed/other sender's HB.
        self.k.heartbeat_round(wallets, "miner", 21, 2710)
        self.assertEqual(send.call_count, 1)

    def test_missing_chain_schedule_record_or_inactive_miner_skips(self):
        for missing in ("hi", "ht", "record", "inactive"):
            with self.subTest(missing=missing):
                wallets, records = self.providers(0)
                if missing in ("hi", "ht"):
                    records[missing] = None
                elif missing == "record":
                    records["miner_" + wallets[0].address] = None
                else:
                    records["miner_" + wallets[0].address][14] = False
                with patch.object(self.k, "send") as send:
                    self.k.heartbeat_round(wallets, "miner", 21, 10000)
                    send.assert_not_called()
                self.assertEqual(wallets[0].confirmed_heartbeat, 0)

    def test_overdue_but_active_miner_can_recover_heartbeat(self):
        wallets, records = self.providers(0)
        send = self.start_patch("send", return_value=True)
        self.k.heartbeat_round(wallets, "miner", 21, 5000)
        send.assert_called_once()
        self.assertTrue(any("timeout exceeded" in c.args[0] for c in self.logger.call_args_list))

    def test_no_cached_price_fallback_when_all_live_sources_fail(self):
        wallets, records = self.providers(0)
        cache = self.start_patch("PRICE_CACHE_PATH")
        cache.read_text.return_value = '{"price_atomic": 25000000, "ts": 1}'
        send = self.start_patch("send")
        self.assertEqual(self.k.submit_prices(wallets, "oracle", 16, 17, 5000), 0)
        send.assert_not_called()  # Neither a stale submission nor an aggregate poke.
        cache.read_text.assert_not_called()
        self.save_cache.assert_not_called()
        self.assertTrue(any("skip submission" in c.args[0] for c in self.logger.call_args_list))

    def test_submission_counter_counts_only_confirmed_success(self):
        wallets, records = self.providers(0, 0, 0)
        self.start_patch("fetch_real_price", side_effect=[
            (20000000, "live A"), (30000000, "live B"), (None, "sources down")])
        send = self.start_patch("send", side_effect=[True, False, True])
        self.assertEqual(self.k.submit_prices(wallets, "oracle", 16, 17, 5000), 1)
        self.assertEqual(send.call_count, 3)  # Poke and two submissions.
        self.save_cache.assert_called_once_with(30000000, "live B")
        self.assertIn("submit x1 confirmed", self.logger.call_args.args[0])

    def test_live_price_median_ignores_failed_and_insane_sources(self):
        responses = []
        for payload in ({"data": [{"last": "0.2"}]}, {"price": "0.4"},
                        {}, [{"last": "50000"}]):
            response = Mock()
            response.json.return_value = payload
            responses.append(response)
        with patch.object(self.k.requests, "get", side_effect=responses):
            price, desc = self.k.fetch_real_price()
        self.assertEqual(price, 30000000)
        self.assertIn("coinex,mexc", desc)

    def test_normal_loop_waits_ten_seconds_even_after_failure(self):
        wallets, records = self.providers(0)
        wallets[0].protocol.daemon.topoheight.side_effect = [ConnectionError("offline"), 100]
        heartbeat = self.start_patch("heartbeat_round")
        submit = self.start_patch("submit_prices")
        self.sleep.side_effect = [None, KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.k.run(wallets, "miner", "oracle",
                       {"heartbeat": 21, "submit": 16, "aggregate": 17})
        self.assertEqual(self.sleep.call_args_list, [call(10), call(10)])
        heartbeat.assert_called_once()
        submit.assert_called_once()

    def test_main_passes_launch_flags_and_resolves_contracts(self):
        wallets, records = self.providers(0)
        load = self.start_patch("load_wallets", return_value=wallets)
        run = self.start_patch("run")
        pw = wallets[0].protocol
        pw.resolve.side_effect = ["resolved-miner", "resolved-oracle"]
        path = ROOT / "unused-config.json"
        self.assertEqual(self.k.main(["--config", str(path), "--rpc", "https://node.invalid"]), 0)
        load.assert_called_once_with(path, "https://node.invalid")
        self.assertEqual(pw.resolve.call_args_list,
                         [call("XelisVaultMiner"), call("StakedOracle")])
        self.assertEqual(run.call_args.args[:3], (wallets, "resolved-miner", "resolved-oracle"))

    def test_main_reports_wallet_daemon_and_initialization_failures(self):
        wallets, records = self.providers(0)
        load = self.start_patch("load_wallets", return_value=wallets)
        run = self.start_patch("run")
        for error in (OSError("config missing"), ValueError("wallet mismatch")):
            load.side_effect = error
            self.assertEqual(self.k.main([]), 1)
            self.assertIn(str(error), self.logger.call_args.args[0])
        load.side_effect = None
        wallets[0].protocol.daemon.topoheight.side_effect = ConnectionError("offline")
        self.assertEqual(self.k.main([]), 1)
        self.assertIn("daemon RPC unavailable", self.logger.call_args.args[0])
        run.assert_not_called()


class SourceKeeperTests(KeeperTests, unittest.TestCase):
    k = SOURCE


class RuntimeKeeperTests(KeeperTests, unittest.TestCase):
    k = RUNTIME


class KeeperCopyTests(unittest.TestCase):
    def test_source_and_runtime_copies_match(self):
        self.assertEqual((ROOT / "scripts/oracle_keeper3.py").read_bytes(),
                         (ROOT / "src/scripts/oracle_keeper3.py").read_bytes())

    def test_paths_use_shared_vault_cache_and_logs(self):
        for keeper in (SOURCE, RUNTIME):
            self.assertEqual(keeper.LOG.parent, keeper.VAULT_DIR / "logs")
            self.assertEqual(keeper.PRICE_CACHE_PATH.parent, keeper.VAULT_DIR / "cache")


if __name__ == "__main__":
    unittest.main()
