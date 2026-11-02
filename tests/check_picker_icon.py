"""Exercise Plasma's real widget picker against a staged package, without installing it."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

with tempfile.TemporaryDirectory(prefix="gptc-picker-") as temp:
    data = Path(temp) / "data"
    package = data / "plasma/plasmoids" / installer.APP_ID
    shutil.copytree(ROOT / "package", package)
    installer.prepare_metadata(package, package)
    icon = data / "icons/hicolor/scalable/apps" / (installer.APP_ID + ".svg")
    icon.parent.mkdir(parents=True)
    shutil.copyfile(package / "contents/icons/gptc.svg", icon)
    env = {**os.environ, "XDG_DATA_HOME": str(data), "XDG_CONFIG_HOME": str(Path(temp) / "config"),
           "QT_QPA_PLATFORM": "offscreen", "QML_DISABLE_DISK_CACHE": "1"}
    result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-input",
                             str(ROOT / "tests/picker/tst_PickerIcon.qml")], env=env, timeout=30)
    raise SystemExit(result.returncode)
