"""Offline operator-console regressions, independently imported from both trees.

Run: venv/Scripts/python.exe -B -m unittest discover -s tests -p test_miner_console.py
Only stdlib test helpers; network, storage writes, wallet I/O and processes are
blocked before importing the console. All identities and credentials are fake.
"""
import importlib
import importlib.util
import io
import os
import platform
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, mock_open, patch


ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "scripts", ROOT / "src" / "scripts")
ADDRESS = "xet:offline-operator"
RPC = "https://node.invalid/json_rpc"
WALLET = "http://127.0.0.1:19082"
OLD_ENDPOINT = "https://old.invalid"
NEW_ENDPOINT = "https://new.invalid"
TX = "ab" * 32
ATOMIC = 100_000_000
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# platform.uname() shells out on Windows and caches its result; warm it here so
# the dashboard header cannot trip the per-test subprocess ban.
platform.uname()


def plain(text):
    return ANSI.sub("", text)


def forbidden(*args, **kwargs):
    raise AssertionError("Unmocked I/O is forbidden in miner console tests")


@contextmanager
def isolated_tree(tree):
    """Keep imports used inside functions isolated too, and restore module caches."""
    names = ("tui", "config", "protocol", "cli_backend", "onboarding",
             "_offline_miner_console")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    old_path = sys.path[:]
    try:
        for name in names:
            sys.modules.pop(name, None)
        sys.path[:] = [str(tree)] + [p for p in old_path if Path(p).resolve() not in TREES]
        importlib.invalidate_caches()
        spec = importlib.util.spec_from_file_location(names[-1], tree / "xvault-miner.py")
        console = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = console
        spec.loader.exec_module(console)
        onboarding = importlib.import_module("onboarding")
        yield console, onboarding
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path[:] = old_path


def miner_record(endpoint=OLD_ENDPOINT):
    return [ADDRESS, endpoint, "cd" * 32, str(1000 * ATOMIC), "3", "100",
            "1000", str(12 * ATOMIC), "0", "8200", "17", "9", "20", "0", True]


