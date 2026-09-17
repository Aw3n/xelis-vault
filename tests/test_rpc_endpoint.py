"""Offline RPC/endpoint regressions for source and installed trees independently.

Run: python -B -m unittest discover -s tests -p test_rpc_endpoint.py -v
Only unittest/stdlib test helpers are used; all HTTP and wallet writes are mocked.
"""
import importlib
import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "scripts", ROOT / "src" / "scripts")
WALLET_URL = "https://wallet.invalid/json_rpc"
DAEMON_URL = "https://configured-daemon.invalid/json_rpc"
ADDRESS = "xet:offline-miner"
CONTRACT = "a" * 64
TX = "b" * 64
OLD_ENDPOINT = "https://old.invalid"
NEW_ENDPOINT = "https://new.invalid"


@contextmanager
def isolated_tree(tree):
    """Never let cli_backend reuse the other tree's cached protocol import."""
    names = ("protocol", "cli_backend")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    old_path = sys.path[:]
    try:
        for name in names:
            sys.modules.pop(name, None)
        sys.path[:] = [str(tree)] + [
            path for path in old_path if Path(path).resolve() not in TREES
        ]
        importlib.invalidate_caches()
        protocol = importlib.import_module("protocol")
        backend = importlib.import_module("cli_backend")
        yield protocol, backend
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        sys.path[:] = old_path


