pragma ComponentBehavior: Bound
import QtQuick
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root
    preferredRepresentation: compactRepresentation
    readonly property string proxyState: backendController.backendAvailable ? backendController.status.state : "unavailable"
    readonly property string statusText: {
        switch (proxyState) {
        case "off": return Translations.i18n("Off");
        case "starting": return Translations.i18n("Starting");
        case "running": return Translations.i18n("Running locally");
        case "stopping": return Translations.i18n("Stopping");
        case "error": return Translations.i18n("Service failed - see details");
        case "external": return Translations.i18n("External instance / port occupied");
        case "degraded": return Translations.i18n("Service running; local readiness not verified");
        default: return Translations.i18n("Backend unavailable");
        }
    }
    toolTipMainText: ""
    toolTipSubText: ""
    ProxyController {
        id: backendController
        popupOpen: root.expanded
    }
    compactRepresentation: CompactRepresentation {
        proxyState: root.proxyState
        statusText: root.statusText
        onActivated: root.expanded = !root.expanded
    }
    fullRepresentation: FullRepresentation {
        controller: backendController
        statusText: root.statusText
    }
}
