import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config"),
                                          "XDG_DATA_HOME": str(self.root / "data")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_dry_run_does_not_write_or_call_system_commands(self):
        with patch.object(installer, "validate"), patch.object(installer, "run") as run:
            installer.install(Path("/tmp/proxy"), 4001, dry_run=True)
        self.assertEqual(list(self.root.iterdir()), [])
        run.assert_not_called()

    def test_refuses_unrelated_files(self):
        target = installer.paths()["unit"]
        target.parent.mkdir(parents=True)
        target.write_text("unrelated")
        with self.assertRaises(ValueError):
            installer.check_owned(installer.paths())
        self.assertEqual(target.read_text(), "unrelated")

    def test_refuses_symlink_parent(self):
        (self.root / "real").mkdir()
        (self.root / "config").symlink_to(self.root / "real", target_is_directory=True)
        with self.assertRaises(ValueError):
            installer.check_owned(installer.paths())

    def test_unit_contains_no_enable_restart_or_shell(self):
        unit = installer.render_unit(Path("/tmp/proxy"), 4001).decode()
        self.assertNotIn("[Install]", unit)
        self.assertNotIn("/bin/sh", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("KillMode=control-group", unit)
        self.assertIn("Environment=PROXY_PORT=4001", unit)
        self.assertNotIn("MASTER_KEY", unit)

    def test_profile_hooks_and_recovery_guard(self):
        unit = installer.render_unit(Path("/tmp/proxy"), 4001).decode()
        self.assertIn("ExecStartPost=/usr/bin/python3 -I -B", unit)
        self.assertIn("profile-on", unit)
        self.assertIn("ExecStopPost=/usr/bin/python3 -I -B", unit)
        self.assertIn("profile-off", unit)
        installer.require_profile_restored()
        journal = installer.paths()["config"].parent / "profile-backups/active.json"
        journal.parent.mkdir(parents=True)
        journal.write_text("{}")
        with self.assertRaises(ValueError):
            installer.require_profile_restored()

    def test_path_escaping(self):
        directory = Path('/tmp/space "quote" % $ ;')
        unit = installer.render_unit(directory, 4001).decode()
        self.assertIn("%%", unit)
        self.assertIn("$$", unit)
        self.assertIn('WorkingDirectory=/tmp/space "quote" %% $ ;', unit)
        self.assertIn(r'\"quote\"', unit)
        for invalid in ("/tmp/a\nb", "/tmp/a\0b"):
            with self.assertRaises(ValueError):
                installer.quote_unit(invalid)

    def test_active_service_blocks_update(self):
        for state in ("active", "activating", "deactivating", "reloading"):
            with patch.object(installer, "run", return_value=state):
                with self.assertRaises(ValueError):
                    installer.inactive()

    def test_modified_owned_file_is_not_overwritten(self):
        targets = installer.paths()
        for key in ("unit", "config"):
            targets[key].parent.mkdir(parents=True, exist_ok=True)
            targets[key].write_bytes(b"owned")
        targets["package"].mkdir(parents=True)
        (targets["package"] / "metadata.json").write_text("{}")
        record = {"owner": installer.APP_ID, "version": 1, "hashes": {
            "unit": installer.digest(b"owned"), "config": installer.digest(b"owned"),
            "package": installer.package_hash(targets["package"])}}
        targets["manifest"].write_text(json.dumps(record))
        self.assertIsNotNone(installer.check_owned(targets))
        targets["unit"].write_text("user modification")
        with self.assertRaises(ValueError):
            installer.check_owned(targets)

    def create_owned_installation(self):
        targets = installer.paths()
        for key in ("unit", "config"):
            targets[key].parent.mkdir(parents=True, exist_ok=True)
            targets[key].write_bytes(b"owned")
        targets["package"].mkdir(parents=True)
        (targets["package"] / "metadata.json").write_text("{}")
        record = {"owner": installer.APP_ID, "version": 1, "hashes": {
            "unit": installer.digest(b"owned"), "config": installer.digest(b"owned"),
            "package": installer.package_hash(targets["package"])}}
        targets["manifest"].write_text(json.dumps(record))
        return targets

    def test_lifecycle_lock_blocks_parallel_installer(self):
        runtime = self.root / "runtime"
        runtime.mkdir(mode=0o700)
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
            with installer.lifecycle_lock():
                with self.assertRaises(RuntimeError):
                    with installer.lifecycle_lock():
                        self.fail("Concurrent lifecycle lock acquired")

    def test_uninstall_reload_failure_restores_retryable_installation(self):
        import shutil
        spec = importlib.util.spec_from_file_location("uninstaller", ROOT / "scripts/uninstall.py")
        uninstaller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(uninstaller)
        targets = self.create_owned_installation()
        def run(argv):
            if "--remove" in argv:
                shutil.rmtree(targets["package"])
                return ""
            raise RuntimeError("user bus unavailable")
        with patch.object(installer, "inactive"), patch.object(installer, "run", side_effect=run):
            with self.assertRaises(RuntimeError):
                uninstaller.remove_locked(installer)
        self.assertIsNotNone(installer.check_owned(targets))

    def test_failed_package_install_preserves_existing_artifacts(self):
        targets = self.create_owned_installation()
        before = {key: targets[key].read_bytes() for key in ("unit", "config", "manifest")}
        def run(argv):
            if "--upgrade" in argv:
                raise RuntimeError("package install failed")
            return ""
        with patch.object(installer, "validate"), patch.object(installer, "inactive"), patch.object(installer, "run", side_effect=run):
            with self.assertRaises(RuntimeError):
                installer.install_locked(Path("/tmp/proxy"), 4001)
        for key, expected in before.items():
            self.assertEqual(targets[key].read_bytes(), expected)
        self.assertIsNotNone(installer.check_owned(targets))

    def test_working_directory_preserves_literal_path(self):
        directory = Path('/tmp/space "quote" back\\\\slash % dollar$')
        line = installer.render_unit(directory, 4001).decode().splitlines()[6]
        self.assertEqual(line, "WorkingDirectory=" + str(directory).replace("%", "%%"))

    def test_picker_icon_uses_registered_theme_name(self):
        package = self.root / "staging"
        package.mkdir()
        (package / "metadata.json").write_bytes((ROOT / "package/metadata.json").read_bytes())
        destination = self.root / "data with spaces/plasma/plasmoids" / installer.APP_ID
        installer.prepare_metadata(package, destination)
        metadata = json.loads((package / "metadata.json").read_text())["KPlugin"]
        self.assertEqual(metadata["Name"], "Claudex")
        self.assertEqual(metadata["Name[ru]"], "Claudex")
        self.assertEqual(metadata["Icon"], installer.APP_ID)
        self.assertEqual(installer.paths()["icon"], self.root / "data/icons/hicolor/scalable/apps" / (installer.APP_ID + ".svg"))
        self.assertTrue((ROOT / "package/contents/icons/gptc.svg").is_file())

    def test_legacy_install_accepts_missing_theme_icon(self):
        targets = self.create_owned_installation()
        self.assertIsNotNone(installer.check_owned(targets))
        self.assertFalse(targets["icon"].exists())

    def test_unowned_theme_icon_is_not_overwritten(self):
        targets = self.create_owned_installation()
        targets["icon"].parent.mkdir(parents=True)
        targets["icon"].write_text("unrelated icon")
        with self.assertRaises(ValueError):
            installer.check_owned(targets)
        self.assertEqual(targets["icon"].read_text(), "unrelated icon")

    def test_successful_install_notifies_running_icon_loaders(self):
        import shutil
        targets = installer.paths()
        calls = []
        def run(argv):
            calls.append(argv)
            if "--install" in argv:
                shutil.copytree(Path(argv[-1]), targets["package"])
            return ""
        with patch.object(installer, "validate"), patch.object(installer, "inactive"), patch.object(installer, "run", side_effect=run):
            installer.install_locked(Path("/tmp/proxy"), 4001)
        signal = ["/usr/bin/gdbus", "emit", "--session", "--object-path", "/KIconLoader",
                  "--signal", "org.kde.KIconLoader.iconChanged", "0"]
        self.assertIn(signal, calls)
        self.assertTrue(targets["manifest"].exists())
        self.assertGreater(calls.index(signal), next(i for i, call in enumerate(calls) if "--install" in call))

    def test_icon_refresh_failure_is_nonfatal(self):
        with patch.object(installer, "run", side_effect=RuntimeError("bus unavailable")):
            with self.assertLogs(installer.LOG, level="WARNING") as logs:
                self.assertFalse(installer.refresh_icon_cache())
        self.assertIn("[FIX:icon-cache]", logs.output[0])

    def test_atomic_write_is_private(self):
        path = self.root / "test/config.json"
        installer.atomic_write(path, b"{}")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
