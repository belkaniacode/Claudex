import QtQuick
import QtTest
import org.kde.plasma.private.shell
import org.kde.kirigami as Kirigami

TestCase {
    id: test
    name: "InstalledPickerIcon"
    when: windowShown
    width: 160
    height: 160
    property var gptc: null
    WidgetExplorer { id: explorer }
    Repeater {
        model: explorer.widgetsModel
        delegate: Item {
            required property var model
            Component.onCompleted: {
                if (model.pluginName === "org.kde.plasma.cloudegptproxy") {
                    test.gptc = model;
                    console.log("[FIX:picker-icon] decoration=" + model.decoration + " screenshot=" + model.screenshot);
                }
            }
        }
    }
    Kirigami.Icon {
        id: icon
        width: 128
        height: 128
        source: test.gptc ? test.gptc.decoration : ""
    }
    function test_pickerIconIsValid() {
        tryVerify(function() { return test.gptc !== null; }, 5000);
        console.log("[FIX:picker-icon] name=" + test.gptc.pluginName + " decoration=" + test.gptc.decoration + " screenshot=" + test.gptc.screenshot + " source=" + icon.source);
        tryCompare(icon, "valid", true);
    }
}
