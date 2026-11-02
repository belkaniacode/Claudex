#!/usr/bin/python3
"""Finite, bridge between Plasma and one user service."""

import argparse
import importlib.util
from contextlib import contextmanager
import fcntl
import http.client
import json
import selectors
import signal
import socket
import stat
import subprocess
import logging
import os
from pathlib import Path
import re
import sys
import time

UNIT = "cloudegpt-proxy.service"
APP_ID = "org.kde.plasma.cloudegptproxy"
CONFIG_DIR = "cloudegpt-proxy-widget"
PROTOCOL_VERSION = 1
LOG = logging.getLogger("proxy-widget")


class BackendError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def configure_logging():
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s [proxy-widget] %(message)s")


def config_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not base.is_absolute():
        raise BackendError("config", "XDG_CONFIG_HOME must be an absolute path.")
    return base / CONFIG_DIR / "config.json"


def load_config(path=None):
    path = path or config_path()
    LOG.debug("config.load enter")
    try:
        with path.open("rb") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized")
        config = json.loads(raw)
        directory = config["proxy_dir"]
        port = config["port"]
        if not isinstance(directory, str) or not Path(directory).is_absolute():
            raise ValueError("path")
        if any(ord(char) < 32 for char in directory):
            raise ValueError("path control characters")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("port")
    except FileNotFoundError as error:
        raise BackendError("not_installed", "Run the widget installer first.") from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BackendError("config", "Invalid or unreadable widget configuration; rerun the installer.") from error
    LOG.debug("config.load exit")
    return {"proxy_dir": directory, "port": port}


