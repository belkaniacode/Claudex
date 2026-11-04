import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("proxyctl", ROOT / "package/contents/code/proxyctl.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class ConfigurationTests(unittest.TestCase):
    def test_missing_configuration_has_actionable_error(self):
        with self.assertRaises(backend.BackendError) as raised:
            backend.load_config(Path("/nonexistent/widget/config.json"))
        self.assertEqual(raised.exception.code, "not_installed")

    def test_valid_and_invalid_configurations(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            for port in (True, "4001", 0, 65536):
                path.write_text(json.dumps({"proxy_dir": "/tmp/proxy", "port": port}))
                with self.assertRaises(backend.BackendError):
                    backend.load_config(path)
            path.write_text(json.dumps({"proxy_dir": "/tmp/space ' % # $ ;", "port": 4001}))
            self.assertEqual(backend.load_config(path)["port"], 4001)
            path.write_text("x" * 8193)
            with self.assertRaises(backend.BackendError):
                backend.load_config(path)

    def test_invalid_action_never_calls_backend(self):
        result = subprocess.run(["/usr/bin/python3", "-I", "-B", str(ROOT / "package/contents/code/proxyctl.py"),
                                 "restart"], capture_output=True)
        self.assertEqual(result.returncode, 2)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.props = {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0"}
        self.config = {"port": 4001}
        self.port = patch.object(backend, "port_occupied", return_value=False).start()
        self.probe = patch.object(backend, "probe_local", return_value=("responsive", 4)).start()
        self.owner = patch.object(backend, "listener_ownership", return_value="unknown").start()
        self.addCleanup(patch.stopall)

    def observe(self, service):
        return backend.observed_state(self.config, {**self.props, "ActiveState": service})

    def test_service_state_mapping(self):
        for service, state in (("inactive", "off"), ("failed", "error"),
                               ("activating", "starting"), ("deactivating", "stopping")):
            self.assertEqual(self.observe(service)["state"], state)
        self.probe.assert_not_called()

    def test_green_requires_managed_listener_and_local_liveness(self):
        self.port.return_value = True
        self.assertEqual(self.observe("active")["state"], "degraded")
        self.owner.return_value = "managed"
        self.assertEqual(self.observe("active")["state"], "running")
        self.probe.return_value = ("unavailable", None)
        self.assertEqual(self.observe("active")["state"], "degraded")

    def test_external_port_cannot_be_started_or_stopped(self):
        self.port.return_value = True
        status = self.observe("inactive")
        self.assertEqual(status["state"], "external")
        self.assertFalse(status["can_start"])
        self.assertFalse(status["can_stop"])

    def test_unknown_port_check_does_not_allow_start(self):
        self.port.return_value = None
        self.assertFalse(self.observe("inactive")["can_start"])

    def test_service_properties_never_request_environment(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return "LoadState=loaded\nActiveState=inactive\n", False
        backend.service_properties(runner)
        self.assertNotIn("Environment", " ".join(calls[0]))

    def test_incomplete_service_output_fails(self):
        with self.assertRaises(backend.BackendError):
            backend.service_properties(lambda *args, **kwargs: ("", False))


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name}).start()
        self.props = patch.object(backend, "service_properties", return_value={
            "LoadState": "loaded", "ActiveState": "inactive"}).start()
        self.port = patch.object(backend, "port_occupied", return_value=False).start()
        self.runner = patch.object(backend, "run_bounded", return_value=("", False)).start()
        self.profile = patch.object(backend, "profile_call").start()
        self.addCleanup(patch.stopall)

    def test_start_uses_fixed_nonblocking_user_unit(self):
        backend.control("start", {"port": 4001})
        self.runner.assert_called_once_with(["/usr/bin/systemctl", "--user", "--no-block", "start", backend.UNIT], limit=8192)

    def test_stop_never_kills_external_process(self):
        self.port.return_value = True
        backend.control("stop", {"port": 4001})
        self.runner.assert_not_called()

    def test_active_start_is_idempotent(self):
        self.props.return_value["ActiveState"] = "active"
        backend.control("start", {"port": 4001})
        self.runner.assert_not_called()
        self.port.assert_not_called()

    def test_port_conflict_prevents_submission(self):
        self.port.return_value = True
        with self.assertRaises(backend.BackendError) as raised:
            backend.control("start", {"port": 4001})
        self.assertEqual(raised.exception.code, "port_conflict")
        self.runner.assert_not_called()

    def test_concurrent_mutation_fails_without_waiting(self):
        with backend.mutation_lock():
            with self.assertRaises(backend.BackendError) as raised:
                backend.control("start", {"port": 4001})
        self.assertEqual(raised.exception.code, "busy")

    def test_timeout_does_not_retry_action(self):
        self.runner.side_effect = backend.BackendError("timeout", "timeout")
        with self.assertRaises(backend.BackendError):
            backend.control("start", {"port": 4001})
        self.assertEqual(self.runner.call_count, 1)


class ProfileLifecycleTests(unittest.TestCase):
    def test_ready_service_activates_profile(self):
        from contextlib import nullcontext
        with patch.object(backend, "load_config", return_value={"port": 4001}), \
                patch.object(backend, "service_properties", return_value={"ActiveState": "activating", "ControlGroup": "/test"}), \
                patch.object(backend, "probe_local", return_value=("responsive", 1)), \
                patch.object(backend, "listener_ownership", return_value="managed"), \
                patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                patch.object(backend, "profile_call") as profile:
            backend.service_profile("profile-on")
            profile.assert_called_once_with("activate", 4001)

    def test_failed_service_does_not_activate(self):
        with patch.object(backend, "load_config", return_value={"port": 4001}), \
                patch.object(backend, "service_properties", return_value={"ActiveState": "failed"}), \
                patch.object(backend, "profile_call") as profile:
            with self.assertRaises(backend.BackendError):
                backend.service_profile("profile-on")
            profile.assert_not_called()

    def test_stop_hook_restores_without_loading_config(self):
        from contextlib import nullcontext
        with patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                patch.object(backend, "load_config") as config, \
                patch.object(backend, "profile_call") as profile:
            backend.service_profile("profile-off")
            profile.assert_called_once_with("restore")
            config.assert_not_called()

    def test_gateway_helper_disabled_fails_without_output(self):
        import io
        from contextlib import nullcontext, redirect_stdout
        output = io.StringIO()
        with patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                patch.object(backend, "profile_call", return_value="original"), redirect_stdout(output):
            with self.assertRaises(backend.BackendError):
                backend.gateway_key()
        self.assertEqual(output.getvalue(), "")

    def test_gateway_helper_emits_only_fake_key_when_ready(self):
        import io
        from contextlib import nullcontext, redirect_stdout
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".litellm").mkdir()
            (home / ".litellm/master-key.txt").write_text("test-only-key")
            output = io.StringIO()
            with patch.object(backend.Path, "home", return_value=home), \
                    patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                    patch.object(backend, "profile_call", return_value="gpt"), \
                    patch.object(backend, "load_config", return_value={"port": 4001}), \
                    patch.object(backend, "observed_state", return_value={"state": "running"}), redirect_stdout(output):
                backend.gateway_key()
            self.assertEqual(output.getvalue(), "test-only-key\n")

    def test_gateway_helper_accepts_model_picker_change_with_real_profile(self):
        import io
        from contextlib import nullcontext, redirect_stdout
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home / ".config")}), \
                    patch.object(backend.Path, "home", return_value=home):
                manager = backend.profile_manager()
                manager.key.parent.mkdir()
                manager.key.write_text("test-only-key")
                manager.activate(4001)
                settings, _ = manager.settings()
                settings["model"] = "fable"
                manager.target.write_text(json.dumps(settings))
                output = io.StringIO()
                with patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                        patch.object(backend, "load_config", return_value={"port": 4001}), \
                        patch.object(backend, "observed_state", return_value={"state": "running"}), \
                        redirect_stdout(output):
                    backend.gateway_key()
                self.assertEqual(output.getvalue(), "test-only-key\n")
                manager.restore()
                self.assertFalse(manager.target.exists())

    def test_gateway_failure_reports_reason_without_stdout(self):
        import io
        from contextlib import redirect_stdout
        error = backend.BackendError("proxy_not_ready", "Managed proxy is not ready.")
        output = io.StringIO()
        with patch.object(backend, "gateway_key", side_effect=error), \
                self.assertLogs(backend.LOG, level="WARNING") as logs, redirect_stdout(output):
            self.assertEqual(backend.main(["gateway-key"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(any("Managed proxy is not ready." in line for line in logs.output))

    def test_gateway_conflict_and_unready_proxy_fail_before_reading_key(self):
        import io
        from contextlib import nullcontext, redirect_stdout
        for profile_status, state, code in (("conflict", "running", "profile_conflict"),
                                             ("gpt", "degraded", "proxy_not_ready")):
            with self.subTest(profile=profile_status, state=state):
                output = io.StringIO()
                with patch.object(backend, "mutation_lock", side_effect=nullcontext), \
                        patch.object(backend, "profile_call", return_value=profile_status), \
                        patch.object(backend, "load_config", return_value={"port": 4001}), \
                        patch.object(backend, "observed_state", return_value={"state": state}), \
                        patch.object(backend.os, "open") as open_key, redirect_stdout(output):
                    with self.assertRaises(backend.BackendError) as raised:
                        backend.gateway_key()
                self.assertEqual(raised.exception.code, code)
                open_key.assert_not_called()
                self.assertEqual(output.getvalue(), "")


class BoundaryTests(unittest.TestCase):
    def test_subprocess_output_is_bounded(self):
        output, truncated = backend.run_bounded(["/usr/bin/python3", "-I", "-B", "-c", "print('x'*100000)"], limit=1024)
        self.assertLessEqual(len(output), 1024)
        self.assertTrue(truncated)

    def test_subprocess_timeout(self):
        with self.assertRaises(backend.BackendError) as raised:
            backend.run_bounded(["/usr/bin/python3", "-I", "-B", "-c", "import time; time.sleep(2)"], timeout=0.05)
        self.assertEqual(raised.exception.code, "timeout")

    def test_unreapable_process_cleanup_never_uses_unbounded_wait(self):
        from unittest.mock import Mock
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("child", 0.1)
        backend.cleanup_process(process)
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=0.1)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_nonzero_command_is_not_success(self):
        with self.assertRaises(backend.BackendError):
            backend.run_bounded(["/usr/bin/false"])

    def test_redacts_secrets_and_ansi(self):
        result = backend.sanitize_logs("\x1b[31mINFO ready\x1b[0m\nAuthorization: secret\nrefresh_token=secret\nsk-abcdefghijk\n\x00")
        self.assertIn("INFO ready", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("sk-", result)
        self.assertNotIn("\x1b", result)
        self.assertNotIn("\x00", result)

    def test_journal_is_unit_filtered_and_current_invocation_scoped(self):
        with patch.object(backend, "run_bounded", return_value=("ready", False)) as run:
            logs = backend.recent_logs({"ActiveState": "active", "InvocationID": "a" * 32})
        args = run.call_args.args[0]
        self.assertIn("--unit=" + backend.UNIT, args)
        self.assertIn("_SYSTEMD_INVOCATION_ID=" + "a" * 32, args)
        self.assertNotIn("--follow", args)
        self.assertEqual(logs["scope"], "current")

    def test_prior_run_logs_are_labeled(self):
        with patch.object(backend, "run_bounded", return_value=("", False)):
            self.assertEqual(backend.recent_logs({"ActiveState": "inactive"})["scope"], "previous")

    def test_liveness_probe_does_not_follow_redirects(self):
        with patch.object(backend.http.client, "HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 302
            response.read.return_value = b'"I\'m alive!"'
            self.assertEqual(backend.probe_local(4001)[0], "unexpected")
            connection.assert_called_once_with("127.0.0.1", 4001, timeout=1)
            self.assertEqual(connection.return_value.request.call_args.args[:2], ("GET", "/health/liveliness"))

    def test_procfs_ownership_accepts_descendant_cgroup(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            (proc / "net").mkdir()
            (proc / "net/tcp").write_text("header\n0: 0100007F:0FA1 00000000:0000 0A 0 0 0 0 0 123\n")
            process = proc / "42"
            (process / "fd").mkdir(parents=True)
            (process / "cgroup").write_text("0::/user/proxy/worker\n")
            (process / "fd/1").symlink_to("socket:[123]")
            self.assertEqual(backend.listener_ownership(4001, "/user/proxy", proc), "managed")
            self.assertEqual(backend.listener_ownership(4001, "/other", proc), "external")


if __name__ == "__main__":
    unittest.main()
