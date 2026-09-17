"""Offline regressions for the shared pid-liveness helpers, run against both trees.

Run: venv/Scripts/python.exe -B -m unittest discover -s tests -p test_process_status.py

Spawns throwaway python children and writes pid files inside a temp dir only;
touches no network, wallet, contract or project file.
"""
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEAD_PID = 2 ** 31 - 1


def load_onboarding(tree: str):
    path = ROOT / tree / "onboarding.py"
    name = "ob_" + tree.replace("/", "_").replace(os.sep, "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def wait_alive(module, pid, limit: float = 10.0) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if module.process_alive(pid):
            return True
        time.sleep(0.1)
    return False


class ProcessStatusCases:
    def setUp(self):
        self.ob = load_onboarding(self.tree)
        self.tmp = Path(tempfile.mkdtemp(prefix="pid-probe-"))

    def child(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    # -- probe ---------------------------------------------------------------
    def test_probe_reports_live_child_without_touching_it(self):
        proc = self.child()
        self.assertTrue(wait_alive(self.ob, proc.pid))
        self.assertIsNone(proc.poll(), "liveness probe must not terminate the child")

    def test_probe_sees_an_exited_child_as_dead(self):
        proc = self.child()
        proc.kill()
        proc.wait(timeout=20)
        self.assertFalse(self.ob.process_alive(proc.pid))

    def test_probe_rejects_unusable_pids_without_raising(self):
        for value in (None, "", "abc", 0, -1, DEAD_PID, 1.5):
            with self.subTest(pid=value):
                self.assertFalse(self.ob.process_alive(value))

    # -- terminate -----------------------------------------------------------
    def test_terminate_stops_a_live_child_and_reports_success(self):
        proc = self.child()
        self.assertTrue(wait_alive(self.ob, proc.pid))
        self.assertTrue(self.ob.terminate_process(proc.pid))
        self.assertIsNone(proc.poll())        # the test harness still owns the reap
        proc.wait(timeout=20)
        self.assertFalse(self.ob.process_alive(proc.pid))

    def test_terminate_of_an_unusable_pid_is_false_and_silent(self):
        for value in (DEAD_PID, 0, "abc"):
            with self.subTest(pid=value):
                self.assertFalse(self.ob.terminate_process(value))

    # -- pid-file plumbing ----------------------------------------------------
    def test_miner_running_keeps_pid_of_live_process_and_never_kills_it(self):
        proc = self.child()
        self.assertTrue(wait_alive(self.ob, proc.pid))
        pid_file = self.tmp / "miner.pid"
        pid_file.write_text(str(proc.pid))
        self.ob.MINER_PID_FILE = pid_file
        self.assertEqual(self.ob.miner_running(), proc.pid)
        self.assertTrue(pid_file.exists())
        self.assertIsNone(proc.poll(), "a status read must not terminate the miner")

    def test_stale_pid_file_is_dropped_on_read(self):
        pid_file = self.tmp / "miner.pid"
        pid_file.write_text(str(DEAD_PID))
        self.ob.MINER_PID_FILE = pid_file
        self.assertIsNone(self.ob.miner_running())
        self.assertFalse(pid_file.exists())

    def test_stop_miner_reports_not_running_once_the_process_is_gone(self):
        proc = self.child()
        pid_file = self.tmp / "miner.pid"
        pid_file.write_text(str(proc.pid))
        self.ob.MINER_PID_FILE = pid_file
        stopped, message = self.ob.stop_miner()
        self.assertTrue(stopped, message)
        self.assertFalse(pid_file.exists())
        stopped, message = self.ob.stop_miner()
        self.assertFalse(stopped)
        self.assertIn("not running", message)


class SourceProcessStatus(ProcessStatusCases, unittest.TestCase):
    tree = "scripts"


class InstalledProcessStatus(ProcessStatusCases, unittest.TestCase):
    tree = "src/scripts"


if __name__ == "__main__":
    unittest.main()
