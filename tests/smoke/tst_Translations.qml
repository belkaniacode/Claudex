import QtQuick
import QtTest
import "../../package/contents/ui" as Widget

TestCase {
    name: "TranslationContext"
    function test_explicitDomain() {
        compare(Widget.Translations.translationDomain, "plasma_applet_org.kde.plasma.cloudegptproxy");
        verify(Widget.Translations.i18n("Claudex").length > 0);
    }
}
