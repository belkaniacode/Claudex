#!/usr/bin/python3
"""Install only user-owned widget artifacts; never start or enable the proxy."""

import argparse
import hashlib
import importlib.util
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

APP_ID = "org.kde.plasma.cloudegptproxy"
UNIT = "cloudegpt-proxy.service"
ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("proxy-install")


def paths():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not config.is_absolute() or not data.is_absolute():
        raise ValueError("XDG paths must be absolute")
    return {"config": config / "cloudegpt-proxy-widget/config.json",
            "manifest": config / "cloudegpt-proxy-widget/install.json",
            "unit": config / "systemd/user" / UNIT,
            "icon": data / "icons/hicolor/scalable/apps" / (APP_ID + ".svg"),
            "package": data / "plasma/plasmoids" / APP_ID}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package_hash(path):
    result = hashlib.sha256()
    for entry in sorted(path.rglob("*")):
        if entry.is_symlink():
            raise ValueError("Refusing symlink in installed package")
        if entry.is_file():
            result.update(str(entry.relative_to(path)).encode())
            result.update(entry.read_bytes())
    return result.hexdigest()


def safe_target(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Refusing symlink installation destination: " + str(part))


def check_owned(targets):
    for path in targets.values():
        safe_target(path)
    manifest = targets["manifest"]
    if not manifest.exists():
        if any(p.exists() for key, p in targets.items() if key != "manifest"):
            raise ValueError("Existing files are not owned by this installer; refusing overwrite")
        return None
    record = json.loads(manifest.read_text())
    if record.get("owner") != APP_ID or record.get("version") != 1:
        raise ValueError("Unrecognized installation manifest")
    for key in ("unit", "config", "package", "icon"):
        path = targets[key]
        expected = record.get("hashes", {}).get(key)
        if key == "icon" and expected is None and not path.exists():
            continue  # Older installations did not register a theme icon.
        if not path.exists() or not expected:
            raise ValueError("Installation is incomplete; inspect before reinstalling")
        actual = package_hash(path) if key == "package" else digest(path.read_bytes())
        if actual != expected:
            raise ValueError("Locally changed installed artifact; refusing overwrite: " + str(path))
    return record


def run(argv):
    LOG.debug("command.enter tool=%s", Path(argv[0]).name)
    result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
    if result.returncode:
        # Tool output can include configuration; do not echo it automatically.
        raise RuntimeError("Command failed: " + Path(argv[0]).name + " (exit " + str(result.returncode) + ")")
    LOG.debug("command.exit tool=%s", Path(argv[0]).name)
    return result.stdout.decode("utf-8", "replace")


def refresh_icon_cache():
    LOG.debug("[FIX:icon-cache] notifying KDE desktop icon loaders")
    try:
        run(["/usr/bin/gdbus", "emit", "--session", "--object-path", "/KIconLoader",
             "--signal", "org.kde.KIconLoader.iconChanged", "0"])
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        LOG.warning("[FIX:icon-cache] notification failed; icon may remain cached until the next desktop login")
        return False
    LOG.info("[FIX:icon-cache] refresh notification sent; reopen Add Widgets")
    return True


def inactive():
    output = run(["/usr/bin/systemctl", "--user", "show", UNIT,
                  "--property=ActiveState", "--value"])
    if output.strip() not in ("inactive", "failed", ""):
        raise ValueError("Stop the managed service explicitly before installing or removing it")


def quote_unit(value, command=False):
    if any(ord(char) < 32 for char in value):
        raise ValueError("Control characters are not allowed in paths")
    if not command:
        # WorkingDirectory is a path directive, not an ExecStart argument list.
        return value.replace("%", "%%")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return '"' + value + '"'


def render_unit(directory, port):
    template = (ROOT / "systemd/cloudegpt-proxy.service.in").read_text()
    return template.replace("@WORKING_DIRECTORY@", quote_unit(str(directory))).replace(
        "@EXEC_START@", "/usr/bin/bash " + quote_unit(str(directory / "scripts/litellm-proxy.sh"), True)
    ).replace("@PORT@", str(port)).replace(
        "@HELPER@", quote_unit(str(paths()["package"] / "contents/code/proxyctl.py"), True)).encode()


def prepare_metadata(package, destination):
    # WidgetExplorer uses QIcon.fromTheme: a bundled file path is not a theme name.
    path = package / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["KPlugin"]["Icon"] = APP_ID
    LOG.debug("[FIX:picker-icon] metadata uses theme name=%s", APP_ID)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".proxy-widget-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate(directory, port):
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    quote_unit(str(directory))
    for name in ("scripts/litellm-proxy.sh", ".venv/bin/litellm"):
        if not os.access(directory / name, os.X_OK):
            raise ValueError("Missing executable in proxy checkout: " + name)
    for tool in ("/usr/bin/python3", "/usr/bin/bash", "/usr/bin/systemctl", "/usr/bin/journalctl",
                 "/usr/bin/systemd-analyze", "/usr/bin/kpackagetool6", "/usr/bin/msgfmt"):
        if not os.access(tool, os.X_OK):
            raise ValueError("Required dependency is missing: " + tool)
    if not Path("/usr/lib/qt6/plugins/plasma5support/dataengine/plasma_engine_executable.so").exists():
        raise ValueError("Install plasma5support before installing this widget")


@contextmanager
def lifecycle_lock():
    spec = importlib.util.spec_from_file_location("widget_backend_lock", ROOT / "package/contents/code/proxyctl.py")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    try:
        with backend.mutation_lock():
            yield
    except backend.BackendError as error:
        raise RuntimeError(str(error)) from error


def require_profile_restored():
    journal = paths()["config"].parent / "profile-backups/active.json"
    safe_target(journal)
    if journal.exists():
        raise ValueError("Switch Claudex off and restore its Claude profile before updating/removing. Keep profile-backups for recovery.")


def install(directory, port, dry_run=False):
    if dry_run:
        return install_locked(directory, port, True)
    with lifecycle_lock():
        return install_locked(directory, port)


def install_locked(directory, port, dry_run=False):
    targets = paths()
    validate(directory, port)
    previous = check_owned(targets)
    unit = render_unit(directory, port)
    config = (json.dumps({"proxy_dir": str(directory), "port": port}, indent=2) + "\n").encode()
    for key, path in targets.items():
        LOG.info("%s %s", "check" if dry_run else "install", path)
    if dry_run:
        LOG.info("Dry run complete; no files or services changed")
        return
    inactive()
    require_profile_restored()
    with tempfile.TemporaryDirectory(prefix="proxy-widget-install-") as temp:
        staged = Path(temp)
        staged_unit = staged / UNIT
        staged_unit.write_bytes(unit)
        run(["/usr/bin/systemd-analyze", "--user", "verify", str(staged_unit)])
        staged_package = staged / "package"
        shutil.copytree(ROOT / "package", staged_package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        prepare_metadata(staged_package, targets["package"])
        catalog = staged_package / ("contents/locale/ru/LC_MESSAGES/plasma_applet_" + APP_ID + ".mo")
        catalog.parent.mkdir(parents=True, exist_ok=True)
        run(["/usr/bin/msgfmt", "--check", "-o", str(catalog), str(ROOT / "po/ru.po")])
        backups = {key: targets[key].read_bytes() if targets[key].exists() else None
                   for key in ("unit", "config", "manifest", "icon")}
        backup_package = staged / "old-package"
        if previous:
            shutil.copytree(targets["package"], backup_package)
        changed = set()
        package_attempted = False
        try:
            icon_data = (staged_package / "contents/icons/gptc.svg").read_bytes()
            atomic_write(targets["icon"], icon_data)
            changed.add("icon")
            os.chmod(targets["icon"], 0o644)
            LOG.info("[FIX:picker-icon] registered theme icon=%s", APP_ID)
            package_attempted = True
            run(["/usr/bin/kpackagetool6", "--type", "Plasma/Applet",
                 "--upgrade" if previous else "--install", str(staged_package)])
            atomic_write(targets["unit"], unit)
            changed.add("unit")
            atomic_write(targets["config"], config)
            changed.add("config")
            run(["/usr/bin/systemctl", "--user", "daemon-reload"])
            record = {"owner": APP_ID, "version": 1, "hashes": {
                "unit": digest(unit), "config": digest(config), "icon": digest(icon_data),
                "package": package_hash(targets["package"])}}
            atomic_write(targets["manifest"], json.dumps(record, indent=2).encode() + b"\n")
        except Exception:
            LOG.error("Installation failed; restoring previous owned artifacts")
            for key in changed:
                data = backups[key]
                if data is None:
                    targets[key].unlink(missing_ok=True)
                else:
                    atomic_write(targets[key], data)
            if package_attempted:
                safe_target(targets["package"])
                if targets["package"].is_dir():
                    shutil.rmtree(targets["package"])
                if previous:
                    shutil.copytree(backup_package, targets["package"])
            try:
                run(["/usr/bin/systemctl", "--user", "daemon-reload"])
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                LOG.error("Rollback daemon-reload failed; run it manually")
            raise
    refresh_icon_cache()
    LOG.info("Installed. Add Claudex to your panel. Proxy remains stopped.")


def main(argv=None):
    logging.basicConfig(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
                        format="%(levelname)s [proxy-install] %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-dir", type=Path, default=Path.home() / "claude-code-chatgpt-proxy")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        install(args.proxy_dir.expanduser().resolve(), args.port, args.dry_run)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        LOG.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
