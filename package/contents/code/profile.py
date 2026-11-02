"""Private, recoverable Claude user-settings overlay. Never log settings values."""

import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid

LOG = logging.getLogger("proxy-widget")
MODELS = {
    "ANTHROPIC_MODEL": "gpt-6.1-sol",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "gpt-6.1-sol",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "gpt-6-luna",
    "ANTHROPIC_SMALL_FAST_MODEL": "gpt-6-luna",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "gpt-6-astra",
    "ANTHROPIC_DEFAULT_FABLE_MODEL": "gpt-6-astra",
    "CLAUDE_CODE_SUBAGENT_MODEL": "gpt-6.1-sol",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "272000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "OPENAI_API_KEY": "",
}
# Claude's model picker persists root.model while the temporary profile is active.
# These aliases still resolve through the unchanged GPT mappings above.
SELECTABLE_MODELS = {value for key, value in MODELS.items() if key.endswith("_MODEL")} | {
    "sonnet", "opus", "haiku",
}


class ProfileError(Exception):
    pass


def safe_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ProfileError("Refusing symlink in profile paths.")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ProfileError("Profile file must be a user-owned regular file.")


def read_bytes(path):
    safe_path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            raise ProfileError("Profile file exceeds size limit.")
        return raw
    except FileNotFoundError:
        return None


def decode(raw):
    try:
        value = json.loads(raw) if raw is not None else {}
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError) as error:
        raise ProfileError("Invalid profile JSON; no settings changed.") from error


def atomic(path, raw, expected):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".gptc-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if read_bytes(path) != expected:
            raise ProfileError("Settings changed concurrently; retry after checking settings.")
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()


def fingerprint(present, value):
    return hashlib.sha256(encoded([present, value])).hexdigest()


class Profile:
    def __init__(self, state_dir, home=None):
        home = home or Path.home()
        self.target = home / ".claude/settings.json"
        self.key = home / ".litellm/master-key.txt"
        self.directory = state_dir / "profile-backups"
        self.journal = self.directory / "active.json"

    def private_directory(self):
        safe_path(self.directory / "probe")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ProfileError("Profile backup directory must be private (0700).")

    def settings(self):
        raw = read_bytes(self.target)
        settings = decode(raw)
        if not isinstance(settings.get("env", {}), dict):
            raise ProfileError("Claude env settings must be an object.")
        return settings, raw

    def record(self):
        raw = read_bytes(self.journal)
        if raw is None:
            return None
        record = decode(raw)
        fields = record.get("fields")
        allowed = set(MODELS) | {"ANTHROPIC_BASE_URL"}
        if (record.get("version") != 1 or record.get("target") != str(self.target)
                or not isinstance(fields, list) or len(fields) != len(allowed) + 2):
            raise ProfileError("Invalid recovery journal; keep backups and inspect manually.")
        seen = set()
        for field in fields:
            if not isinstance(field, dict):
                raise ProfileError("Invalid recovery field.")
            scope, key = field.get("scope"), field.get("key")
            pair = (scope, key)
            if (pair in seen or not (scope == "env" and key in allowed or scope == "root" and key in ("model", "apiKeyHelper"))
                    or type(field.get("present")) is not bool or "value" not in field
                    or not isinstance(field.get("applied"), str)):
                raise ProfileError("Invalid recovery field.")
            seen.add(pair)
        return record

    def status(self):
        record = self.record()
        if record is None:
            return "original"
        settings, _ = self.settings()
        return "gpt" if all(self.matches_applied(settings, f) for f in record["fields"]) else "conflict"

    def matches_applied(self, settings, field):
        if self.current(settings, field) == field["applied"]:
            return True
        model = settings.get("model")
        return (field["scope"] == "root" and field["key"] == "model"
                and isinstance(model, str) and model in SELECTABLE_MODELS)

    @staticmethod
    def current(settings, field):
        container = settings.get("env", {}) if field["scope"] == "env" else settings
        return fingerprint(field["key"] in container, container.get(field["key"]))

    def activate(self, port):
        LOG.debug("profile.activate enter")
        self.private_directory()
        if self.record() is not None:
            raise ProfileError("Previous GPTC profile needs recovery. Switch off before starting again.")
        settings, raw = self.settings()
        helper = Path(__file__).resolve().with_name("proxyctl.py")
        command = "/usr/bin/python3 -I -B " + "'" + str(helper).replace("'", "'\"'\"'") + "' gateway-key"
        values = {**MODELS, "ANTHROPIC_BASE_URL": "http://127.0.0.1:" + str(port)}
        snapshot = self.directory / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex + ".json")
        # Full original snapshot survives restoration, including original absence.
        atomic(snapshot, encoded({"existed": raw is not None, "settings": settings}), None)
        record = {"version": 1, "target": str(self.target), "snapshot": snapshot.name,
                  "existed": raw is not None, "env_present": "env" in settings, "fields": []}
        env = settings.setdefault("env", {})
        for scope, container, entries in (("env", env, values), ("root", settings, {"model": "gpt-6.1-sol", "apiKeyHelper": command})):
            for key, value in entries.items():
                record["fields"].append({"scope": scope, "key": key, "present": key in container,
                                         "value": container.get(key), "applied": fingerprint(True, value)})
                container[key] = value
        atomic(self.journal, encoded(record), None)
        atomic(self.target, encoded(settings), raw)
        LOG.info("profile.activate complete; private recovery snapshot saved")

    def restore(self):
        LOG.debug("profile.restore enter")
        record = self.record()
        if record is None:
            return
        settings, raw = self.settings()
        for field in record["fields"]:
            if (not self.matches_applied(settings, field)
                    and self.current(settings, field) != fingerprint(field["present"], field["value"])):
                raise ProfileError("GPTC-owned settings were edited. Recovery backup retained; restore edited fields before switching off.")
        for field in record["fields"]:
            container = settings.setdefault("env", {}) if field["scope"] == "env" else settings
            if field["present"]:
                container[field["key"]] = field["value"]
            else:
                container.pop(field["key"], None)
        if not settings.get("env") and not record["env_present"]:
            settings.pop("env", None)
        if not settings and not record["existed"]:
            if read_bytes(self.target) != raw:
                raise ProfileError("Settings changed concurrently; recovery retained.")
            self.target.unlink(missing_ok=True)
            if self.target.parent.exists():
                sync_directory(self.target.parent)
        else:
            atomic(self.target, encoded(settings), raw)
        self.journal.unlink()
        sync_directory(self.directory)
        LOG.info("profile.restore complete; original snapshot retained")
