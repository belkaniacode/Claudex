import QtQuick
import org.kde.plasma.plasma5support as Plasma5Support
import "../code/Command.js" as Command

Item {
    id: root
    visible: false
    property bool autoPoll: true
    property bool popupOpen: false
    property bool detailsOpen: false
    property bool busy: false
    property bool backendAvailable: false
    property string errorMessage: ""
    property string logs: ""
    property string logScope: ""
    property bool logsTruncated: false
    property url helperUrl: Qt.resolvedUrl("../code/proxyctl.py")
    property var transport: engine
    property var status: ({state: "unavailable", service: "unavailable", probe: "not_checked",
                           ownership: "unknown", endpoint: "", pid: 0, uptime: null,
                           latency_ms: null, can_start: false, can_stop: false})
    property string pendingSource: ""
    property string pendingId: ""
    property string pendingAction: ""
    property int sequence: 0
    property string instanceId: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2)
    readonly property bool transitioning: status.service === "activating" || status.service === "deactivating"
    readonly property bool switchOn: status.service === "active" || status.service === "activating"
                                     || status.profile === "gpt" || status.profile === "conflict"
    readonly property bool actionEnabled: backendAvailable && !busy && !transitioning && !actionPending
                                         && (switchOn ? status.can_stop : status.can_start)
    property bool actionPending: false
    property string actionTarget: ""
    readonly property int statusInterval: popupOpen || transitioning || actionPending ? 3000 : 15000
    signal diagnostic(string level, string event)

    function log(level, event) {
        diagnostic(level, event);
        if (level !== "DEBUG" || status.log_level === "DEBUG")
            console.log("[proxy-widget] " + level + " " + event);
    }

    function unavailable(message) {
        backendAvailable = false;
        errorMessage = message;
        log("ERROR", "backend.unavailable");
    }

    function request(action) {
        if (busy)
            return false;
        if ((action === "start" || action === "stop") && !actionEnabled)
            return false;
        if (!transport || !transport.valid) {
            unavailable(Translations.i18n("Backend unavailable"));
            return false;
        }
        try {
            pendingId = instanceId + "-" + (++sequence);
            pendingAction = action;
            pendingSource = Command.command(helperUrl, action, pendingId);
            busy = true;
            if (action === "start" || action === "stop") {
                actionPending = true;
                actionTarget = action;
                actionDeadline.restart();
            }
            watchdog.restart();
            log(action === "start" || action === "stop" ? "INFO" : "DEBUG", "request." + action);
            transport.connectSource(pendingSource);
            return true;
        } catch (error) {
            cleanup();
            unavailable(Translations.i18n("Unable to launch backend"));
            return false;
        }
    }

    function cleanup() {
        watchdog.stop();
        if (transport && pendingSource)
            transport.disconnectSource(pendingSource);
        pendingSource = "";
        busy = false;
    }

    function receive(source, data) {
        if (source !== pendingSource) {
            log("DEBUG", "response.stale");
            return;
        }
        const action = pendingAction;
        const requestId = pendingId;
        cleanup();
        try {
            if (data["exit status"] !== 0 || (data["exit code"] !== 0 && data["exit code"] !== 1))
                throw new Error("Helper process failed");
            const result = Command.response(data.stdout, requestId, action);
            if ((data["exit code"] === 0) !== result.ok)
                throw new Error("Exit status mismatch");
            if (result.ok) {
                status = result.status;
                backendAvailable = true;
                errorMessage = "";
                if (actionPending && (status.service === "failed"
                        || actionTarget === "start" && status.service === "active"
                        || actionTarget === "stop" && status.service === "inactive")) {
                    actionPending = false;
                    actionDeadline.stop();
                }
                if (action === "logs") {
                    logs = result.logs.text;
                    logsTruncated = result.logs.truncated;
                    logScope = result.logs.scope;
                }
            } else {
                if (action === "start" || action === "stop") {
                    actionPending = false;
                    actionDeadline.stop();
                }
                errorMessage = result.error.message;
                if (action === "status")
                    backendAvailable = false;
                log("WARN", "request.failed." + action);
            }
            if (action === "start" || action === "stop")
                refresh.restart();
        } catch (error) {
            unavailable(Translations.i18n("Invalid backend response"));
        }
    }

    onPopupOpenChanged: {
        log("DEBUG", popupOpen ? "popup.open" : "popup.close");
        if (popupOpen && autoPoll)
            request("status");
    }
    onDetailsOpenChanged: {
        log("DEBUG", detailsOpen ? "details.open" : "details.close");
        if (popupOpen && detailsOpen && autoPoll)
            request("logs");
    }
    Component.onCompleted: {
        if (autoPoll)
            request("status");
    }
    Component.onDestruction: cleanup()

    Plasma5Support.DataSource {
        id: engine
        engine: "executable"
        interval: 0
        connectedSources: []
    }
    Connections {
        target: root.transport
        function onNewData(sourceName, data) { root.receive(sourceName, data); }
    }
    Timer {
        interval: root.statusInterval
        running: root.autoPoll
        repeat: true
        onTriggered: root.request("status")
    }
    Timer {
        interval: 5000
        running: root.autoPoll && root.popupOpen && root.detailsOpen
        repeat: true
        onTriggered: root.request("logs")
    }
    Timer {
        id: refresh
        interval: 250
        onTriggered: root.request("status")
    }
    Timer {
        id: actionDeadline
        interval: 35000
        onTriggered: {
            root.actionPending = false;
            root.unavailable(Translations.i18n("Service action is taking longer than expected; refresh status."));
        }
    }
    Timer {
        id: watchdog
        interval: 10000
        onTriggered: {
            root.cleanup();
            root.unavailable(Translations.i18n("Backend timed out; refresh status before retrying"));
        }
    }
}
