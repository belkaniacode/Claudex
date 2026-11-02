import QtQuick
import QtTest
import "../../package/contents/ui" as Widget

TestCase {
    id: test
    name: "NativeViews"
    when: windowShown
    width: 560
    height: 760
    QtObject {
        id: fake
        property bool busy: false
        property bool actionEnabled: true
        property bool backendAvailable: true
        property bool switchOn: false
        property bool detailsOpen: true
        property string errorMessage: ""
        property string logs: "INFO: ready\n<not rich text>"
        property string logScope: "current"
        property bool logsTruncated: false
        property var status: ({state: "off", service: "inactive", probe: "not_checked",
                              ownership: "unknown", endpoint: "http://127.0.0.1:4001", pid: 0,
                              uptime: null, latency_ms: null})
        property int calls: 0
        function request(action) { calls++; }
    }
    Widget.FullRepresentation {
        id: view
        controller: fake
        statusText: "Off"
        width: 500
        height: 700
    }
    function test_loadViews() {
        compare(fake.calls, 0);
        verify(findChild(view, "powerSwitch") !== null);
        compare(findChild(view, "logText").text, fake.logs);
        compare(findChild(view, "logText").textFormat, TextEdit.PlainText);
    }
}