class Clock:
    """Advance deadlines without wall-clock sleeps or unbounded polling."""
    def __init__(self):
        self.now = 1000.0
        self.sleep = Mock(side_effect=self.advance)

    def advance(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now

    def time(self):
        return self.now


def miner_record(endpoint):
    return [ADDRESS, endpoint, "c" * 64, 1000, 1, 0, 100, 0, 0,
            1000, 0, 0, 0, 0, True]


def deployed_module():
    # The real RPC result nests chunk metadata below data.module.chunks.
    chunks = [{"type": "internal", "value": {}} for _ in range(88)]
    chunks.append({"type": "entry", "value": {
        "parameters": [{"type": "string"}]
    }})
    return {"data": {"module": {"chunks": chunks}}}


class RpcEndpointCases:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.create_connection", "socket.socket.connect",
                       "socket.socket.connect_ex", "subprocess.Popen"):
            self.stack.enter_context(patch(
                target, side_effect=AssertionError("Real network/process forbidden")))
        self.p, self.b = self.stack.enter_context(isolated_tree(self.tree))
        self.assertEqual(Path(self.p.__file__).resolve(), self.tree / "protocol.py")
        self.assertEqual(Path(self.b.__file__).resolve(), self.tree / "cli_backend.py")
        self.assertIs(self.b.WalletClient, self.p.WalletClient)
        self.assertIs(self.b.RPCError, self.p.RPCError)
        self.stack.enter_context(patch.object(
            self.p.requests.sessions.Session, "request",
            side_effect=AssertionError("Unmocked HTTP forbidden")))
        self.post = self.stack.enter_context(patch.object(
            self.p.requests, "post",
            side_effect=AssertionError("Unexpected HTTP call")))
        self.clock = Clock()
        self.stack.enter_context(patch.object(self.p, "time", self.clock))
        self.stack.enter_context(patch.object(self.b, "time", self.clock))

    def tearDown(self):
        for request in self.post.call_args_list:
            self.assertIsNot(request.kwargs.get("verify", True), False,
                             "TLS verification must never be disabled")

    def response(self, payload=None, status=200, bad_json=False):
        response = Mock(status_code=status)
        response.json.return_value = payload
        if bad_json:
            response.json.side_effect = ValueError("HTML, not JSON")
        if status >= 400:
            response.raise_for_status.side_effect = self.p.requests.exceptions.HTTPError(
                f"HTTP {status}", response=response)
        return response

    def failure(self, kind):
        exc = self.p.requests.exceptions
        if kind == "ssl":
            return exc.SSLError("UNEXPECTED_EOF_WHILE_READING")
        if kind == "connection":
            return exc.ConnectionError("response connection lost")
        if kind == "timeout":
            return exc.Timeout("response timed out")
        if kind == "bad_json":
            return self.response(bad_json=True)
        return self.response(status=int(kind))

    def set_responses(self, *responses):
        outcomes = iter(responses)

        def respond(*args, **kwargs):
            # Check every attempt, including earlier subtests whose mocks reset.
            self.assertIsNot(kwargs.get("verify", True), False,
                             "TLS verification must never be disabled")
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        self.post.reset_mock()
        self.post.side_effect = respond
        self.clock.sleep.reset_mock()

    def wallet(self):
        return self.p.WalletClient(WALLET_URL, ("test-user", "test-pass"),
                                   daemon_url=DAEMON_URL)

    def backend(self):
        # Backend.__init__ resolves registries over the network: never call it.
        backend = object.__new__(self.b.Backend)
        backend.cfg = {"miner_address": ADDRESS, "rpc_url": DAEMON_URL}
        backend.contracts = {"miner": CONTRACT, "XelisVaultMiner": CONTRACT}
        backend.wallet = Mock(spec=self.p.WalletClient)
        backend.wallet.address.return_value = ADDRESS
        backend.wallet.invoke.return_value = TX
        backend.daemon = Mock(spec=self.p.DaemonClient)
        backend.daemon.read_key.return_value = miner_record(OLD_ENDPOINT)
        backend.daemon._call.return_value = deployed_module()
        return backend

    def assert_endpoint_invoke(self, backend):
        backend.wallet.invoke.assert_called_once_with(
            CONTRACT, 88, params=[self.p.val_str(NEW_ENDPOINT)],
            deposits={}, max_gas=5_000_000)

    def assert_pending(self, result):
        self.assertIsInstance(result, self.b.OpResult)
        self.assertFalse(result.ok)
        self.assertEqual(result.tx, TX)
        self.assertRegex(result.reason.lower(), r"pending|not.*verified|unverified")
        self.assertIn("retry", result.reason.lower())

    def test_post_read_exhausts_three_attempts_with_only_2_4_sleeps(self):
        for kind in ("ssl", "connection", "timeout", "429", "503", "bad_json"):
            with self.subTest(failure=kind):
                self.set_responses(*(self.failure(kind) for _ in range(3)))
                with self.assertRaises(self.p.RPCError) as caught:
                    self.p._post(DAEMON_URL, "get_nonce", {"address": ADDRESS})
                self.assertTrue(caught.exception.transient)
                self.assertEqual(self.post.call_count, 3)
                self.assertEqual(self.clock.sleep.call_args_list, [call(2), call(4)])
                self.assertIsNotNone(caught.exception.__cause__)

    def test_post_reads_recover_from_each_retryable_failure(self):
        for kind in ("ssl", "connection", "timeout", "429", "503", "bad_json"):
            with self.subTest(failure=kind):
                self.set_responses(self.failure(kind), self.failure(kind),
                                   self.response({"result": {"nonce": 8}}))
                self.assertEqual(self.p._post(DAEMON_URL, "get_nonce", None),
                                 {"nonce": 8})
                self.assertEqual(self.post.call_count, 3)
                self.assertEqual(self.clock.sleep.call_args_list, [call(2), call(4)])

    def test_post_auth_and_certificate_failures_are_immediate(self):
        failures = [self.response(status=401), self.p.requests.exceptions.SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")]
        for failure in failures:
            with self.subTest(failure=str(failure)):
                self.set_responses(failure)
                with self.assertRaises(self.p.RPCError) as caught:
                    self.p._post(WALLET_URL, "get_address", None)
                self.assertFalse(caught.exception.transient)
                self.post.assert_called_once()
                self.clock.sleep.assert_not_called()

    def test_post_preserves_rpc_application_error_without_transport_retry(self):
        for message, transient in (("not enough funds", False),
                                   ("Invalid nonce, expected 8", True),
                                   ("permission denied", False)):
            with self.subTest(message=message):
                self.set_responses(self.response({"error": {
                    "code": -32000, "message": message}}))
                with self.assertRaises(self.p.RPCError) as caught:
                    self.p._post(DAEMON_URL, "get_contract_data", {})
                self.assertIn(message, str(caught.exception))
                self.assertEqual(caught.exception.transient, transient)
                self.post.assert_called_once()
                self.clock.sleep.assert_not_called()

    def test_post_invalid_json_rpc_envelopes_are_not_success(self):
        for payload in (None, [], "html", {}, {"unrelated": 1},
                        {"error": "invalid"}, {"error": ["invalid"]}):
            with self.subTest(payload=payload):
                self.set_responses(*(self.response(payload) for _ in range(3)))
                with self.assertRaises(self.p.RPCError):
                    self.p._post(DAEMON_URL, "get_nonce", None)
                self.assertEqual(self.post.call_count, 3)
                self.assertEqual(self.clock.sleep.call_args_list, [call(2), call(4)])

    def test_post_success_preserves_auth_payload_timeout_and_tls(self):
        self.set_responses(self.response({"result": None}))
        auth = ("test-user", "test-pass")
        self.assertIsNone(self.p._post(WALLET_URL, "get_address", None, auth, timeout=9))
        self.post.assert_called_once_with(
            WALLET_URL, auth=auth, json={"jsonrpc": "2.0", "method": "get_address", "id": 1},
            timeout=9)
        self.clock.sleep.assert_not_called()

    def test_write_response_loss_never_replays_in_post_or_outer_retries(self):
        for outer in (False, True):
            for kind in ("ssl", "connection", "timeout", "429", "503", "bad_json"):
                with self.subTest(outer_retries=outer, failure=kind):
                    self.set_responses(self.failure(kind))
                    operation = Mock(side_effect=lambda: self.p._post(
                        WALLET_URL, "build_transaction", {"broadcast": True}))
                    with self.assertRaises(self.p.RPCError) as caught:
                        if outer:
                            self.p._with_retries(operation)
                        else:
                            operation()
                    self.assertFalse(caught.exception.transient)
                    self.assertIn("result unknown", str(caught.exception).lower())
                    operation.assert_called_once_with()
                    self.post.assert_called_once()
                    self.clock.sleep.assert_not_called()

    def test_outer_retries_never_replay_raw_transport_exceptions(self):
        for kind in ("ssl", "connection", "timeout"):
            with self.subTest(failure=kind):
                operation = Mock(side_effect=self.failure(kind))
                self.clock.sleep.reset_mock()
                with self.assertRaises(self.p.RPCError) as caught:
                    self.p._with_retries(operation)
                self.assertFalse(caught.exception.transient)
                self.assertIn("unknown", str(caught.exception))
                operation.assert_called_once_with()
                self.clock.sleep.assert_not_called()

    def test_outer_retries_still_allow_explicit_nonce_application_rejection(self):
        operation = Mock(side_effect=[self.p.RPCError("nonce expected 8", transient=True), TX])
        self.assertEqual(self.p._with_retries(operation), TX)
        self.assertEqual(operation.call_count, 2)
        self.clock.sleep.assert_called_once_with(8.0)

    def test_wallet_accepts_configured_daemon_and_normalizes_rpc_urls(self):
        for suffix in ("", "/", "///", "/json_rpc", "/json_rpc/"):
            with self.subTest(suffix=suffix):
                wallet = self.p.WalletClient("https://wallet.invalid" + suffix,
                                            daemon_url="https://daemon.invalid" + suffix)
                self.assertEqual(wallet.url, "https://wallet.invalid/json_rpc")
                self.assertEqual(wallet.daemon_url, "https://daemon.invalid/json_rpc")
                daemon = self.p.DaemonClient("https://daemon.invalid" + suffix)
                self.assertEqual(daemon.url, wallet.daemon_url)
        self.post.assert_not_called()

    def test_protocol_passes_its_daemon_url_to_wallet(self):
        protocol = self.p.Protocol(wallet_url=WALLET_URL, daemon_url=DAEMON_URL)
        self.assertEqual(protocol.wallet.daemon_url, protocol.daemon.url)
        self.assertEqual(protocol.wallet.daemon_url, DAEMON_URL)
        self.post.assert_not_called()

    def test_nonce_catchup_uses_configured_daemon_and_requires_equality(self):
        for daemon_nonce in ({"nonce": 8}, 8):
            with self.subTest(daemon_nonce=daemon_nonce):
                wallet = self.wallet()
                self.clock.sleep.reset_mock()
                with patch.object(wallet, "_call", side_effect=[ADDRESS, 7, 9, 8]) as wallet_rpc, \
                        patch.object(self.p, "_post", return_value=daemon_nonce) as daemon_rpc:
                    self.assertEqual(wallet._wait_nonce_catchup(timeout=20), 8)
                self.assertEqual(wallet_rpc.call_args_list,
                                 [call("get_address")] + [call("get_nonce")] * 3)
                self.assertEqual(daemon_rpc.call_args_list, [
                    call(DAEMON_URL, "get_nonce", {"address": ADDRESS})] * 3)
                self.assertEqual(self.clock.sleep.call_args_list, [call(5), call(5)])

    def test_invoke_never_builds_while_nonce_is_behind_or_ahead(self):
        for nonce in (7, 9):
            with self.subTest(wallet_nonce=nonce):
                wallet = self.wallet()

                def wallet_rpc(method, params=None):
                    if method == "get_address":
                        return ADDRESS
                    if method == "get_nonce":
                        return nonce
                    self.fail("build_transaction before nonce synchronization")

                with patch.object(wallet, "_call", side_effect=wallet_rpc) as rpc, \
                        patch.object(self.p, "_post", return_value={"nonce": 8}), \
                        patch.object(wallet, "wait_nonce_advance") as advance:
                    with self.assertRaisesRegex(self.p.RPCError, "synchronized"):
                        wallet.invoke(CONTRACT, 88, [self.p.val_str(NEW_ENDPOINT)])
                self.assertNotIn("build_transaction", [c.args[0] for c in rpc.call_args_list])
                advance.assert_not_called()

    def test_invoke_never_builds_when_nonce_synchronization_read_fails(self):
        wallet = self.wallet()
        with patch.object(wallet, "_call", side_effect=[ADDRESS, 8]) as wallet_rpc, \
                patch.object(self.p, "_post", side_effect=self.p.RPCError("TLS read failed")), \
                patch.object(wallet, "wait_nonce_advance") as advance:
            with self.assertRaisesRegex(self.p.RPCError, "TLS read failed"):
                wallet.invoke(CONTRACT, 88)
        self.assertEqual(wallet_rpc.call_args_list, [call("get_address"), call("get_nonce")])
        advance.assert_not_called()

    def test_invoke_waits_using_prebuild_nonce_not_a_followup_nonce(self):
        wallet = self.wallet()
        order = Mock()
        with patch.object(wallet, "_wait_nonce_catchup", return_value=8) as sync, \
                patch.object(wallet, "_call", return_value={"hash": TX}) as rpc, \
                patch.object(wallet, "wait_nonce_advance", return_value=9) as advance:
            order.attach_mock(sync, "sync")
            order.attach_mock(rpc, "rpc")
            order.attach_mock(advance, "advance")
            self.assertEqual(wallet.invoke(CONTRACT, 88, [self.p.val_str(NEW_ENDPOINT)]), TX)
        self.assertEqual([c[0] for c in order.mock_calls], ["sync", "rpc", "advance"])
        rpc.assert_called_once()
        self.assertEqual(rpc.call_args.args[0], "build_transaction")
        self.assertEqual(rpc.call_args.args[1]["invoke_contract"]["entry_id"], 88)
        advance.assert_called_once_with(8, timeout=180)

    def test_invoke_keeps_broadcast_hash_if_followup_nonce_read_fails(self):
        wallet = self.wallet()
        with patch.object(wallet, "_wait_nonce_catchup", return_value=8), \
                patch.object(wallet, "_call", side_effect=[
                    {"hash": TX}, self.p.RPCError("get_nonce: transport failed")]) as rpc:
            self.assertEqual(wallet.invoke(CONTRACT, 88), TX)
        self.assertEqual([c.args[0] for c in rpc.call_args_list],
                         ["build_transaction", "get_nonce"])

    def test_invoke_without_broadcast_skips_nonce_advance_wait(self):
        wallet = self.wallet()
        with patch.object(wallet, "_wait_nonce_catchup", return_value=8) as sync, \
                patch.object(wallet, "_call", return_value={"hash": TX}) as rpc, \
                patch.object(wallet, "wait_nonce_advance") as advance:
            self.assertEqual(wallet.invoke(CONTRACT, 88, broadcast=False), TX)
        sync.assert_called_once_with()
        rpc.assert_called_once()
        self.assertIs(rpc.call_args.args[1]["broadcast"], False)
        advance.assert_not_called()

    def test_invoke_build_response_loss_does_not_rebroadcast(self):
        wallet = self.wallet()
        self.set_responses(self.failure("connection"))
        with patch.object(wallet, "_wait_nonce_catchup", return_value=8), \
                patch.object(wallet, "wait_nonce_advance") as advance:
            with self.assertRaisesRegex(self.p.RPCError, "result unknown"):
                wallet.invoke(CONTRACT, 88)
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.kwargs["json"]["method"], "build_transaction")
        advance.assert_not_called()
        self.clock.sleep.assert_not_called()

    def test_daemon_read_key_propagates_transport_failure(self):
        for kind in ("ssl", "connection", "timeout", "429", "503", "bad_json"):
            with self.subTest(failure=kind):
                self.set_responses(*(self.failure(kind) for _ in range(3)))
                with self.assertRaises(self.p.RPCError):
                    self.p.DaemonClient(DAEMON_URL).read_key(CONTRACT, "miner_" + ADDRESS)
                self.assertEqual(self.post.call_count, 3)

    def test_daemon_read_key_returns_none_only_for_real_missing_key_error(self):
        self.set_responses(self.response({"error": {
            "code": -32000, "message": "No data found with requested key"}}))
        self.assertIsNone(self.p.DaemonClient(DAEMON_URL).read_key(CONTRACT, "absent"))
        self.post.assert_called_once()
        self.clock.sleep.assert_not_called()
        self.set_responses(self.response({"error": {
            "code": -32601, "message": "Method not found"}}))
        with self.assertRaisesRegex(self.p.RPCError, "Method not found"):
            self.p.DaemonClient(DAEMON_URL).read_key(CONTRACT, "absent")

    def test_daemon_read_key_parses_existing_storage(self):
        self.set_responses(self.response({"result": {
            "data": self.p.val_str(NEW_ENDPOINT), "topoheight": 123}}))
        self.assertEqual(self.p.DaemonClient(DAEMON_URL).read_key(CONTRACT, "endpoint"),
                         NEW_ENDPOINT)
        params = self.post.call_args.kwargs["json"]["params"]
        self.assertEqual(params, {"contract": CONTRACT, "key": self.p.val_str("endpoint")})

    def test_miner_chunks_keep_heartbeat_21_and_use_new_endpoint_88(self):
        chunks = self.b.CHUNKS["XelisVaultMiner"]
        self.assertEqual(chunks["submit_heartbeat"], 21)
        self.assertEqual(chunks["update_endpoint"], 88)

    def test_each_tree_docs_map_uses_compiled_indexes_21_and_88(self):
        path = self.tree.parent / "docs" / "entry_chunk_ids.json"
        mapping = json.loads(path.read_text(encoding="utf-8"))["XelisVaultMiner"]
        for index, name in ((21, "submit_heartbeat"), (88, "update_endpoint")):
            with self.subTest(entry=name):
                self.assertIn(str(index), mapping)
                self.assertEqual(mapping[str(index)]["name"], name)
                self.assertEqual(mapping[str(index)]["kind"], "Entry")
                self.assertEqual(self.p.entry_id("XelisVaultMiner", name), index)

    def test_endpoint_success_checks_module_then_reads_back_desired_value(self):
        backend = self.backend()
        backend.daemon.read_key.side_effect = [miner_record(OLD_ENDPOINT),
                                              miner_record(OLD_ENDPOINT),
                                              miner_record(NEW_ENDPOINT)]
        order = Mock()
        order.attach_mock(backend.wallet.address, "identity")
        order.attach_mock(backend.daemon.read_key, "storage")
        order.attach_mock(backend.daemon._call, "module")
        order.attach_mock(backend.wallet.invoke, "invoke")
        result = backend.miner_update_endpoint("  " + NEW_ENDPOINT + "  ")
        self.assertIsInstance(result, self.b.OpResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.tx, TX)
        self.assert_endpoint_invoke(backend)
        backend.daemon._call.assert_called_once_with("get_contract_module", {"contract": CONTRACT})
        self.assertEqual(backend.daemon.read_key.call_args_list,
                         [call(CONTRACT, "miner_" + ADDRESS)] * 3)
        self.assertEqual([c[0] for c in order.mock_calls],
                         ["identity", "storage", "module", "invoke", "storage", "storage"])
        self.clock.sleep.assert_called_once_with(2)

    def test_endpoint_identity_mismatch_fails_before_any_chain_write(self):
        backend = self.backend()
        backend.wallet.address.return_value = "xet:another-wallet"
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assertFalse(result.ok)
        self.assertRegex(result.reason.lower(), "address|wallet")
        backend.wallet.invoke.assert_not_called()
        backend.daemon.read_key.assert_not_called()
        backend.daemon._call.assert_not_called()

    def test_endpoint_identity_read_failure_is_fail_closed(self):
        backend = self.backend()
        backend.wallet.address.side_effect = self.p.RPCError("wallet unavailable")
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assertFalse(result.ok)
        backend.wallet.invoke.assert_not_called()
        backend.daemon._call.assert_not_called()

    def test_endpoint_empty_unregistered_and_no_wallet_never_write(self):
        for condition in ("empty", "unregistered", "no_wallet"):
            with self.subTest(condition=condition):
                backend = self.backend()
                wallet = backend.wallet
                if condition == "unregistered":
                    backend.daemon.read_key.return_value = None
                if condition == "no_wallet":
                    backend.wallet = None
                result = backend.miner_update_endpoint("  " if condition == "empty" else NEW_ENDPOINT)
                self.assertFalse(result.ok)
                self.assertTrue(result.reason)
                wallet.invoke.assert_not_called()
                backend.daemon._call.assert_not_called()

    def test_endpoint_noop_checks_identity_but_skips_transaction_and_module(self):
        backend = self.backend()
        backend.daemon.read_key.return_value = miner_record(NEW_ENDPOINT)
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assertTrue(result.ok)
        self.assertFalse(result.tx)
        backend.wallet.address.assert_called_once_with()
        backend.wallet.invoke.assert_not_called()
        backend.daemon._call.assert_not_called()
        self.clock.sleep.assert_not_called()

    def test_capability_probe_reports_deployed_contract_support(self):
        supported = self.backend()
        self.assertIs(supported.miner_supports_update_endpoint(), True)
        supported.daemon._call.assert_called_once_with("get_contract_module",
                                                      {"contract": CONTRACT})

        missing = self.backend()
        metadata = deployed_module()
        metadata["data"]["module"]["chunks"].pop()
        missing.daemon._call.return_value = metadata
        self.assertIs(missing.miner_supports_update_endpoint(), False)

        wrong_shape = self.backend()
        metadata = deployed_module()
        metadata["data"]["module"]["chunks"][88]["value"]["parameters"] = []
        wrong_shape.daemon._call.return_value = metadata
        self.assertIs(wrong_shape.miner_supports_update_endpoint(), False)

        unreachable = self.backend()
        unreachable.daemon._call.side_effect = self.p.RPCError("node down")
        self.assertIsNone(unreachable.miner_supports_update_endpoint())

        malformed = self.backend()
        malformed.daemon._call.return_value = {"data": None}
        self.assertIsNone(malformed.miner_supports_update_endpoint())

    def test_capability_probe_reads_the_module_once_per_contract_hash(self):
        backend = self.backend()
        for _ in range(3):
            self.assertIs(backend.miner_supports_update_endpoint(), True)
        backend.daemon._call.assert_called_once()
        upgraded = "c" * 64
        backend.contracts = {"miner": upgraded, "XelisVaultMiner": upgraded}
        self.assertIs(backend.miner_supports_update_endpoint(), True)
        self.assertEqual(backend.daemon._call.call_args_list,
                         [call("get_contract_module", {"contract": CONTRACT}),
                          call("get_contract_module", {"contract": upgraded})])

    def test_endpoint_old_88_chunk_module_requires_migration_without_write(self):
        backend = self.backend()
        metadata = deployed_module()
        metadata["data"]["module"]["chunks"].pop()
        backend.daemon._call.return_value = metadata
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assertFalse(result.ok)
        self.assertRegex(result.reason.lower(), "deployment|migration|support")
        backend.wallet.invoke.assert_not_called()

    def test_endpoint_missing_module_metadata_fails_closed(self):
        malformed = [None, {}, {"data": None}, {"data": {}},
                     {"data": {"module": None}},
                     {"data": {"module": {"chunks": None}}},
                     {"data": {"module": {"chunks": []}}}]
        for metadata in malformed:
            with self.subTest(metadata=metadata):
                backend = self.backend()
                backend.daemon._call.return_value = metadata
                result = backend.miner_update_endpoint(NEW_ENDPOINT)
                self.assertIsInstance(result, self.b.OpResult)
                self.assertFalse(result.ok)
                backend.wallet.invoke.assert_not_called()

    def test_endpoint_wrong_entry_or_parameter_signature_fails_closed(self):
        bad_chunks = [
            {}, {"type": "all", "value": {"parameters": [{"type": "string"}]}},
            {"type": "entry", "value": {}},
            {"type": "entry", "value": {"parameters": []}},
            {"type": "entry", "value": {"parameters": [{"type": "u64"}]}},
            {"type": "entry", "value": {"parameters": ["string"]}},
            {"type": "entry", "value": {"parameters": [{"type": "string"}] * 2}},
        ]
        for chunk in bad_chunks:
            with self.subTest(chunk=chunk):
                backend = self.backend()
                backend.daemon._call.return_value["data"]["module"]["chunks"][88] = chunk
                result = backend.miner_update_endpoint(NEW_ENDPOINT)
                self.assertFalse(result.ok)
                backend.wallet.invoke.assert_not_called()

    def test_endpoint_non_object_chunk_metadata_fails_closed(self):
        bad_chunks = [None, [], "invalid", {"type": "entry", "value": None},
                      {"type": "entry", "value": []}, {"type": "entry", "value": "invalid"}]
        for chunk in bad_chunks:
            with self.subTest(chunk=chunk):
                backend = self.backend()
                backend.daemon._call.return_value["data"]["module"]["chunks"][88] = chunk
                result = backend.miner_update_endpoint(NEW_ENDPOINT)
                self.assertIsInstance(result, self.b.OpResult)
                self.assertFalse(result.ok)
                backend.wallet.invoke.assert_not_called()

    def test_endpoint_preflight_transport_errors_never_write(self):
        for location in ("read_key", "_call"):
            with self.subTest(location=location):
                backend = self.backend()
                getattr(backend.daemon, location).side_effect = self.p.RPCError("RPC transport failed")
                result = backend.miner_update_endpoint(NEW_ENDPOINT)
                self.assertFalse(result.ok)
                backend.wallet.invoke.assert_not_called()

    def test_endpoint_failed_readback_retains_tx_and_pending_warning(self):
        backend = self.backend()
        backend.daemon.read_key.side_effect = [miner_record(OLD_ENDPOINT),
                                              self.p.RPCError("TLS readback failed")]
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assert_pending(result)
        self.assert_endpoint_invoke(backend)
        self.assertEqual(backend.daemon.read_key.call_count, 2)

    def test_endpoint_stale_or_missing_readback_never_claims_success(self):
        for readback in (miner_record(OLD_ENDPOINT), None):
            with self.subTest(readback=readback):
                backend = self.backend()
                backend.daemon.read_key.side_effect = lambda *args: (
                    miner_record(OLD_ENDPOINT) if backend.daemon.read_key.call_count == 1
                    else readback)
                self.assert_pending(backend.miner_update_endpoint(NEW_ENDPOINT))
                self.assert_endpoint_invoke(backend)
                self.assertGreaterEqual(backend.daemon.read_key.call_count, 2)

    def test_endpoint_failed_broadcast_does_not_poll_readback(self):
        backend = self.backend()
        backend.wallet.invoke.side_effect = self.p.RPCError("result unknown; do not retry")
        result = backend.miner_update_endpoint(NEW_ENDPOINT)
        self.assertFalse(result.ok)
        self.assertIn("result unknown", result.reason)
        self.assert_endpoint_invoke(backend)
        backend.daemon.read_key.assert_called_once_with(CONTRACT, "miner_" + ADDRESS)
        self.clock.sleep.assert_not_called()


class SourceRpcEndpointTests(RpcEndpointCases, unittest.TestCase):
    tree = TREES[0]


class InstalledRpcEndpointTests(RpcEndpointCases, unittest.TestCase):
    tree = TREES[1]


if __name__ == "__main__":
    unittest.main()
