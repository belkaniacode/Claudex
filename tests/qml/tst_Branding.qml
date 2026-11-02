import QtQuick
import QtTest
import org.kde.plasma.components as PlasmaComponents
import "../../package/contents/ui" as Widget

TestCase {
    id: test
    name: "ClaudexBranding"
    when: windowShown
    visible: true
    width: 100
    height: 100

    Widget.CompactRepresentation {
        id: button
        width: 32
        height: 32
        proxyState: "off"
        statusText: "Off"
    }
    Image {
        id: image
        source: button.icon.source
        width: 32
        height: 32
        visible: false
    }
    SignalSpy {
        id: activated
        target: button
        signalName: "activated"
    }
    function test_iconLoadsAtPanelSizes() {
        tryCompare(image, "status", Image.Ready);
        verify(String(button.icon.source).endsWith("/icons/gptc.svg"));
        for (const size of [16, 22, 32, 48]) {
            image.sourceSize = Qt.size(size, size);
            tryCompare(image, "status", Image.Ready);
        }
    }
    function test_iconFillsSmallPanelButton() {
        button.width = 28;
        button.height = 28;
        wait(0);
        console.log("[FIX:panel-icon] button=28 icon=" + button.icon.width + "x" + button.icon.height);
        verify(button.icon.width >= 22, "Panel icon should be at least 22 px in a 28 px button");
        verify(button.icon.height >= 22);
        verify(button.leftPadding <= 3 && button.rightPadding <= 3);
        button.width = 32;
        button.height = 32;
    }
    property bool tooltipAppeared: false
    Connections {
        target: button.PlasmaComponents.ToolTip
        function onVisibleChanged() {
            if (button.PlasmaComponents.ToolTip.visible)
                test.tooltipAppeared = true;
        }
    }
    function test_hoverHasNoTooltipAndRemainsClickable() {
        tooltipAppeared = false;
        mouseMove(test, 90, 90);
        mouseMove(button, button.width / 2, button.height / 2);
        wait(100);
        console.log("[FIX:no-tooltip] hovered=" + button.hovered
                    + " tooltip=" + button.PlasmaComponents.ToolTip.visible);
        compare(tooltipAppeared, false, "Hover must never open a tooltip");
        compare(button.PlasmaComponents.ToolTip.visible, false);
        activated.clear();
        mouseClick(button, button.width / 2, button.height / 2);
        compare(activated.count, 1);
        mouseMove(test, 90, 90);
    }
    function test_nameAndKeyboardActivation() {
        compare(button.Accessible.name, "Claudex: Off");
        activated.clear();
        button.forceActiveFocus();
        keyClick(Qt.Key_Space);
        compare(activated.count, 1);
    }
}