def profile_manager():
    spec = importlib.util.spec_from_file_location("claudex_profile", Path(__file__).with_name("profile.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Profile(config_path().parent)


def profile_call(action, *args):
    try:
        return getattr(profile_manager(), action)(*args)
    except Exception as error:
        LOG.warning("profile.failed operation=%s type=%s", action, type(error).__name__)
        raise BackendError("profile", "Claude profile operation failed. Check settings and private profile-backups recovery files for conflicts.") from error


def service_profile(action):
    deadline = time.monotonic() + (25 if action == "profile-on" else 5)
    config = load_config() if action == "profile-on" else None
    while time.monotonic() < deadline:
        ready = action == "profile-off"
        if not ready:
            props = service_properties()
            if props.get("ActiveState") not in ("activating", "active"):
                raise BackendError("profile_start", "Service stopped before local readiness.")
            ready = (probe_local(config["port"])[0] == "responsive"
                     and listener_ownership(config["port"], props.get("ControlGroup")) == "managed")
        if ready:
            try:
                with mutation_lock():
                    if action == "profile-off":
                        profile_call("restore")
                    else:
                        profile_call("activate", config["port"])
                return
            except BackendError as error:
                if error.code != "busy":
                    raise
        time.sleep(0.25)
    raise BackendError("profile_start", "Profile lifecycle timed out; inspect local diagnostics and recovery backup.")


def gateway_key():
    # This stdout belongs exclusively to Claude's apiKeyHelper, never to QML.
    with mutation_lock():
        profile_status = profile_call("status")
        if profile_status == "conflict":
            raise BackendError("profile_conflict", "GPT profile settings were changed. Check Claudex profile recovery before retrying.")
        if profile_status != "gpt":
            raise BackendError("profile_disabled", "GPT profile is not enabled. Enable Claudex and restart Claude Code.")
        config = load_config()
        state = observed_state(config)
        if state["state"] != "running":
            raise BackendError("proxy_not_ready", "Managed proxy is not ready. Check Claudex service status before retrying.")
        key = Path.home() / ".litellm/master-key.txt"
        fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise BackendError("profile", "Invalid local gateway key file.")
            raw = stream.read(8193)
        token = raw.decode().strip()
        if not token or len(raw) > 8192 or any(ord(c) < 32 for c in token):
            raise BackendError("profile", "Invalid local gateway key.")
        sys.stdout.write(token + "\n")


def empty_state():
    return {"service": "unavailable", "probe": "not_checked", "ownership": "unknown",
            "state": "unavailable", "endpoint": "", "pid": 0, "uptime": None,
            "latency_ms": None, "can_start": False, "can_stop": False,
            "invocation": "", "log_level": os.environ.get("LOG_LEVEL", "INFO").upper()}


def cleanup_process(process):
    # Popen.__exit__ waits without a deadline, even after a timed wait failed.
    for pipe in (process.stdout, process.stderr):
        if pipe:
            pipe.close()
    if process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            LOG.warning("subprocess.cleanup child_not_reaped")


def run_bounded(argv, limit=65536, timeout=3):
    """Drain both pipes without unbounded communicate() buffering."""
    LOG.debug("subprocess.enter tool=%s", Path(argv[0]).name)
    output = bytearray()
    total = 0
    truncated = False
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"})
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                deadline = time.monotonic() + timeout
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BackendError("timeout", "System command timed out; refresh status before retrying.")
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if key.data:
                            output.extend(chunk[:max(0, limit - len(output))])
                        if total > limit:
                            truncated = True
                            break
                    if truncated:
                        break
            if truncated:
                process.kill()
            result = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        finally:
            cleanup_process(process)
    except OSError as error:
        raise BackendError("command", "A required system command is missing or inaccessible.") from error
    except subprocess.TimeoutExpired as error:
        raise BackendError("timeout", "System command timed out; refresh status before retrying.") from error
    if result and not truncated:
        raise BackendError("command", "System command failed; check the user session bus or journal permissions.")
    LOG.debug("subprocess.exit bytes=%d truncated=%s", len(output), truncated)
    return output.decode("utf-8", "replace"), truncated


def service_properties(runner=run_bounded):
    names = ("LoadState", "ActiveState", "SubState", "Result", "MainPID", "ExecMainStatus",
             "ControlGroup", "InvocationID", "ActiveEnterTimestampMonotonic")
    raw, truncated = runner(["/usr/bin/systemctl", "--user", "show", UNIT,
                             "--property=" + ",".join(names)], limit=8192)
    if truncated:
        raise BackendError("protocol", "Service state output exceeded its limit.")
    props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if not props.get("LoadState") or not props.get("ActiveState"):
        raise BackendError("protocol", "Service manager returned an incomplete state.")
    return props


def port_occupied(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return None


def probe_local(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    started = time.monotonic()
    try:
        connection.request("GET", "/health/liveliness", headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(1025)
        valid = response.status == 200 and len(body) <= 1024 and json.loads(body) == "I'm alive!"
        return ("responsive" if valid else "unexpected"), round((time.monotonic() - started) * 1000)
    except (OSError, ValueError, http.client.HTTPException):
        return "unavailable", None
    finally:
        connection.close()


def listener_ownership(port, group, proc=Path("/proc")):
    if not group or not group.startswith("/") or group == "/":
        return "unknown"
    try:
        inodes = set()
        for line in (proc / "net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            address, port_hex = fields[1].split(":")
            if fields[3] == "0A" and int(port_hex, 16) == port and address in ("0100007F", "00000000"):
                inodes.add(fields[9])
        if not inodes:
            return "unknown"
        owned = set()
        external = set()
        for directory in proc.iterdir():
            if not directory.name.isdigit():
                continue
            try:
                groups = [line.split(":", 2)[2] for line in (directory / "cgroup").read_text().splitlines()]
                managed = any(g == group or g.startswith(group + "/") for g in groups)
                for fd in (directory / "fd").iterdir():
                    try:
                        target = os.readlink(fd)
                    except OSError:
                        continue
                    if target.startswith("socket:[") and target[8:-1] in inodes:
                        (owned if managed else external).add(target[8:-1])
            except (OSError, IndexError):
                continue
        if external:
            return "external"
        return "managed" if owned == inodes else "unknown"
    except (OSError, ValueError, IndexError):
        return "unknown"


def observed_state(config, props=None):
    props = props if props is not None else service_properties()
    status = empty_state()
    status["endpoint"] = "http://127.0.0.1:" + str(config["port"])
    service = props.get("ActiveState", "unavailable")
    if props.get("LoadState") == "not-found":
        service = "missing"
    elif props.get("LoadState") != "loaded":
        service = "unavailable"
    status["service"] = service
    status["invocation"] = props.get("InvocationID", "")
    status["pid"] = int(props.get("MainPID", "0") or 0)
    status["result"] = props.get("Result", "")
    entered = int(props.get("ActiveEnterTimestampMonotonic", "0") or 0)
    if service == "active" and entered:
        status["uptime"] = max(0, int(time.monotonic() - entered / 1000000))
    occupied = port_occupied(config["port"])
    if occupied:
        status["probe"], status["latency_ms"] = probe_local(config["port"])
        status["ownership"] = listener_ownership(config["port"], props.get("ControlGroup"))
        if service in ("inactive", "failed", "missing"):
            status["ownership"] = "external"
    status["can_start"] = service in ("inactive", "failed") and occupied is False
    status["can_stop"] = service in ("active", "activating")
    status["state"] = {"inactive": "off", "activating": "starting", "deactivating": "stopping",
                       "failed": "error", "missing": "unavailable"}.get(service, "unavailable")
    if status["ownership"] == "external":
        status["state"] = "external"
    elif service == "active":
        status["state"] = "running" if status["ownership"] == "managed" and status["probe"] == "responsive" else "degraded"
    LOG.debug("state.observed service=%s probe=%s ownership=%s", service, status["probe"], status["ownership"])
    return status


@contextmanager
def mutation_lock():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or ("/run/user/" + str(os.getuid())))
    info = runtime.stat()
    if not runtime.is_absolute() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BackendError("runtime", "Private user runtime directory is unavailable.")
    fd = os.open(runtime / "cloudegpt-proxy-widget.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise BackendError("runtime", "Unsafe control lock file.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackendError("busy", "Another widget action is pending; refresh status.") from error
        yield
    finally:
        os.close(fd)


def control(action, config):
    with mutation_lock():
        props = service_properties()
        service = props.get("ActiveState")
        if props.get("LoadState") != "loaded":
            raise BackendError("not_installed", "Managed service is unavailable; rerun the installer.")
        if action == "start":
            if service in ("active", "activating"):
                return props
            if service == "deactivating":
                raise BackendError("busy", "Service is still stopping.")
            if port_occupied(config["port"]) is not False:
                raise BackendError("port_conflict", "Port occupied or unavailable. Stop the external proxy yourself before starting this service.")
        elif service in ("inactive", "failed"):
            profile_call("restore")
            return props
        if action == "stop":
            profile_call("restore")
        LOG.info("control.submit action=%s", action)
        run_bounded(["/usr/bin/systemctl", "--user", "--no-block", action, UNIT], limit=8192)
        return service_properties()


def sanitize_logs(text):
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32 and ord(char) != 127)
    text = re.sub(r"(?im)^.*(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|master[_-]?key|device[_ -]?code|user[_ -]?code|password|cookie).*$", "[sensitive log line redacted]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b", "[redacted]", text)
    return text


def recent_logs(props):
    invocation = props.get("InvocationID", "")
    current = props.get("ActiveState") in ("active", "activating", "deactivating") and re.fullmatch(r"[a-fA-F0-9]{32}", invocation or "")
    argv = ["/usr/bin/journalctl", "--user", "--unit=" + UNIT, "--no-pager", "--quiet",
            "--lines=200", "--output=short-iso"]
    if current:
        argv.append("_SYSTEMD_INVOCATION_ID=" + invocation)
    output, truncated = run_bounded(argv)
    return {"text": sanitize_logs(output), "truncated": truncated,
            "scope": "current" if current else "previous"}


def dispatch(action):
    config = load_config()
    if action in ("start", "stop"):
        props = control(action, config)
    else:
        props = service_properties()
    result = {"status": observed_state(config, props)}
    try:
        result["status"]["profile"] = profile_call("status")
    except BackendError:
        result["status"]["profile"] = "conflict"
    if result["status"]["profile"] != "original":
        result["status"]["can_stop"] = True
        result["status"]["can_start"] = False
    if action == "logs":
        result["logs"] = recent_logs(props)
    return result


def deadline_expired(signum, frame):
    raise BackendError("timeout", "Backend deadline exceeded; refresh status before retrying.")


def main(argv=None):
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "start", "stop", "logs", "profile-on", "profile-off", "gateway-key"))
    parser.add_argument("--request-id", default="cli")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", args.request_id):
        parser.error("request ID must contain 1-100 letters, digits, dots, underscores or hyphens")
    started = time.monotonic()
    response = {"version": PROTOCOL_VERSION, "request_id": args.request_id,
                "action": args.action, "ok": False, "error": None, "status": empty_state()}
    signal.signal(signal.SIGALRM, deadline_expired)
    signal.setitimer(signal.ITIMER_REAL, 30 if args.action == "profile-on" else 8)
    try:
        LOG.debug("request.enter action=%s id=%s", args.action, args.request_id)
        if args.action == "gateway-key":
            gateway_key()
            return 0
        if args.action in ("profile-on", "profile-off"):
            service_profile(args.action)
        else:
            response.update(dispatch(args.action))
        response["ok"] = True
    except BackendError as error:
        LOG.warning("request.failed action=%s code=%s", args.action, error.code)
        if args.action == "gateway-key":
            # Claude shows stderr in /status; BackendError messages contain no key values.
            LOG.warning("%s", error)
        response["error"] = {"code": error.code, "message": str(error)}
    except Exception as error:
        LOG.error("request.failed action=%s type=%s", args.action, type(error).__name__)
        response["error"] = {"code": "internal", "message": "Backend failed; inspect local diagnostics."}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    LOG.debug("request.exit action=%s ok=%s elapsed_ms=%d", args.action, response["ok"],
              (time.monotonic() - started) * 1000)
    if args.action == "gateway-key":
        return 1
    print(json.dumps(response, ensure_ascii=True))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
