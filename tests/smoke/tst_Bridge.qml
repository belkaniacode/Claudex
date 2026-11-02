import QtQuick
import QtTest
import org.kde.plasma.plasma5support as Plasma5Support
import "../../package/contents/code/Command.js" as Command

TestCase {
    id: test
    name: "RealExecutableBridge"
    property var result: null
    Plasma5Support.DataSource {
        id: engine
        engine: "executable"
        interval: 0
        connectedSources: []
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName);
            test.result = data;
        }
    }
    function test_repeatedSafeCommands() {
        verify(engine.valid);
        const argument = "space ' quote $ ; % #";
        for (let n = 0; n < 2; ++n) {
            result = null;
            const source = ["/usr/bin/python3", "-I", "-B",
                Command.localPath(Qt.resolvedUrl("../qml/fixtures/harmless.py")), argument, String(n)].map(Command.quote).join(" ");
            engine.connectSource(source);
            tryVerify(function() { return test.result !== null; }, 5000);
            compare(result["exit code"], 0);
            compare(result["exit status"], 0);
            compare(JSON.parse(result.stdout).arguments[0], argument);
        }
    }
}
