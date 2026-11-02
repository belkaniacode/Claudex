.pragma library

function localPath(url) {
    const value = String(url);
    if (!value.startsWith("file:///") || /[?#]/.test(value))
        throw new Error("Expected an absolute local file URL");
    const path = decodeURIComponent(value.substring(7));
    if (path.indexOf("\0") !== -1)
        throw new Error("Invalid path");
    return path;
}

function quote(value) {
    const text = String(value);
    if (text.indexOf("\0") !== -1)
        throw new Error("Invalid command argument");
    return "'" + text.replace(/'/g, "'\"'\"'") + "'";
}

function command(url, action, requestId) {
    if (["status", "start", "stop", "logs"].indexOf(action) === -1)
        throw new Error("Invalid action");
    return ["/usr/bin/python3", "-I", "-B", localPath(url), action,
            "--request-id", requestId].map(quote).join(" ");
}

function response(text, requestId, action) {
    if (typeof text !== "string" || text.length > 524288)
        throw new Error("Invalid response size");
    const result = JSON.parse(text);
    if (result.version !== 1 || result.request_id !== requestId || result.action !== action
            || typeof result.ok !== "boolean" || !result.status)
        throw new Error("Invalid backend protocol");
    const status = result.status;
    if (["off", "starting", "running", "stopping", "error", "external", "unavailable", "degraded"].indexOf(status.state) === -1
            || typeof status.can_start !== "boolean" || typeof status.can_stop !== "boolean"
            || typeof status.service !== "string" || typeof status.probe !== "string"
            || typeof status.endpoint !== "string" || typeof status.ownership !== "string")
        throw new Error("Invalid status");
    if (!result.ok && (!result.error || typeof result.error.message !== "string"))
        throw new Error("Invalid error");
    if (action === "logs" && result.ok && (!result.logs || typeof result.logs.text !== "string"
            || result.logs.text.length > 65536 || typeof result.logs.truncated !== "boolean"))
        throw new Error("Invalid logs");
    return result;
}
