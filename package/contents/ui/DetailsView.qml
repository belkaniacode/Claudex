import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root
    required property var controller
    spacing: Kirigami.Units.smallSpacing
    PlasmaComponents.Label {
        Layout.fillWidth: true
        text: root.controller.status.endpoint || "-"
        textFormat: Text.PlainText
        elide: Text.ElideMiddle
    }
    PlasmaComponents.Label {
        Layout.fillWidth: true
        text: Translations.i18n("PID: %1 | Uptime: %2 s", root.controller.status.pid || "-",
                              root.controller.status.uptime === null ? "-" : root.controller.status.uptime)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }
    PlasmaComponents.Label {
        Layout.fillWidth: true
        text: Translations.i18n("Local probe: %1 ms | Ownership: %2",
                              root.controller.status.latency_ms === null ? "-" : root.controller.status.latency_ms,
                              root.controller.status.ownership)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }
    PlasmaComponents.Label {
        text: root.controller.logScope === "current" ? Translations.i18n("Current service logs")
                                                    : Translations.i18n("Recent logs (may include previous runs)")
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    PlasmaComponents.ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit * 12
        PlasmaComponents.TextArea {
            id: logText
            objectName: "logText"
            text: root.controller.logs || Translations.i18n("No logs available")
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            Accessible.name: Translations.i18n("Service logs")
            font.family: "monospace"
        }
    }
    PlasmaComponents.Label {
        visible: root.controller.logsTruncated
        text: Translations.i18n("Output limit reached; showing a bounded excerpt.")
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    PlasmaComponents.Label {
        text: Translations.i18n("Logs may contain sensitive data. Redaction is best-effort.")
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        opacity: 0.7
    }
}
