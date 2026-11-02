[Back to README](../README.md)

# Claudex for KDE Plasma 6

A top-panel switch for your local LiteLLM proxy, without an open terminal.
The widget reuses your existing claude-code-chatgpt-proxy checkout and credentials.
A systemd user service supervises the proxy; the widget itself needs no resident daemon.

## Requirements

- Arch Linux with KDE Plasma 6 (developed against Plasma 6.7.5 / Wayland).
- Python 3, systemd, libplasma, plasma-workspace, plasma5support, kpackage, kirigami and ki18n.
- gettext (`msgfmt`) for compiling Russian translations during installation.
- An already working checkout of https://github.com/eugeny-dementev/claude-code-chatgpt-proxy
  at `~/claude-code-chatgpt-proxy`, including its existing `.venv` and authentication setup.
- A running user session bus. Run everything as your regular desktop user, not with sudo.

## Install

From this project's directory, inspect the proposed installation first:

```sh
/usr/bin/python3 -I -B scripts/install.py --dry-run
```

When ready to install:

```sh
/usr/bin/python3 -I -B scripts/install.py
```

Installation creates a user service, nonsecret configuration, and the Plasma applet.
It does NOT start or enable the proxy, change your panel, enable lingering, or restart Plasma.
Right-click an empty area of the top panel, enter Edit Mode, choose Add Widgets,
search for **Claudex**, and drag it onto the panel beside the system tray. Exit Edit Mode.
Its panel icon uses two large, opposing arrows in the panel's text color, without a background tile.
The glyph scales with panel height, with a small separate status dot.
The widget is not added to the panel automatically. The installer notifies KDE to refresh
its icon cache (using `gdbus` from glib2); close and reopen Add Widgets after an update.
If an older installation still shows a question-mark icon, refresh without restarting Plasma:

```sh
gdbus emit --session --object-path /KIconLoader --signal org.kde.KIconLoader.iconChanged 0
```

## Use

1. Click the panel icon to open the popup. Hover tooltips are disabled; status and details appear inside.
2. If the proxy is already running in a terminal, stop that instance yourself first.
3. Toggle **Proxy enabled** on. The service launches your existing script in the background.
4. Open **Details** for endpoint, process ID, uptime, local probe duration and recent logs.
5. Toggle off to stop only the managed service. This may interrupt active requests.

Closing the popup or removing the widget does not stop the service. Startup is manual:
there is no login autostart, automatic restart, or periodic model request.
Service survival after logout depends on your existing user-manager/session settings;
this project does not alter those settings.

## Global Claude Profile

After local readiness and service ownership are verified, Claudex saves a private full
snapshot of `~/.claude/settings.json`, then applies a temporary GPT profile. Restart
Claude Code after toggling; VS Code may require **Developer: Reload Window**. No
`source scripts/claude-codex-env.sh` is needed for future ordinary launches.
Fully close a VS Code instance previously launched from that sourced shell and reopen
it from the desktop once: inherited shell variables otherwise remain in its processes.
Project settings, explicit CLI model arguments, managed policies, custom
`CLAUDE_CONFIG_DIR`, remote/container sessions and stale inherited environments can
override this local default; they are not rewritten.

Settings contain an absolute `apiKeyHelper` command, **not a copy of the gateway key**.
That helper reads `~/.litellm/master-key.txt` only for Claude authentication while the
managed profile and locally verified proxy are enabled. It emits the key only to
Claude's helper pipe, never to logs or widget status. Claude caches helper results;
existing chats must be restarted and may fail when the proxy stops. The existing
LiteLLM Anthropic API authentication supports the API-key header used by this helper.
No provider inference is performed to check readiness.

While GPT mode is enabled, choosing one of its configured GPT models in Claude Code
(or the mapped Sonnet/Opus/Haiku aliases) keeps authentication enabled. Switching
Claudex off restores the model selected before activation. Changes to custom model
names, routing, authentication or other owned fields still require conflict recovery.
If the helper fails, Claude's `/status` includes its reason on stderr: a disabled
profile, conflicting settings, or an unready proxy. The key is never included.

On normal stop, startup failure or service exit, systemd runs profile restoration.
The widget also restores before requesting stop. Only Claudex-owned fields are
restored; unrelated edits are preserved. A conflict in an owned field refuses
restoration rather than overwriting the user's edit. The popup shows recovery state.
Backups are in `~/.config/cloudegpt-proxy-widget/profile-backups/` (or the configured
XDG config directory): directory 0700, files 0600. Timestamped full snapshots remain
for manual recovery; `active.json` is the write-ahead recovery journal, not a file to
delete to dismiss an error. Snapshots may contain your preexisting secrets; never
publish them. Installation and removal refuse an outstanding recovery journal and
retain all snapshots. After a power loss, use the widget's off switch to restore a
leftover profile before starting again. Status polling never changes settings.

