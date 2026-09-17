"""Offline regression tests for both onboarding tunnel implementations."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
OLD_URL = "https://old-session.trycloudflare.com"
NEW_URL = "https://new-session.trycloudflare.com"
TX = "a" * 64


def profile(url):
    return {"registered": {"endpoint": url}}


class TunnelCases:
    """Shared cases run against source and runtime without importing real RPC/UI."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(sys, "path", list(sys.path)))
        self.backend = Mock()
        self.backend.chat_relayer_status.return_value = profile(OLD_URL)
        self.backend.chat_update_endpoint.return_value = SimpleNamespace(
            ok=True, tx=TX, reason="")
        self.backend_factory = Mock(return_value=self.backend)
        self.enterContext(patch.dict(sys.modules, {
            "requests": Mock(),
            "tui": Mock(),
            "cli_backend": SimpleNamespace(Backend=self.backend_factory),
        }))
        spec = importlib.util.spec_from_file_location(
            "tunnel_onboarding_under_test", ROOT / self.module_path)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.m.RELAYER_DIR = self.temp / "relayer"
        self.m.LOG_DIR = self.temp / "logs"
        self.m.LOG_DIR.mkdir()
        self.m.TUNNEL_LOG = self.m.LOG_DIR / "relayer-tunnel.log"
        self.m.TUNNEL_PID_FILE = self.m.RELAYER_DIR / "tunnel.pid"
        self.cfg = SimpleNamespace(data={
            "relayer_port": 18444,
            "rpc_url": "https://rpc.invalid",
            "wallet_url": "http://wallet.invalid",
            "wallet_user": "test-user",
            "wallet_pass": "test-pass",
            "contracts": {"VaultChat": "b" * 64},
            "network": "testnet",
            "custom_setting": "preserved",
        }, save=Mock())
        self.cfg.get = self.cfg.data.get
        self.proc = Mock(pid=43210)
        self.proc.poll.return_value = None
        self.handles = []
        self.m.subprocess = Mock()
        self.m.subprocess.Popen.side_effect = self.spawn
        self.m.time = Mock()
        self.m._detached_kwargs = Mock(return_value={})
        self.m.ensure_tunnel_binary = Mock(return_value=("cloudflared-test", "installed"))
        self.m.tunnel_running = Mock(return_value=None)
        self.m.start_relayer = Mock(return_value=(True, "relayer ready"))
        if hasattr(self.m, "tunnel_healthy"):
            self.m.tunnel_healthy = Mock(return_value=True)

    def spawn(self, *args, **kwargs):
        self.assertIs(kwargs["stdout"], kwargs["stderr"])
        self.assertFalse(kwargs["stdout"].closed)
        self.handles.append(kwargs["stdout"])
        return self.proc

    def log(self, text):
        self.m.TUNNEL_LOG.write_text(text, encoding="utf-8")

    def public_ready(self):
        self.m.start_tunnel = Mock(return_value=(True, "tunnel ready"))
        self.m.tunnel_running.return_value = self.proc.pid
        self.log(NEW_URL)

    def test_new_session_clears_old_url_before_child_writes(self):
        self.log(OLD_URL)
        observed = []

        def child_tick(_):
            observed.append(self.m.tunnel_url())
            if len(observed) == 2:
                self.log(NEW_URL)

        self.m.time.sleep.side_effect = child_tick
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertTrue(ok)
        self.assertEqual(observed, ["", ""])
        self.assertIn(NEW_URL, message)
        self.assertNotIn(OLD_URL, self.m.TUNNEL_LOG.read_text())
        self.assertTrue(self.handles[0].closed)
        self.assertEqual(self.m.TUNNEL_PID_FILE.read_text(), str(self.proc.pid))
        self.assertEqual(self.proc.poll.call_count, 2)

    def test_tunnel_url_keeps_last_match_within_session(self):
        self.log(OLD_URL + "\n" + NEW_URL)
        self.assertEqual(self.m.tunnel_url(), NEW_URL)

    def test_live_session_does_not_reset_log_or_launch(self):
        self.log(OLD_URL)
        self.m.tunnel_running.return_value = self.proc.pid
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertTrue(ok)
        self.assertIn(OLD_URL, message)
        self.assertEqual(self.m.TUNNEL_LOG.read_text(), OLD_URL)
        self.m.subprocess.Popen.assert_not_called()
        self.m.ensure_tunnel_binary.assert_not_called()

    def test_live_session_without_url_is_not_ready(self):
        self.log("still connecting")
        self.m.tunnel_running.return_value = self.proc.pid
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertFalse(ok)
        self.assertIn("URL not ready", message)
        self.assertEqual(self.m.TUNNEL_LOG.read_text(), "still connecting")
        self.m.subprocess.Popen.assert_not_called()

    def test_exited_process_is_rejected_even_with_url(self):
        for code in (0, 1):
            with self.subTest(exit_code=code):
                self.proc.poll.return_value = code
                self.m.time.sleep.side_effect = lambda _: self.log(NEW_URL)
                ok, message = self.m.start_tunnel(self.cfg)
                self.assertFalse(ok)
                self.assertIn(f"exited (code {code})", message)
                self.assertFalse(self.m.TUNNEL_PID_FILE.exists())
                self.assertTrue(self.handles[-1].closed)
        self.cfg.save.assert_not_called()

    def test_missing_url_times_out_without_accepting_old_log(self):
        self.log(OLD_URL)
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertFalse(ok)
        self.assertIn("URL not ready", message)
        self.assertEqual(self.m.time.sleep.call_count, 25)
        self.assertEqual(self.m.tunnel_url(), "")
        self.assertTrue(self.handles[0].closed)
        self.cfg.save.assert_not_called()

    def test_spawn_failure_closes_log(self):
        def fail(*args, **kwargs):
            self.spawn(*args, **kwargs)
            raise OSError("spawn denied")

        self.m.subprocess.Popen.side_effect = fail
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertFalse(ok)
        self.assertIn("spawn denied", message)
        self.assertTrue(self.handles[0].closed)
        self.assertFalse(self.m.TUNNEL_PID_FILE.exists())

    def test_public_relayer_failure_does_not_start_tunnel(self):
        self.public_ready()
        self.m.start_relayer.return_value = (False, "relayer failed")
        self.assertEqual(self.m.start_relayer_public(self.cfg), (False, "relayer failed"))
        self.m.start_tunnel.assert_not_called()
        self.backend_factory.assert_not_called()

    def test_public_tunnel_failure_does_not_use_old_url(self):
        self.public_ready()
        self.log(OLD_URL)
        self.m.start_tunnel.return_value = (False, "cloudflared exited")
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("cloudflared exited", message)
        self.backend_factory.assert_not_called()

    def test_public_missing_url_does_not_update(self):
        self.public_ready()
        self.log("")
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("URL not ready", message)
        self.backend_factory.assert_not_called()

    def test_public_process_death_does_not_update(self):
        self.public_ready()
        self.m.tunnel_running.return_value = None
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("exited", message)
        self.backend_factory.assert_not_called()

    def test_failed_update_is_not_success(self):
        self.public_ready()
        self.backend.chat_update_endpoint.return_value = SimpleNamespace(
            ok=False, tx=TX, reason="notregistered")
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("notregistered", message)
        self.assertIn(TX, message)
        self.assertEqual(self.backend.chat_relayer_status.call_count, 1)

    def test_update_exception_is_not_success(self):
        self.public_ready()
        self.backend.chat_update_endpoint.side_effect = RuntimeError("wallet unavailable")
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("wallet unavailable", message)

    def test_pending_or_unknown_readback_includes_tx_and_is_not_success(self):
        self.public_ready()
        for readback in (profile(OLD_URL), {}, None, {"registered": None},
                         RuntimeError("RPC unavailable")):
            with self.subTest(readback=readback):
                self.backend.chat_relayer_status.side_effect = [profile(OLD_URL), readback]
                ok, message = self.m.start_relayer_public(self.cfg)
                self.assertFalse(ok)
                self.assertIn("pending/unknown", message)
                self.assertIn(TX, message)
                self.assertNotIn("on-chain updated", message)

    def test_success_requires_readback_and_preserves_full_config(self):
        self.public_ready()
        self.backend.chat_relayer_status.side_effect = [profile(OLD_URL), profile(NEW_URL)]
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertTrue(ok)
        self.assertIn("on-chain updated", message)
        self.assertIn(TX, message)
        self.assertIs(self.backend_factory.call_args.args[0], self.cfg.data)
        self.backend.chat_update_endpoint.assert_called_once_with(NEW_URL)
        self.assertEqual(self.backend.chat_relayer_status.call_count, 2)
        self.cfg.save.assert_not_called()

    def test_existing_matching_endpoint_skips_write(self):
        self.public_ready()
        self.backend.chat_relayer_status.return_value = profile(NEW_URL)
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertTrue(ok)
        self.assertIn("already matches", message)
        self.backend.chat_update_endpoint.assert_not_called()
        self.backend.chat_relayer_status.assert_called_once_with()
        self.assertIs(self.backend_factory.call_args.args[0], self.cfg.data)


