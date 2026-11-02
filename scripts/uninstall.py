#!/usr/bin/python3
"""Remove verified widget-owned files only, after an explicit service stop."""

import argparse
import importlib.util
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile


def remove_locked(installer, dry_run=False):
    targets = installer.paths()
    if installer.check_owned(targets) is None:
        logging.info("No owned installation found")
        return
    for path in targets.values():
        logging.info("%s %s", "would remove" if dry_run else "remove", path)
    if dry_run:
        return
    installer.inactive()
    installer.require_profile_restored()
    with tempfile.TemporaryDirectory(prefix="proxy-widget-remove-") as temp:
        backup_package = Path(temp) / "package"
        shutil.copytree(targets["package"], backup_package)
        backups = {key: targets[key].read_bytes() for key in ("unit", "config", "manifest", "icon")
                   if targets[key].exists()}
        try:
            installer.run(["/usr/bin/kpackagetool6", "--type", "Plasma/Applet", "--remove", installer.APP_ID])
            for key in ("unit", "config", "icon"):
                if key in backups:
                    targets[key].unlink()
            installer.run(["/usr/bin/systemctl", "--user", "daemon-reload"])
            targets["manifest"].unlink()
        except Exception:
            logging.error("Removal failed; restoring owned installation for retry")
            for key, data in backups.items():
                installer.atomic_write(targets[key], data)
            installer.safe_target(targets["package"])
            if targets["package"].exists():
                shutil.rmtree(targets["package"])
            shutil.copytree(backup_package, targets["package"])
            try:
                installer.run(["/usr/bin/systemctl", "--user", "daemon-reload"])
            except Exception:
                logging.error("Rollback reload failed; retry removal after restoring the user session bus")
            raise
    logging.info("Removed widget artifacts; upstream checkout and credentials are untouched")


def main(argv=None):
    logging.basicConfig(level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
                        format="%(levelname)s [proxy-uninstall] %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location("widget_install", Path(__file__).with_name("install.py"))
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    try:
        if args.dry_run:
            remove_locked(installer, True)
        else:
            with installer.lifecycle_lock():
                remove_locked(installer)
        return 0
    except Exception as error:
        logging.error("Removal stopped: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
