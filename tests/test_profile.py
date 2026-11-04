import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gptc_profile", ROOT / "package/contents/code/profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.manager = profile.Profile(self.home / "state", self.home)
        self.manager.key.parent.mkdir()
        self.manager.key.write_text("fake-test-gateway-token")

    def write_settings(self, settings):
        self.manager.target.parent.mkdir(exist_ok=True)
        self.manager.target.write_text(json.dumps(settings))

    def settings(self):
        return json.loads(self.manager.target.read_text())

    def test_activation_and_restore_preserve_unrelated_edits(self):
        original = {"env": {"OTHER": "keep", "ANTHROPIC_MODEL": "original"}, "model": "opus", "hooks": {}}
        self.write_settings(original)
        self.manager.activate(4999)
        self.assertEqual(self.manager.status(), "gpt")
        settings = self.settings()
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:4999")
        settings["language"] = "russian"
        settings["env"]["OTHER"] = "edited"
        self.write_settings(settings)
        self.manager.restore()
        expected = {**original, "language": "russian"}
        expected["env"]["OTHER"] = "edited"
        self.assertEqual(self.settings(), expected)
        self.assertEqual(self.manager.status(), "original")
        self.assertEqual(len(list(self.manager.directory.glob("*.json"))), 1)
        self.manager.restore()

    def test_absent_file_restored_as_absent(self):
        self.manager.activate(4001)
        self.manager.restore()
        self.assertFalse(self.manager.target.exists())
        snapshot = json.loads(next(self.manager.directory.glob("*.json")).read_text())
        self.assertFalse(snapshot["existed"])

    def test_backups_and_settings_are_private(self):
        self.manager.activate(4001)
        self.assertEqual(self.manager.directory.stat().st_mode & 0o777, 0o700)
        for path in [self.manager.target, *self.manager.directory.iterdir()]:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("fake-test-gateway-token", self.manager.journal.read_text())

    def test_conflict_keeps_journal_and_changes_nothing(self):
        self.manager.activate(4001)
        settings = self.settings()
        settings["env"]["ANTHROPIC_BASE_URL"] = "https://example.invalid"
        self.write_settings(settings)
        self.assertEqual(self.manager.status(), "conflict")
        with self.assertRaises(profile.ProfileError):
            self.manager.restore()
        self.assertEqual(self.settings(), settings)
        self.assertTrue(self.manager.journal.exists())

    def test_model_picker_keeps_profile_enabled_and_restores_original_model(self):
        original = {"model": "opus", "language": "russian"}
        for model in ("gpt-6-astra", "gpt-6-luna", "sonnet", "opus", "haiku", "fable"):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as temp:
                manager = profile.Profile(Path(temp) / "state", Path(temp))
                manager.target.parent.mkdir()
                manager.target.write_text(json.dumps(original))
                manager.activate(4001)
                settings, _ = manager.settings()
                settings["model"] = model
                manager.target.write_text(json.dumps(settings))
                self.assertEqual(manager.status(), "gpt")
                manager.restore()
                self.assertEqual(manager.settings()[0], original)

    def test_unrecognized_model_edit_keeps_recovery_conflict(self):
        self.manager.activate(4001)
        settings = self.settings()
        settings["model"] = "custom-provider-model"
        self.write_settings(settings)
        self.assertEqual(self.manager.status(), "conflict")
        with self.assertRaises(profile.ProfileError):
            self.manager.restore()
        self.assertEqual(self.settings(), settings)
        self.assertTrue(self.manager.journal.exists())

    def test_model_picker_does_not_mask_routing_or_auth_edits(self):
        for scope, key in (("env", "ANTHROPIC_BASE_URL"), ("env", "ANTHROPIC_API_KEY"),
                           ("env", "ANTHROPIC_DEFAULT_OPUS_MODEL"), ("root", "apiKeyHelper")):
            with self.subTest(scope=scope, key=key), tempfile.TemporaryDirectory() as temp:
                manager = profile.Profile(Path(temp) / "state", Path(temp))
                manager.activate(4001)
                settings, _ = manager.settings()
                settings["model"] = "gpt-6-astra"
                container = settings["env"] if scope == "env" else settings
                container[key] = "edited"
                manager.target.write_text(json.dumps(settings))
                self.assertEqual(manager.status(), "conflict")
                with self.assertRaises(profile.ProfileError):
                    manager.restore()

    def test_failed_settings_write_is_recoverable(self):
        self.write_settings({"model": "opus"})
        real_atomic = profile.atomic
        def failing(path, raw, expected):
            if path == self.manager.target:
                raise OSError("fake write failure")
            real_atomic(path, raw, expected)
        with patch.object(profile, "atomic", side_effect=failing):
            with self.assertRaises(OSError):
                self.manager.activate(4001)
        self.assertEqual(self.settings(), {"model": "opus"})
        self.manager.restore()
        self.assertFalse(self.manager.journal.exists())
        self.assertEqual(self.settings(), {"model": "opus"})

    def test_repeated_activation_refused(self):
        self.manager.activate(4001)
        with self.assertRaises(profile.ProfileError):
            self.manager.activate(4001)
        self.assertEqual(len(list(self.manager.directory.glob("*.json"))), 2)

    def test_symlink_and_invalid_json_refused(self):
        self.manager.target.parent.mkdir()
        self.manager.target.symlink_to(self.home / "other")
        with self.assertRaises(profile.ProfileError):
            self.manager.activate(4001)
        self.manager.target.unlink()
        self.manager.target.write_text("not json")
        with self.assertRaises(profile.ProfileError):
            self.manager.activate(4001)

    def test_activation_never_reads_gateway_key(self):
        self.manager.key.unlink()
        self.manager.activate(4001)
        self.assertIn("gateway-key", self.settings()["apiKeyHelper"])
        self.assertEqual(self.settings()["env"]["ANTHROPIC_AUTH_TOKEN"], "")
        self.assertNotIn("fake-test-gateway-token", self.manager.target.read_text())

    def test_status_does_not_write(self):
        self.assertEqual(self.manager.status(), "original")
        self.assertFalse(self.manager.directory.exists())

    def test_concurrent_edit_detected(self):
        self.write_settings({"env": {}})
        old = self.manager.target.read_bytes()
        self.write_settings({"new": True})
        with self.assertRaises(profile.ProfileError):
            profile.atomic(self.manager.target, b"{}", old)
        self.assertEqual(self.settings(), {"new": True})


if __name__ == "__main__":
    unittest.main()
