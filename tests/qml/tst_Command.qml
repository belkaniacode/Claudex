import QtQuick
import QtTest
import "../../package/contents/code/Command.js" as Command

TestCase {
    name: "CommandProtocol"
    function test_quoting() {
        compare(Command.quote("a'b $;"), "'a'\"'\"'b $;'");
        compare(Command.localPath("file:///tmp/a%20%27%23%25%24%3B"), "/tmp/a '#%$;");
        compare(Command.localPath("file:///tmp/%D1%82%D0%B5%D1%81%D1%82"), "/tmp/тест");
    }
    function test_rejectUnsafeUrls() {
        for (const url of ["https://example.com", "file://host/tmp/a", "file:///tmp/a#b", "file:///tmp/%00"])
            verify(exceptionThrown(function() { Command.localPath(url); }));
    }
    function exceptionThrown(callback) {
        try { callback(); return false; } catch (error) { return true; }
    }
    function test_invalidActionsAndProtocol() {
        verify(exceptionThrown(function() { Command.command("file:///tmp/a", "restart", "1"); }));
        verify(exceptionThrown(function() { Command.response("{}", "1", "status"); }));
        verify(exceptionThrown(function() { Command.response("not JSON", "1", "status"); }));
    }
}