For explicit recovery with the service already stopped, run the installed helper:

```sh
/usr/bin/python3 -I -B ~/.local/share/plasma/plasmoids/org.kde.plasma.cloudegptproxy/contents/code/proxyctl.py profile-off
```

If an owned field was edited, inspect its original value in the private snapshot and
resolve the conflict first; do not replace the entire settings file if it also has
new unrelated changes. A hard power loss or concurrent third-party settings writer
can require manual recovery. The helper checks for concurrent edits before atomic
replacement, but cannot lock other applications' configuration writers.

## Status And Privacy

| Status | Meaning |
|--------|---------|
| Off | Managed service is inactive |
| Starting / Stopping | A service transition is in progress |
| Running locally | Service active, local liveness succeeds, listener belongs to its cgroup |
| Readiness not verified | Process active, but local liveness or ownership is unverified |
| External instance / port occupied | Another listener is present; it is never killed or adopted |
| Service failed | Inspect Details and local logs before retrying |
| Backend unavailable | Helper, installation, user bus, or protocol problem |

Green does not prove account login, model availability, quota or successful inference.
Only `http://127.0.0.1:4001/health/liveliness` is probed by default, never `/health`.
Probe duration is local HTTP response time, NOT model latency. No tokens/cost counters are inferred.
Logs are unit-filtered and bounded to 200 entries / 64 KiB, with best-effort secret redaction.
They can still contain sensitive data; nothing is uploaded or automatically exported.
English and Russian interface labels are included; technical backend diagnostics use English.

## Configuration And Updates

Optional installation arguments: `--proxy-dir /absolute/path/to/checkout --port 4001`.
Ports must be 1024-65535. Stop the managed service before reinstalling or changing these settings.
Rerun the installer to update; it refuses unrelated or locally edited installed artifacts.
It preserves the upstream launcher, virtual environment, runtime YAML and credential files.

Installed locations (standard XDG defaults):

- `~/.config/systemd/user/cloudegpt-proxy.service`
- `~/.config/cloudegpt-proxy-widget/config.json` (proxy directory and port only)
- `~/.config/cloudegpt-proxy-widget/install.json` (ownership checksums)
- `~/.local/share/plasma/plasmoids/org.kde.plasma.cloudegptproxy/`
- `~/.local/share/icons/hicolor/scalable/apps/org.kde.plasma.cloudegptproxy.svg` (widget picker icon)

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` overrides must be absolute paths.
Do not edit the generated unit/config independently: the port must remain consistent.
For read-only local debugging after installation:

```sh
LOG_LEVEL=DEBUG /usr/bin/python3 -I -B package/contents/code/proxyctl.py status
journalctl --user --unit=cloudegpt-proxy.service --no-pager --lines=50
```

`LOG_LEVEL` defaults to INFO; DEBUG adds sanitized helper diagnostics on stderr.
The JSON response stays on stdout. Raw journal output is NOT redacted by journalctl.
If authentication expires, stop the service and follow upstream foreground login instructions;
the widget never opens an OAuth login or reads tokens. For a missing bridge, check plasma5support.
For changed-installation errors, inspect and back up your edits; do not delete files blindly.

## Remove

Remove the applet from the panel and explicitly turn off its managed service first.
The uninstaller refuses to remove an active installation; it never stops it automatically.

```sh
/usr/bin/python3 -I -B scripts/uninstall.py --dry-run
/usr/bin/python3 -I -B scripts/uninstall.py
```

Only verified installer-owned files are removed. Proxy checkout, credentials and journals remain.

## Development Checks

```sh
/usr/bin/python3 -I -B -m unittest discover -s tests -v
/usr/bin/python3 -I -B tests/check_picker_icon.py
/usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml package/contents/ui/*.qml
QT_QPA_PLATFORM=offscreen QML_DISABLE_DISK_CACHE=1 /usr/lib/qt6/bin/qmltestrunner -input tests/qml
QT_QPA_PLATFORM=offscreen QML_DISABLE_DISK_CACHE=1 /usr/lib/qt6/bin/qmltestrunner -input tests/smoke
```

Tests use fake service/HTTP responses; the bridge smoke test runs only a harmless JSON helper.
Offscreen runs can report installed icon-theme/window-system warnings.
Real panel placement, scaling, light/dark themes, translation loading, service start/stop,
and journal access still require authorized manual acceptance in the KDE session.

## See Also

- [Claudex installation and usage](../README.md) — user guide in Russian.
- [Upstream proxy](https://github.com/eugeny-dementev/claude-code-chatgpt-proxy) — proxy setup and authentication.
