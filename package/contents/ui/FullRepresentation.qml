import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

PlasmaComponents.ScrollView {
    id: root
    required property var controller
    required property string statusText
    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.preferredWidth: Kirigami.Units.gridUnit * 24
    Layout.minimumHeight: Kirigami.Units.gridUnit * 16
    Layout.preferredHeight: Kirigami.Units.gridUnit * (controller.detailsOpen ? 36 : 20)
    contentWidth: availableWidth

    ColumnLayout {
        width: root.availableWidth
        spacing: Kirigami.Units.smallSpacing * 2
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            Kirigami.Heading {
                text: Translations.i18n("Claudex")
                level: 2
                Layout.fillWidth: true
            }
            PlasmaComponents.BusyIndicator {
                running: root.controller.busy
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Layout.preferredWidth
            }
        }
        PlasmaComponents.Switch {
            id: powerSwitch
            objectName: "powerSwitch"
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing * 2
            text: Translations.i18n("Proxy enabled")
            Accessible.name: text
            activeFocusOnTab: true
            enabled: root.controller.actionEnabled
            checked: root.controller.switchOn
            onClicked: {
                root.controller.request(root.controller.switchOn ? "stop" : "start");
                checked = Qt.binding(function() { return root.controller.switchOn; });
            }
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            text: root.statusText
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            font.bold: true
            color: root.controller.backendAvailable && root.controller.status.state === "running"
                   ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing * 2
            Layout.rightMargin: Kirigami.Units.smallSpacing * 2
            text: Translations.i18n("Service: %1 | Local HTTP: %2", root.controller.status.service,
                                  root.controller.status.probe)
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            text: root.controller.errorMessage
            visible: text.length > 0
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            text: root.controller.status.state === "external"
                  ? Translations.i18n("Port occupied. Stop the terminal-launched proxy yourself before switching on.")
                  : Translations.i18n("Account and quota are not checked. Stopping may interrupt active requests.")
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            opacity: 0.8
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            text: root.controller.status.profile === "gpt"
                  ? Translations.i18n("Claude profile: GPT proxy. Restart Claude Code to apply.")
                  : root.controller.status.profile === "conflict"
                    ? Translations.i18n("Claude profile needs recovery. Private backups are retained; switch off or inspect settings conflicts.")
                    : Translations.i18n("Claude profile: original settings. Restart Claude Code after switching; VS Code may need Reload Window.")
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            PlasmaComponents.Button {
                objectName: "detailsButton"
                text: root.controller.detailsOpen ? Translations.i18n("Hide details") : Translations.i18n("Details")
                icon.name: root.controller.detailsOpen ? "go-up" : "go-down"
                onClicked: root.controller.detailsOpen = !root.controller.detailsOpen
            }
            Item { Layout.fillWidth: true }
            PlasmaComponents.Button {
                text: Translations.i18n("Refresh")
                icon.name: "view-refresh"
                enabled: !root.controller.busy
                onClicked: root.controller.request("status")
            }
        }
        DetailsView {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing * 2
            visible: root.controller.detailsOpen
            controller: root.controller
        }
    }
}
