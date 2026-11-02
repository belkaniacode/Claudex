import QtQuick
import QtTest
import "../../package/contents/ui" as Widget

TestCase {
    id: test
    name: "ProxyController"
    property var controller: null
    QtObject {
        id: fake
        property bool valid: true
        property var commands: []
        property var disconnected: []
        signal newData(string sourceName, var data)
        function connectSource(source) { commands.push(source); }
        function disconnectSource(source) { disconnected.push(source); }
    }
    Component {
        id: factory
        Widget.ProxyController { autoPoll: false; transport: fake }
    }
    function init() {
        fake.commands = [];
        fake.disconnected = [];
        fake.valid = true;
        controller = factory.createObject(test);
    }
    function cleanup() {
        controller.destroy();
        controller = null;
        wait(1);
    }
    function state() {
        return {state: "off", service: "inactive", probe: "not_checked", ownership: "unknown",
                endpoint: "http://127.0.0.1:4001", can_start: true, can_stop: false};
    }
    function respond() {
        fake.newData(controller.pendingSource, {"exit status": 0, "exit code": 0, stdout: JSON.stringify({
            version: 1, request_id: controller.pendingId, action: controller.pendingAction,
            ok: true, error: null, status: state()})});
    }
    function test_noAutomaticMutation() {
        compare(fake.commands.length, 0);
        verify(!controller.request("start"));
        controller.request("status");
        respond();
        verify(controller.actionEnabled);
        compare(fake.commands.length, 1);
    }
    function test_busyAndStaleResponse() {
        controller.request("status");
        verify(!controller.request("status"));
        fake.newData("stale", {});
        verify(controller.busy);
        respond();
        verify(!controller.busy);
        compare(fake.disconnected.length, 1);
    }
    function test_malformedResponseIsUnavailable() {
        controller.request("status");
        fake.newData(controller.pendingSource, {"exit status": 0, "exit code": 0, stdout: "{}"});
        verify(!controller.backendAvailable);
        verify(!controller.busy);
        verify(controller.errorMessage.length > 0);
    }
    function test_uniqueSourcesAndPollingIntervals() {
        controller.request("status");
        respond();
        controller.request("status");
        verify(fake.commands[0] !== fake.commands[1]);
        compare(controller.statusInterval, 15000);
        controller.popupOpen = true;
        compare(controller.statusInterval, 3000);
    }
    function test_explicitMutationOnly() {
        controller.request("status");
        respond();
        verify(controller.request("start"));
        verify(fake.commands[1].indexOf("'start'") !== -1);
    }
    function test_actionRemainsPendingUntilObserved() {
        controller.request("status");
        respond();
        controller.request("start");
        respond();
        verify(controller.actionPending);
        verify(!controller.actionEnabled);
        controller.request("status");
        const active = state();
        active.service = "active";
        active.state = "degraded";
        active.can_stop = true;
        fake.newData(controller.pendingSource, {"exit status": 0, "exit code": 0, stdout: JSON.stringify({
            version: 1, request_id: controller.pendingId, action: "status", ok: true, error: null, status: active})});
        verify(!controller.actionPending);
        verify(controller.switchOn);
    }
    function test_logPollingRequiresBothViews() {
        controller.autoPoll = true;
        controller.popupOpen = false;
        controller.detailsOpen = true;
        compare(fake.commands.length, 0);
        controller.popupOpen = true;
        respond();
        controller.detailsOpen = false;
        controller.detailsOpen = true;
        compare(controller.pendingAction, "logs");
        controller.autoPoll = false;
    }
    function test_destroyDisconnectsPendingRequest() {
        controller.request("status");
        controller.destroy();
        controller = factory.createObject(test);
        wait(1);
        compare(fake.disconnected.length, 1);
        compare(fake.commands.length, 1);
    }
    function test_missingEngineAndCleanup() {
        fake.valid = false;
        verify(!controller.request("status"));
        fake.valid = true;
        controller.request("status");
        controller.cleanup();
        compare(fake.disconnected.length, 1);
        verify(!controller.busy);
    }
}
