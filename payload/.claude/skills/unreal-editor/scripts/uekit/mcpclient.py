"""Stdlib MCP client for the in-editor Unreal MCP server (streamable HTTP).

The server exposes three meta-tools: list_toolsets, describe_toolset, call_tool.
"""
import json
import urllib.error
import urllib.request

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class McpError(RuntimeError):
    pass


class Client:
    def __init__(self, url, timeout=600):
        self.url, self.timeout, self.sid, self._id = url, timeout, None, 0

    def _post(self, body):
        h = dict(HEADERS)
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.sid = r.headers.get("Mcp-Session-Id") or self.sid
                data = r.read().decode("utf-8", "replace")
        except urllib.error.URLError as e:
            raise McpError("Cannot reach MCP server at %s (%s). Is the editor running? `ue status`" % (self.url, e))
        if not data.strip():
            return None
        if data.lstrip().startswith("event:") or data.lstrip().startswith("data:"):
            data = "\n".join(l[5:].strip() for l in data.splitlines() if l.startswith("data:"))
        return json.loads(data)

    def connect(self):
        self._id += 1
        self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ue-claude-kit", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tool(self, name, args=None):
        """Call a top-level MCP tool. Returns (is_error, text)."""
        self._id += 1
        r = self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}}})
        if "error" in r:
            raise McpError(r["error"].get("message", str(r["error"])))
        res = r["result"]
        return bool(res.get("isError")), "\n".join(c.get("text", "") for c in res.get("content", []))

    def call(self, toolset, tool, args=None):
        """Call a toolset tool; returns parsed JSON (usually {"returnValue": ...}) or raises McpError."""
        err, text = self.tool("call_tool", {"toolset_name": toolset, "tool_name": tool, "arguments": args or {}})
        if err:
            raise McpError("%s.%s failed: %s" % (toolset, tool, text[:2000]))
        try:
            return json.loads(text)
        except ValueError:
            return text

    def list_toolsets(self):
        return self.tool("list_toolsets")[1]

    def describe(self, toolset):
        err, text = self.tool("describe_toolset", {"toolset_name": toolset})
        if err:
            raise McpError(text)
        return json.loads(text)