class MinerConsoleCases:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.out))
        self.stack.enter_context(redirect_stderr(self.err))
        self.stack.enter_context(patch.object(Path, "home", return_value=self.home))
        self.stack.enter_context(patch.object(sys, "dont_write_bytecode", True))
        for target in ("socket.create_connection", "socket.socket.connect",
                       "socket.socket.connect_ex", "urllib.request.urlopen",
                       "os.system", "os.kill", "builtins.input"):
            self.stack.enter_context(patch(target, side_effect=forbidden))
        self.spawn = self.stack.enter_context(patch("subprocess.Popen", side_effect=forbidden))
        # Imports may consult deployment metadata, never operator configuration.
        def import_metadata(path, *args, **kwargs):
            if path.name == "deployment_state.json" and path.parent.name == "docs":
                return "{}"
            return forbidden()
        self.stack.enter_context(patch.object(Path, "read_text", autospec=True,
                                             side_effect=import_metadata))
        for method in ("write_text", "write_bytes", "mkdir", "unlink", "chmod"):
            self.stack.enter_context(patch.object(Path, method, side_effect=forbidden))
        self.m, self.onboarding = self.stack.enter_context(isolated_tree(self.tree))
        self.tui = sys.modules["tui"]
        self.protocol = sys.modules["protocol"]
        self.backend_module = sys.modules["cli_backend"]
        self.config_module = sys.modules["config"]
        self.stack.enter_context(patch.object(self.protocol.requests.sessions.Session,
                                             "request", side_effect=forbidden))
        self.stack.enter_context(patch.object(self.protocol, "_post", side_effect=forbidden))
        self.stack.enter_context(patch.object(self.protocol.WalletClient, "_call",
                                             side_effect=forbidden))
        self.stack.enter_context(patch.object(self.m.Config, "load", side_effect=forbidden))
        self.save = self.stack.enter_context(patch.object(self.m.Config, "save"))
        self.stack.enter_context(patch("builtins.open", side_effect=forbidden))
        self.stack.enter_context(patch("io.open", side_effect=forbidden))
        self.stack.enter_context(patch.object(self.tui, "_RICH", False))
        self.stack.enter_context(patch.object(self.tui, "clear"))
        self.stack.enter_context(patch.object(self.tui, "read_key", return_value="ENTER"))
        self.clear = self.p("clear")
        self.show = self.p("show_cursor", wraps=self.m.show_cursor)
        self.hide = self.p("hide_cursor", wraps=self.m.hide_cursor)
        self.info = self.p("info_box", wraps=self.m.info_box)
        self.panels = self.p("render_panel", wraps=self.m.render_panel)
        self.text = self.p("text_input", side_effect=forbidden)
        self.confirm = self.p("confirm", return_value=False)
        self.menu = self.p("menu", side_effect=forbidden)
        self.p("read_key", return_value="ENTER")
        self.keys = self.p("read_key_timeout", side_effect=forbidden)
        self.stack.enter_context(patch.object(self.m.time, "sleep"))
        self.signals = self.stack.enter_context(patch.object(self.m.signal, "signal"))
        self.keeper_running = self.p("keeper_running", return_value=None)
        self.pow_running = self.stack.enter_context(patch.object(
            self.onboarding, "miner_running", return_value=None))
        self.start_pow = self.stack.enter_context(patch.object(
            self.onboarding, "start_miner", side_effect=forbidden))
        self.stop_pow = self.stack.enter_context(patch.object(
            self.onboarding, "stop_miner", side_effect=forbidden))
        self.cfg = object.__new__(self.m.Config)
        self.cfg.data = {
            "rpc_url": RPC, "wallet_url": WALLET, "miner_address": ADDRESS,
            "miner_endpoint": NEW_ENDPOINT, "services": "both",
            "wallet_user": "offline-user", "wallet_pass": "fake-rpc-secret",
            "wallet_password": "fake-wallet-secret", "seed": "fake-seed-never-read",
        }
        self.b = self.backend()
        self.factory = self.p("Backend", return_value=self.b)
        self.pid = self.p("KEEPER_PID", new=MagicMock(spec=Path))
        self.pid.read_text.side_effect = forbidden
        self.pid.write_text.side_effect = forbidden
        self.pid.unlink.side_effect = forbidden

    def p(self, name, **kwargs):
        return self.stack.enter_context(patch.object(self.m, name, **kwargs))

    def backend(self):
        b = Mock(spec=self.backend_module.Backend)
        b.address = ADDRESS
        b.has_wallet = True
        b.daemon = Mock(spec=self.protocol.DaemonClient)
        b.wallet = Mock(spec=self.protocol.WalletClient)
        b.wallet.address.side_effect = forbidden
        b.wallet.invoke.side_effect = forbidden
        b.daemon.topoheight.return_value = 1250
        b.topo.side_effect = forbidden  # This wrapper used to swallow RPC failures.
        b.balances.return_value = {"XEL": 2 * ATOMIC, "VLT": 3000 * ATOMIC, "xUSD": 0}
        b.my_miner.return_value = miner_record()
        b.miner_stats.return_value = {
            "total_staked": 5000 * ATOMIC, "budget": 200 * ATOMIC,
            "distributed": 50 * ATOMIC, "min_stake": 1000 * ATOMIC,
            "heartbeat_interval": 900, "heartbeat_timeout": 4000,
        }
        b.price.return_value = (20_000_000, 1200, False)
        b.miner_supports_update_endpoint.return_value = True
        b.chat_relayer_status.return_value = {
            "active": True, "bond": 50 * ATOMIC,
            "registered": {"endpoint": "https://relay.invalid", "free_daily_limit": 100,
                           "free_wallet_slots": 1000},
        }
        for method in ("miner_register", "miner_heartbeat", "miner_increase_stake",
                       "miner_enable_service", "miner_update_endpoint"):
            getattr(b, method).side_effect = forbidden
        return b

    def output(self):
        return plain(self.out.getvalue())

    def reset_output(self):
        self.out.seek(0)
        self.out.truncate()
        self.info.reset_mock()
        self.panels.reset_mock()

    def info_text(self):
        return plain("\n".join(str(part) for c in self.info.call_args_list for part in c.args))

    def panel_text(self, title):
        return plain("\n".join(str(line) for c in self.panels.call_args_list
                               if title in c.args[0] for line in c.args[1]))

    def result(self, method, ok=True, tx=TX, reason=""):
        operation = getattr(self.b, method)
        operation.side_effect = None
        operation.return_value = self.backend_module.OpResult(ok, tx, reason)
        return operation

    def endpoint_input(self, value=NEW_ENDPOINT, confirmed=True):
        self.text.side_effect = None
        self.text.return_value = value
        self.confirm.return_value = confirmed

    def run_main(self, keys=("Q",), flags=()):
        self.keys.side_effect = list(keys)
        with patch.object(sys, "argv", [str(self.tree / "xvault-miner.py"), *flags]), \
                patch.object(self.m, "Config", return_value=self.cfg), \
                patch.object(self.m, "check_contracts", return_value="live") as check:
            self.m.main()
        return check

    def test_imports_are_from_selected_tree_not_cached_other_tree(self):
        self.assertEqual(Path(self.m.__file__).resolve(), self.tree / "xvault-miner.py")
        for name in ("tui", "config", "protocol", "cli_backend", "onboarding"):
            self.assertEqual(Path(sys.modules[name].__file__).resolve(), self.tree / (name + ".py"))
        self.assertIs(self.m.RPCError, self.protocol.RPCError)
        self.assertIs(self.backend_module.RPCError, self.protocol.RPCError)
        self.assertIs(self.backend_module.WalletClient, self.protocol.WalletClient)
        self.assertEqual(self.m.CONFIG_PATH, self.home / ".xelis-vault/config/config.json")

    def test_fetch_golden_path_maps_entire_miner_and_uses_direct_daemon(self):
        live = self.m.fetch_live(self.b)
        self.assertTrue(live["connected"])
        self.assertTrue(live["miner_loaded"])
        self.assertEqual(live["error"], "")
        self.assertEqual(live["topo"], 1250)
        self.assertEqual(live["miner"], {
            "endpoint": OLD_ENDPOINT, "stake": 1000 * ATOMIC, "mask": 3,
            "registered_at": 100, "hb_topo": 1000, "rewards": 12 * ATOMIC,
            "slashed": 0, "reputation": 8200, "valid_submissions": 17,
            "anchors": 9, "total_submissions": 20, "active": True,
        })
        self.assertEqual(live["balances"], self.b.balances.return_value)
        self.assertEqual(live["stats"], self.b.miner_stats.return_value)
        self.assertEqual(live["feeds"], [{"name": "XEL/USD", "price_raw": 20_000_000,
                                          "age": 50, "stale": False}])
        self.assertEqual(live["relayer"], self.b.chat_relayer_status.return_value)
        self.b.daemon.topoheight.assert_called_once_with()
        self.b.topo.assert_not_called()
        self.b.chat_relayer_status.assert_called_once_with(ADDRESS)

    def test_fetch_read_only_without_feed_or_relayer_and_future_feed_age(self):
        self.b.has_wallet = False
        self.b.price.return_value = None
        live = self.m.fetch_live(self.b)
        self.assertTrue(live["connected"])
        self.assertEqual(live["feeds"], [])
        self.assertIsNone(live["relayer"])
        self.b.chat_relayer_status.assert_not_called()
        self.b.price.return_value = (20_000_000, 2000, True)
        self.assertEqual(self.m.fetch_live(self.b)["feeds"][0]["age"], 0)

    def test_fetch_real_absence_is_distinct_from_unknown_registration(self):
        self.b.my_miner.return_value = None
        live = self.m.fetch_live(self.b)
        self.assertTrue(live["miner_loaded"])
        self.assertTrue(live["connected"])
        self.assertEqual(live["miner"], {})
        self.m.render_dashboard(self.cfg, live)
        self.assertIn("Not registered", self.output())
        self.assertNotIn("Miner status unavailable", self.output())

    def test_fetch_missing_operator_is_unknown_not_unregistered(self):
        self.b.address = ""
        live = self.m.fetch_live(self.b)
        self.assertFalse(live["connected"])
        self.assertFalse(live["miner_loaded"])
        self.assertIn("address unavailable", live["error"])
        self.b.my_miner.assert_not_called()
        self.m.render_dashboard(self.cfg, live)
        self.assertIn("Miner status unavailable", self.output())
        self.assertNotIn("Not registered", self.output())

    def test_fetch_persistent_rpc_failure_then_recovery_at_every_read_stage(self):
        for stage in ("daemon.topoheight", "balances", "my_miner", "miner_stats",
                      "price", "chat_relayer_status"):
            with self.subTest(stage=stage):
                b = self.backend()
                operation = b.daemon.topoheight if stage.startswith("daemon.") else getattr(b, stage)
                healthy = operation.return_value
                operation.side_effect = [self.m.RPCError("RPC offline"),
                                         self.m.RPCError("RPC offline"), healthy]
                for _ in range(2):
                    live = self.m.fetch_live(b)
                    self.assertFalse(live["connected"])
                    self.assertIn("RPC offline", live["error"])
                    self.assertEqual(live["miner_loaded"], stage in (
                        "miner_stats", "price", "chat_relayer_status"))
                    self.reset_output()
                    self.m.render_dashboard(self.cfg, live)
                    self.assertIn("UNAVAILABLE / INCOMPLETE READS", self.output())
                    self.assertNotIn("Not registered", self.output())
                recovered = self.m.fetch_live(b)
                self.assertTrue(recovered["connected"])
                self.assertTrue(recovered["miner_loaded"])
                self.assertEqual(recovered["error"], "")
                self.assertEqual(operation.call_count, 3)

    def test_fetch_does_not_retain_prior_success_after_outage(self):
        first = self.m.fetch_live(self.b)
        self.b.daemon.topoheight.side_effect = self.m.RPCError("lost connection")
        failed = self.m.fetch_live(self.b)
        self.assertTrue(first["connected"])
        self.assertFalse(failed["miner_loaded"])
        self.assertEqual(failed["miner"], {})
        self.assertEqual(failed["balances"], {})
        self.assertEqual(failed["feeds"], [])

    def test_fetch_malformed_miner_is_unknown_never_false_registration(self):
        bad_numeric = miner_record()
        bad_numeric[3] = "invalid stake"
        bad_null = miner_record()
        bad_null[9] = None
        for record in ([], [ADDRESS], miner_record()[:14], {}, "malformed", bad_numeric, bad_null):
            with self.subTest(record=record):
                self.b.my_miner.return_value = record
                live = self.m.fetch_live(self.b)
                self.assertFalse(live["connected"])
                self.assertFalse(live["miner_loaded"])
                self.assertEqual(live["miner"], {})
                self.assertTrue(live["error"])
                self.reset_output()
                self.m.render_dashboard(self.cfg, live)
                self.assertIn("Miner status unavailable", self.output())
                self.assertNotIn("Not registered", self.output())

    def test_dashboard_renders_real_panels_balances_feeds_and_endpoint_mismatch(self):
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b), "refresh hint")
        text = self.output()
        for expected in ("CONNECTED", "1,250", ADDRESS, "REGISTERED", "EXCELLENT",
                         "1,000.0000 VLT", "Oracle", "Chat relay", "$   0.2000",
                         "25%", "RELAYER", "refresh hint", "Not synchronized"):
            self.assertIn(expected, text)
        self.assertIn("On-chain endpoint: " + OLD_ENDPOINT, text)
        self.assertIn("Configured endpoint: " + NEW_ENDPOINT, text)
        self.assertEqual([c.args[0] for c in self.panels.call_args_list],
                         ["  MINER  STATUS", "  WALLET  BALANCE", "  PROTOCOL  STATS",
                          "  PRICE  FEEDS", "  RELAYER  (VaultChat)"])
        self.assertGreaterEqual(
            len(re.findall(r"(?m)^[╭┌+][-─]{20,}", text)), 5,
            "expected five panel top borders in the rendered dashboard")

    def test_endpoint_mismatch_advice_follows_deployed_capability(self):
        cases = (
            (True, "Actions > Update endpoint", None),
            (False, "developer upgrade", "Actions > Update endpoint"),
            (None, "capability unknown", "Actions > Update endpoint"),
        )
        for support, expected, forbidden in cases:
            with self.subTest(support=support):
                self.b.miner_supports_update_endpoint.return_value = support
                self.reset_output()
                self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
                text = self.output()
                self.assertIn("Not synchronized", text)
                self.assertIn(expected, text)
                if forbidden:
                    self.assertNotIn(forbidden, text)

    def test_dashboard_matching_endpoint_does_not_claim_unsynchronized(self):
        self.cfg.data["miner_endpoint"] = OLD_ENDPOINT
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
        self.assertNotIn("Configured endpoint", self.output())
        self.assertNotIn("Not synchronized", self.output())

    def test_dashboard_inactive_is_not_unregistered(self):
        self.b.my_miner.return_value[14] = False
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
        self.assertIn("INACTIVE", self.output())
        self.assertNotIn("Not registered", self.output())

    def test_dashboard_zero_budget_and_balances_are_real_zero_not_unknown(self):
        self.b.miner_stats.return_value.update(budget=0, distributed=0, min_stake=0)
        self.b.balances.return_value = {"XEL": 0, "VLT": None, "xUSD": 0}
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
        self.assertIn("Budget spent:  0%", self.output())
        self.assertIn("Reward budget: 0 VLT", self.output())
        self.assertIn("Min stake:     0 VLT", self.output())
        self.assertEqual(plain(self.m.bfmt(0, "VLT")), "0 VLT")
        self.assertEqual(plain(self.m.bfmt(None)), "--")
        self.assertEqual(plain(self.m.bfmt(1)), "0.00000001")

    def test_glyph_probe_uses_stdout_encoding_not_the_default_codec(self):
        # sys.getdefaultencoding() is always utf-8, so consulting it made the
        # ASCII fallback unreachable and box glyphs crash on a code page console.
        for encoding, expected in (("utf-8", True), ("cp1252", False), ("ascii", False)):
            with self.subTest(encoding=encoding):
                fake = Mock(spec=["encoding"])
                fake.encoding = encoding
                with patch.object(sys, "stdout", fake):
                    self.assertEqual(self.tui._stdout_can_encode("╭─░"), expected)
        with patch.object(sys, "stdout", Mock(spec=[])), \
                patch("locale.getpreferredencoding", return_value="cp1252"):
            self.assertFalse(self.tui._stdout_can_encode("╭─░"))
        with patch.object(sys, "stdout", Mock(spec=[])), \
                patch("locale.getpreferredencoding", return_value="utf-8"):
            self.assertTrue(self.tui._stdout_can_encode("╭─░"))

    def test_redirected_output_survives_glyphs_the_console_cannot_encode(self):
        def console():
            return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")

        raw = console()
        with self.assertRaises(UnicodeEncodeError):
            raw.write("╭")
        for stream in (console(), io.StringIO()):
            with patch.object(sys, "stdout", stream), patch.object(sys, "stderr", stream):
                self.tui._harden_streams()
            if hasattr(stream, "reconfigure"):
                self.assertEqual(stream.errors, "replace")
                stream.write("╭")
                stream.flush()

    def test_banner_ink_matches_the_active_glyph_set(self):
        banner = self.m.BANNER
        self.assertEqual(chr(0x2588) in banner, self.tui._BLOCK_FULL == chr(0x2588))
        self.assertIn(self.tui._BLOCK_FULL, banner)
        self.assertIn("Privacy-First DeFi on XELIS BlockDAG", plain(banner))

    def test_dashboard_heartbeat_uses_chain_hi_ht_including_boundaries(self):
        self.b.miner_stats.return_value.update(heartbeat_interval=20, heartbeat_timeout=80)
        for age, expected in ((19, "19 blk ago"), (20, "20 blk ago — due"),
                              (80, "80 blk ago — due"), (81, "timeout exceeded")):
            with self.subTest(age=age):
                self.reset_output()
                self.b.daemon.topoheight.return_value = 1000 + age
                self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
                hb = self.panel_text("MINER  STATUS")
                self.assertIn(expected, hb)
                if age < 20:
                    self.assertNotIn("— due", hb)
                    self.assertNotIn("timeout exceeded", hb)

    def test_dashboard_missing_schedule_is_unknown_not_hardcoded_defaults(self):
        self.b.miner_stats.return_value = {}
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
        self.assertIn("schedule unknown", self.panel_text("MINER  STATUS"))
        self.assertNotIn("— due", self.panel_text("MINER  STATUS"))

    def test_tier_thresholds_and_service_masks(self):
        for reputation, tier in ((0, "LOW"), (999, "LOW"), (1000, "CRITICAL"),
                                 (1999, "CRITICAL"), (2000, "WARNING"), (4999, "WARNING"),
                                 (5000, "GOOD"), (7999, "GOOD"), (8000, "EXCELLENT")):
            with self.subTest(reputation=reputation):
                self.assertEqual(self.m.tier_name(reputation), tier)
        self.assertIn("none", plain(self.m.svc_badges(0)))
        self.assertNotIn("Chat relay", plain(self.m.svc_badges(1)))
        self.assertNotIn("Oracle", plain(self.m.svc_badges(2)))

    def test_setup_only_saves_local_configuration_never_instantiates_backend(self):
        self.text.side_effect = [RPC, WALLET, ADDRESS, "  " + NEW_ENDPOINT + "  "]
        self.menu.side_effect = None
        self.menu.return_value = "oracle"
        self.m.interactive_setup(self.cfg)
        self.assertEqual(self.cfg.get("miner_endpoint"), NEW_ENDPOINT)
        self.assertEqual(self.cfg.get("services"), "oracle")
        self.save.assert_called_once_with()
        self.factory.assert_not_called()
        self.assertEqual(self.b.mock_calls, [])
        self.spawn.assert_not_called()
        self.assertIn("Saved locally only", self.info_text())
        self.assertIn("on-chain settings are unchanged", self.info_text())
        self.assertIn("Setup Complete", self.output())

    def test_endpoint_success_retries_same_config_when_chain_differs(self):
        self.endpoint_input("  " + NEW_ENDPOINT + "  ")
        operation = self.result("miner_update_endpoint")
        self.m.action_update_endpoint(self.cfg, self.b)
        operation.assert_called_once_with(NEW_ENDPOINT)
        self.save.assert_called_once_with()
        self.assertIn(OLD_ENDPOINT, self.text.call_args.args[0])
        self.assertEqual(self.text.call_args.args[1], NEW_ENDPOINT)
        self.assertIn("On-chain endpoint verified", self.output())
        self.assertIn(TX, self.info_text())
        self.b.wallet.address.assert_not_called()
        self.b.wallet.invoke.assert_not_called()

    def test_endpoint_failed_verification_keeps_desired_but_dashboard_uses_chain(self):
        self.endpoint_input()
        self.result("miner_update_endpoint", ok=False, tx="", reason="deployment needs migration")
        self.m.action_update_endpoint(self.cfg, self.b)
        self.assertEqual(self.cfg.get("miner_endpoint"), NEW_ENDPOINT)
        self.assertIn("deployment needs migration", self.output())
        self.assertNotIn("On-chain endpoint verified", self.output())
        self.m.render_dashboard(self.cfg, self.m.fetch_live(self.b))
        self.assertIn("On-chain endpoint: " + OLD_ENDPOINT, self.output())
        self.assertIn("Not synchronized", self.output())

    def test_endpoint_pending_retains_full_hash_and_warns_before_retry(self):
        self.endpoint_input()
        operation = self.result("miner_update_endpoint", ok=False, tx=TX,
                                reason="pending: readback unavailable")
        self.m.action_update_endpoint(self.cfg, self.b)
        self.assertIn(TX, self.info_text())
        self.assertIn("Check transaction/status before retrying", self.info_text())
        self.assertIn("pending", self.output())
        self.assertNotIn("On-chain endpoint verified", self.output())
        operation.assert_called_once_with(NEW_ENDPOINT)

    def test_endpoint_matching_chain_is_noop_even_when_local_config_differs(self):
        self.endpoint_input(OLD_ENDPOINT)
        self.m.action_update_endpoint(self.cfg, self.b)
        self.assertEqual(self.cfg.get("miner_endpoint"), OLD_ENDPOINT)
        self.save.assert_called_once_with()
        self.confirm.assert_not_called()
        self.b.miner_update_endpoint.assert_not_called()
        self.assertIn("already matches on-chain", self.output())

    def test_endpoint_cancel_or_empty_never_saves_or_sends(self):
        for value, confirmed in (("   ", True), ("https://cancel.invalid", False)):
            with self.subTest(value=value):
                self.endpoint_input(value, confirmed)
                self.m.action_update_endpoint(self.cfg, self.b)
                self.assertEqual(self.cfg.get("miner_endpoint"), NEW_ENDPOINT)
                self.save.assert_not_called()
                self.b.miner_update_endpoint.assert_not_called()

    def test_endpoint_missing_wallet_registration_or_rpc_read_fails_closed(self):
        for condition in ("wallet", "registration", "rpc"):
            with self.subTest(condition=condition):
                b = self.backend()
                self.reset_output()
                if condition == "wallet":
                    b.has_wallet = False
                elif condition == "registration":
                    b.my_miner.return_value = None
                else:
                    b.my_miner.side_effect = self.m.RPCError("TLS unavailable")
                self.m.action_update_endpoint(self.cfg, b)
                self.text.assert_not_called()
                self.save.assert_not_called()
                b.miner_update_endpoint.assert_not_called()
                if condition == "rpc":
                    self.assertIn("Cannot read miner status", self.output())
                    self.assertNotIn("Not registered", self.output())

    def test_endpoint_identity_validation_is_delegated_to_real_backend(self):
        b = object.__new__(self.backend_module.Backend)
        b.cfg = self.cfg.data
        b.contracts = {"miner": "aa" * 32}
        b.daemon = Mock(spec=self.protocol.DaemonClient)
        b.daemon.read_key.return_value = miner_record()
        b.wallet = Mock(spec=self.protocol.WalletClient)
        b.wallet.address.return_value = "xet:different-wallet"
        b.wallet.invoke.side_effect = forbidden
        self.endpoint_input()
        self.m.action_update_endpoint(self.cfg, b)
        b.wallet.address.assert_called_once_with()
        b.wallet.invoke.assert_not_called()
        self.assertIn("Endpoint not verified", self.output())
        self.assertRegex(self.info_text().lower(), r"mismatch|does not match")
        self.assertNotIn("On-chain endpoint verified", self.output())

    def test_endpoint_malformed_record_reports_error_without_transaction(self):
        self.b.my_miner.return_value = [ADDRESS]
        self.m.action_update_endpoint(self.cfg, self.b)
        self.b.miner_update_endpoint.assert_not_called()
        self.save.assert_not_called()
        self.assertRegex(self.info_text().lower(), r"invalid|malformed|unavailable")

    def test_registration_golden_path_uses_atomic_stake_and_service_mask(self):
        self.b.my_miner.return_value = None
        self.b.miner_stake_min.return_value = 1000 * ATOMIC
        self.endpoint_input("1000.5")
        operation = self.result("miner_register")
        self.m.action_registration_flow(self.cfg, self.b)
        operation.assert_called_once_with(NEW_ENDPOINT, 3, 1000 * ATOMIC + ATOMIC // 2)
        self.assertEqual(self.text.call_args.kwargs["default"], "1000")
        self.assertIn("Registration broadcast", self.output())
        self.assertIn("registration not yet verified", self.output())

    def test_registration_existing_profile_and_read_failure_never_register(self):
        self.m.action_registration_flow(self.cfg, self.b)
        self.b.miner_register.assert_not_called()
        self.text.assert_not_called()
        self.b.my_miner.side_effect = self.m.RPCError("offline")
        with self.assertRaises(self.m.RPCError):
            self.m.action_registration_flow(self.cfg, self.b)
        self.b.miner_register.assert_not_called()
        self.text.assert_not_called()

    def test_heartbeat_success_rejection_and_no_wallet(self):
        operation = self.result("miner_heartbeat")
        self.m.action_heartbeat(self.cfg, self.b)
        operation.assert_called_once_with()
        self.assertIn("Heartbeat sent", self.output())
        self.reset_output()
        operation.return_value = self.backend_module.OpResult(False, reason="toosoon")
        self.m.action_heartbeat(self.cfg, self.b)
        self.assertIn("toosoon", self.output())
        self.b.has_wallet = False
        operation.reset_mock()
        self.m.action_heartbeat(self.cfg, self.b)
        operation.assert_not_called()

    def test_stake_and_service_actions_delegate_correct_types(self):
        self.endpoint_input("2.5")
        stake = self.result("miner_increase_stake")
        self.m.action_increase_stake(self.cfg, self.b)
        stake.assert_called_once_with(250_000_000)
        self.menu.side_effect = None
        self.menu.return_value = self.m.SERVICE_CHAT
        enable = self.result("miner_enable_service")
        self.m.action_enable_service(self.cfg, self.b)
        enable.assert_called_once_with(2)

    def keeper_launch_mocks(self, detached=None):
        self.p("LOG_DIR", new=MagicMock(spec=Path))
        self.m.LOG_DIR.__truediv__.return_value = self.home / "keeper.log"
        self.pid.write_text.side_effect = None
        self.spawn.side_effect = None
        self.spawn.return_value = Mock(pid=9876)
        log = self.p("open", new=mock_open(), create=True)
        detach = self.stack.enter_context(patch.object(
            self.onboarding, "_detached_kwargs", return_value=detached or {"start_new_session": True}))
        return log, detach

    def test_keeper_launch_saves_config_passes_rpc_unbuffered_detached_and_closes_log(self):
        for detached in ({"start_new_session": True}, {"creationflags": 520}):
            with self.subTest(detached=detached):
                self.save.reset_mock()
                self.spawn.reset_mock()
                self.pid.write_text.reset_mock()
                log, detach = self.keeper_launch_mocks(detached)
                order = Mock()
                order.attach_mock(self.save, "save")
                order.attach_mock(self.spawn, "spawn")
                order.attach_mock(self.pid.write_text, "pid")
                self.m.launch_keeper(self.cfg)
                self.assertEqual([c[0] for c in order.mock_calls], ["save", "spawn", "pid"])
                args = self.spawn.call_args.args[0]
                self.assertEqual(args, [sys.executable, "-u", str(self.tree / "oracle_keeper3.py"),
                                        "--config", str(self.m.CONFIG_PATH), "--rpc", RPC])
                self.assertEqual(self.spawn.call_args.kwargs,
                                 dict(stdout=log.return_value.__enter__.return_value,
                                      stderr=log.return_value.__enter__.return_value, **detached))
                detach.assert_called_once_with()
                log.assert_called_once_with(self.home / "keeper.log", "ab")
                log.return_value.__enter__.assert_called_once_with()
                log.return_value.__exit__.assert_called_once_with(None, None, None)
                self.pid.write_text.assert_called_once_with("9876")
                self.assertIn("not yet verified", self.info_text())
                for secret in ("fake-rpc-secret", "fake-wallet-secret", "fake-seed-never-read", WALLET):
                    self.assertNotIn(secret, repr(self.spawn.call_args) + self.output())

    def test_keeper_duplicate_guard_does_not_save_spawn_open_or_write_pid(self):
        log, detach = self.keeper_launch_mocks()
        self.keeper_running.return_value = 9876
        self.m.launch_keeper(self.cfg)
        self.save.assert_not_called()
        self.spawn.assert_not_called()
        log.assert_not_called()
        self.pid.write_text.assert_not_called()
        self.assertIn("already running", self.output())

    def test_keeper_requires_script_and_all_operator_configuration(self):
        log, detach = self.keeper_launch_mocks()
        for key in ("rpc_url", "wallet_url", "miner_address"):
            with self.subTest(missing=key), patch.dict(self.cfg.data, {key: ""}):
                self.m.launch_keeper(self.cfg)
        with patch.object(Path, "exists", return_value=False):
            self.m.launch_keeper(self.cfg)
        self.save.assert_not_called()
        self.spawn.assert_not_called()
        log.assert_not_called()
        self.pid.write_text.assert_not_called()
        self.assertIn("not found", self.info_text())

    def test_keeper_save_log_spawn_and_pid_errors_are_visible_without_success(self):
        for stage in ("save", "log", "spawn", "pid"):
            with self.subTest(stage=stage):
                self.reset_output()
                self.save.side_effect = None
                self.save.reset_mock()
                self.spawn.reset_mock()
                self.pid.write_text.reset_mock()
                log, detach = self.keeper_launch_mocks()
                target = {"save": self.save, "log": log, "spawn": self.spawn,
                          "pid": self.pid.write_text}[stage]
                target.side_effect = OSError(stage + " blocked")
                self.m.launch_keeper(self.cfg)
                self.assertIn("Could not launch: " + stage + " blocked", self.info_text())
                self.assertNotIn("Keeper launched", self.info_text())
                if stage in ("save", "log"):
                    self.spawn.assert_not_called()
                if stage != "pid":
                    self.pid.write_text.assert_not_called()
                if stage in ("spawn", "pid"):
                    log.return_value.__exit__.assert_called_once()
                target.side_effect = None

    def test_keeper_stop_handles_absent_process_and_failed_signal(self):
        self.m.stop_keeper()
        self.assertIn("not running", self.output())
        self.keeper_running.return_value = 9876
        with patch.object(self.onboarding, "terminate_process",
                          return_value=False) as term:
            self.m.stop_keeper()
        term.assert_called_once_with(9876)
        self.pid.unlink.assert_not_called()
        self.assertIn("Could not stop pid 9876", self.output())
        self.pid.unlink.side_effect = None
        self.pid.unlink.reset_mock()
        self.reset_output()
        with patch.object(self.onboarding, "terminate_process",
                          return_value=True) as term:
            self.m.stop_keeper()
        term.assert_called_once_with(9876)
        self.pid.unlink.assert_called_once_with(missing_ok=True)
        self.assertIn("Stopped pid 9876", self.output())
        self.assertNotIn("Could not stop", self.output())

    def test_provider_guide_renders_and_dispatches_launch_stop_then_back(self):
        self.menu.side_effect = ["keeper", "stopkeeper", None]
        self.keeper_running.side_effect = [None, 9876, None]
        launch = self.p("launch_keeper")
        stop = self.p("stop_keeper")
        self.m.provider_guide(self.cfg)
        launch.assert_called_once_with(self.cfg)
        stop.assert_called_once_with()
        self.assertIn("PRICE PROVIDER", self.output())
        self.assertIn("hi = heartbeat minimum interval", self.output())
        self.assertIn("ht = heartbeat timeout", self.output())

    def test_main_quit_tokens_restore_cursor_without_writes(self):
        for key in ("Q", "CTRL_C", "CTRL_D"):
            with self.subTest(key=key):
                self.show.reset_mock()
                self.hide.reset_mock()
                check = self.run_main([key])
                check.assert_called_once_with(self.cfg)
                self.show.assert_called_once_with()
                self.hide.assert_called_once_with()
        self.assertIn("Goodbye", self.output())
        self.save.assert_not_called()
        self.spawn.assert_not_called()

    def test_main_refresh_auto_toggle_and_timeouts(self):
        self.run_main([None, "r", "a", "a", "Q"])
        self.assertEqual(self.keys.call_args_list, [call(5), call(5), call(5), call(999), call(5)])
        self.assertIn("Auto-refreshed at", self.output())
        self.assertIn("Manual refresh at", self.output())
        self.assertIn("Auto-refresh: OFF", self.output())
        self.assertIn("Auto-refresh: ON", self.output())
        self.assertEqual(self.b.daemon.topoheight.call_count, 5)

    def test_main_rpc_outage_refreshes_until_recovered_instead_of_exiting(self):
        self.b.daemon.topoheight.side_effect = [self.m.RPCError("offline"),
                                              self.m.RPCError("offline"), 1250]
        self.run_main(["r", "r", "Q"])
        self.assertEqual(self.b.daemon.topoheight.call_count, 3)
        self.assertEqual(self.output().count("Miner status unavailable"), 2)
        self.assertIn("CONNECTED", self.output())
        self.assertNotIn("Not registered", self.output())
        self.assertEqual(self.show.call_count, 1)

    def test_main_catches_rpc_errors_from_actions_provider_and_heartbeat(self):
        for key, name in (("m", "action_menu"), ("p", "provider_guide"), ("h", "action_heartbeat")):
            with self.subTest(action=name):
                self.reset_output()
                with patch.object(self.m, name, side_effect=self.m.RPCError("result unknown")) as action:
                    self.run_main([key, "Q"])
                action.assert_called_once()
                self.assertIn("RPC unavailable", self.output())
                self.assertIn("Check transaction/status before retrying", self.info_text())
                self.assertIn("Goodbye", self.output())

    def test_main_restores_cursor_even_if_render_or_keyboard_raises(self):
        for location, error in (("render_dashboard", RuntimeError("render failed")),
                                ("read_key_timeout", KeyboardInterrupt())):
            with self.subTest(location=location):
                self.show.reset_mock()
                if location == "render_dashboard":
                    with patch.object(self.m, location, side_effect=error), self.assertRaises(RuntimeError):
                        self.run_main()
                else:
                    with self.assertRaises(KeyboardInterrupt):
                        self.run_main([error])
                self.show.assert_called_once_with()
                self.assertIn("Goodbye", self.output())

    def test_main_signal_stops_loop_and_restores_cursor(self):
        def signal_during_read(timeout):
            self.signals.call_args_list[0].args[1](self.m.signal.SIGINT, None)
            return None
        with patch.object(sys, "argv", ["xvault-miner"]), \
                patch.object(self.m, "Config", return_value=self.cfg), \
                patch.object(self.m, "check_contracts"), \
                patch.object(self.m, "read_key_timeout", side_effect=signal_during_read):
            self.m.main()
        self.assertEqual(self.b.daemon.topoheight.call_count, 1)
        self.show.assert_called_once_with()

    def test_main_miner_flag_opens_menu_without_automatically_starting_pow(self):
        self.menu.side_effect = None
        self.menu.return_value = None
        self.run_main(["Q"], ["--miner"])
        self.menu.assert_called_once()
        self.assertEqual(self.menu.call_args.args[0], "Miner actions")
        self.start_pow.assert_not_called()
        self.stop_pow.assert_not_called()
        self.spawn.assert_not_called()
        self.keys.assert_called_once_with(5)

    def test_main_dry_run_blocks_setup_actions_keeper_and_miner_flag(self):
        actions = {name: self.p(name) for name in (
            "interactive_setup", "action_menu", "provider_guide", "action_heartbeat",
            "launch_keeper", "stop_keeper")}
        check = self.run_main(["s", "m", "p", "h", "r", "Q"], ["--dry-run", "--miner"])
        check.assert_not_called()
        for action in actions.values():
            action.assert_not_called()
        self.save.assert_not_called()
        self.spawn.assert_not_called()
        self.start_pow.assert_not_called()
        self.stop_pow.assert_not_called()
        self.pid.write_text.assert_not_called()
        self.assertIn("Read-only mode (--dry-run)", self.output())
        self.assertEqual(self.b.daemon.topoheight.call_count, 6)

    def test_main_dry_run_setup_conflict_exits_before_configuration_or_actions(self):
        with patch.object(sys, "argv", ["xvault-miner", "--dry-run", "--setup"]), \
                patch.object(self.m, "Config") as config, \
                patch.object(self.m, "interactive_setup") as setup, \
                self.assertRaises(SystemExit) as caught:
            self.m.main()
        self.assertEqual(caught.exception.code, 2)
        config.assert_not_called()
        setup.assert_not_called()
        self.factory.assert_not_called()
        self.assertIn("cannot be combined", self.err.getvalue())

    def test_main_setup_flag_and_hotkey_use_wizard_not_implicit_transaction(self):
        with patch.object(self.m, "interactive_setup") as setup:
            self.run_main(flags=["--setup"])
            setup.assert_called_once_with(self.cfg)
        self.factory.assert_not_called()
        with patch.object(self.m, "interactive_setup") as setup:
            self.run_main(["s", "Q"])
            setup.assert_called_once_with(self.cfg)
        self.save.assert_not_called()
        self.spawn.assert_not_called()

    def test_main_cli_overrides_reach_backend_without_saving_secrets(self):
        override = "https://override.invalid/json_rpc"
        self.run_main(flags=["--rpc", override, "--wallet-url", "http://127.0.0.1:29082",
                             "--services", "oracle", "--dry-run"])
        self.assertEqual(self.factory.call_args.args[0]["rpc_url"], override)
        self.assertEqual(self.factory.call_args.args[0]["services"], "oracle")
        self.assertEqual(self.factory.call_args.args[0]["wallet_url"], "http://127.0.0.1:29082")
        self.save.assert_not_called()
        for secret in ("fake-rpc-secret", "fake-wallet-secret", "fake-seed-never-read"):
            self.assertNotIn(secret, self.output())


class SourceMinerConsoleTests(MinerConsoleCases, unittest.TestCase):
    tree = TREES[0]


class InstalledMinerConsoleTests(MinerConsoleCases, unittest.TestCase):
    tree = TREES[1]


def load_tests(loader, tests, pattern):
    # Source first, so a concurrent installed-tree sync cannot mask source regressions.
    return unittest.TestSuite(loader.loadTestsFromTestCase(cls) for cls in (
        SourceMinerConsoleTests, InstalledMinerConsoleTests))


if __name__ == "__main__":
    unittest.main()
