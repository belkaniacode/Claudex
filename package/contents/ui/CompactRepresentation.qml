import QtQuick
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

PlasmaComponents.ToolButton {
    id: root
    required property string statusText
    required property string proxyState
    signal activated()
    padding: 2
    leftPadding: 2
    rightPadding: 2
    topPadding: 2
    bottomPadding: 2
    readonly property real glyphSize: Math.max(0, Math.min(width, height) - 4)
    icon.source: Qt.resolvedUrl("../icons/gptc.svg")
    icon.width: glyphSize
    icon.height: glyphSize
    contentItem: Item {
        Kirigami.Icon {
            anchors.centerIn: parent
            width: root.icon.width
            height: root.icon.height
            source: root.icon.source
            isMask: true
            color: Kirigami.Theme.textColor
        }
    }
    Accessible.name: Translations.i18n("Claudex") + ": " + statusText
    activeFocusOnTab: true
    display: PlasmaComponents.AbstractButton.IconOnly
    onClicked: activated()
    Rectangle {
        width: 5
        height: width
        radius: width / 2
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 1
        color: root.proxyState === "running" ? Kirigami.Theme.positiveTextColor
             : root.proxyState === "off" ? Kirigami.Theme.disabledTextColor
             : root.proxyState === "error" ? Kirigami.Theme.negativeTextColor
             : Kirigami.Theme.neutralTextColor
        border.width: 1
        border.color: Kirigami.Theme.backgroundColor
    }
}
