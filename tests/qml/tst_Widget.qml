import QtQuick
import QtTest
import "../../package/contents/ui" as Widget

TestCase {
    id: test
    name: "WidgetInteractions"
    when: windowShown
    width: 560
    height: 760
    QtObject {
        id: fake
        property bool busy: false
        property bool actionEnabled: true
        property bool backendAvailable: true
        property bool switchOn: false
        property bool detailsOpen: false
        property string errorMessage: ""
        property string logs: "<b>not markup</b>"
        property string logScope: "current"
        property bool logsTruncated: false
        property var status: ({state: "off", service: "inactive", probe: "not_checked",
            ownership: "unknown", endpoint: "http://127.0.0.1:4001", pid: 0, uptime: null, latency_ms: null})
        property var calls: []
        function request(action) { calls.push(action); }
    }
    Widget.FullRepresentation {
        id: view
        width: 500
        height: 700
        controller: fake
        statusText: "Off"
    }
    function init() { fake.calls = []; fake.switchOn = false; fake.detailsOpen = false; }
    function test_observedStateDoesNotIssueActions() {
        fake.switchOn = true;
        compare(fake.calls.length, 0);
        compare(findChild(view, "powerSwitch").checked, true);
    }
    function test_keyboardSwitchRequestsWithoutOptimism() {
        const control = findChild(view, "powerSwitch");
        control.forceActiveFocus();
        keyClick(Qt.Key_Space);
        compare(fake.calls[0], "start");
        compare(control.checked, false);
    }
    function test_detailsAndPlainText() {
        const button = findChild(view, "detailsButton");
        button.forceActiveFocus();
        keyClick(Qt.Key_Space);
        verify(fake.detailsOpen);
        compare(fake.calls.length, 0);
        compare(findChild(view, "logText").textFormat, TextEdit.PlainText);
    }
}