class SourceTunnelTests(TunnelCases, unittest.TestCase):
    module_path = "scripts/onboarding.py"


class RuntimeTunnelTests(TunnelCases, unittest.TestCase):
    module_path = "src/scripts/onboarding.py"

    def test_unhealthy_live_session_is_not_ready_and_keeps_log(self):
        self.log(NEW_URL)
        self.m.tunnel_running.return_value = self.proc.pid
        self.m.tunnel_healthy.return_value = False
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertFalse(ok)
        self.assertIn("unreachable", message)
        self.assertEqual(self.m.TUNNEL_LOG.read_text(), NEW_URL)
        self.m.subprocess.Popen.assert_not_called()

    def test_unhealthy_new_session_is_not_ready(self):
        self.m.time.sleep.side_effect = lambda _: self.log(NEW_URL)
        self.m.tunnel_healthy.return_value = False
        ok, message = self.m.start_tunnel(self.cfg)
        self.assertFalse(ok)
        self.assertIn("not yet reachable", message)
        self.assertTrue(self.handles[0].closed)

    def test_public_unreachable_url_does_not_update(self):
        self.public_ready()
        self.m.tunnel_healthy.return_value = False
        ok, message = self.m.start_relayer_public(self.cfg)
        self.assertFalse(ok)
        self.assertIn("unreachable", message)
        self.backend_factory.assert_not_called()

    def run_watchdog(self, cycles=1):
        statuses = []

        class StopWatchdog(BaseException):
            pass

        def tick(_):
            # The watchdog is intentionally endless. Observe status at its sleep
            # boundary, then interrupt without changing production control flow.
            statuses.append(dict(sys._getframe(1).f_locals["last_status"]))
            if len(statuses) == cycles:
                raise StopWatchdog()

        self.m.time.sleep = tick
        with self.assertRaises(StopWatchdog):
            self.m.watchdog_tunnel(self.cfg)
        return statuses

    def watchdog_ready(self):
        self.m.relayer_tunnel_status = Mock(return_value={
            "relayer_pid": 12345, "tunnel_pid": self.proc.pid, "url": NEW_URL})

    def test_watchdog_failed_start_does_not_use_stale_url(self):
        self.m.start_tunnel = Mock(return_value=(False, "cloudflared exited"))
        self.m.relayer_tunnel_status = Mock(return_value={
            "tunnel_pid": None, "url": OLD_URL})
        statuses = self.run_watchdog()
        self.assertFalse(statuses[0]["ok"])
        self.backend_factory.assert_not_called()

    def test_watchdog_does_not_cache_failed_update(self):
        self.watchdog_ready()
        self.backend.chat_update_endpoint.return_value = SimpleNamespace(
            ok=False, tx=TX, reason="notregistered")
        statuses = self.run_watchdog(cycles=2)
        self.assertTrue(all(not s["ok"] for s in statuses))
        self.assertEqual(self.backend.chat_update_endpoint.call_count, 2)

    def test_watchdog_pending_update_is_rechecked_and_then_skips_write(self):
        self.watchdog_ready()
        self.backend.chat_relayer_status.side_effect = [
            profile(OLD_URL), profile(OLD_URL), profile(NEW_URL)]
        statuses = self.run_watchdog(cycles=2)
        self.assertFalse(statuses[0]["ok"])
        self.assertIn(TX, statuses[0]["endpoint"])
        self.assertTrue(statuses[1]["ok"])
        self.assertIn("already matches", statuses[1]["endpoint"])
        self.backend.chat_update_endpoint.assert_called_once_with(NEW_URL)
        self.assertIs(self.backend_factory.call_args.args[0], self.cfg.data)

    def test_watchdog_caches_only_confirmed_url(self):
        self.watchdog_ready()
        self.backend.chat_relayer_status.side_effect = [profile(OLD_URL), profile(NEW_URL)]
        statuses = self.run_watchdog(cycles=2)
        self.assertTrue(all(s["ok"] for s in statuses))
        self.backend.chat_update_endpoint.assert_called_once_with(NEW_URL)
        self.assertEqual(self.backend.chat_relayer_status.call_count, 2)

    def test_watchdog_unreachable_url_is_not_success(self):
        self.watchdog_ready()
        self.backend.chat_relayer_status.return_value = profile(NEW_URL)
        self.m.tunnel_healthy.return_value = False
        statuses = self.run_watchdog()
        self.assertFalse(statuses[0]["ok"])
        self.assertFalse(statuses[0]["healthy"])
        self.backend.chat_update_endpoint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
