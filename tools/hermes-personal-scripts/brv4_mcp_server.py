# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""ByteRover V4 MCP Server — wraps scripts/*.mjs as MCP tools for Hermes."""
import json, os, subprocess
from pathlib import Path

SKILL_DIR = Path(os.path.expandvars(r"%USERPROFILE%")) / ".hermes" / "skills" / "byterover"
SCRIPTS_DIR = SKILL_DIR / "scripts"

import shutil
_NODE = shutil.which("node") or "node"
# Prefer the npm-bundled node.exe if available
_npm_node = os.path.join(os.path.expandvars(r"%APPDATA%"), r"npm\node.exe")
if os.path.exists(_npm_node):
    _NODE = _npm_node

def _run(script: str, *args, timeout: int = 60) -> dict:
    cmd = [_NODE, str(SCRIPTS_DIR / script)] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(SKILL_DIR), stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stderr and not stdout:
            return {"ok": False, "error": stderr}
        try:
            return json.loads(stdout) if stdout else {"ok": False, "error": "empty output"}
        except json.JSONDecodeError:
            return {"ok": True, "text": stdout}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("byterover-v4")

@mcp.tool()
def brv4_query(query: str, limit: int = 5) -> str:
    """Search ByteRover V4 memory. Use BEFORE any non-trivial task."""
    return json.dumps(_run("query.mjs", query, "--limit", str(limit)), ensure_ascii=False, indent=2)

@mcp.tool()
def brv4_record(path: str, title: str = "", summary: str = "", keywords: str = "", body: str = "") -> str:
    """Save knowledge to ByteRover V4. Use AFTER completing important work."""
    args = ["record.mjs", path]
    if title: args += ["--title", title]
    if summary: args += ["--summary", summary]
    if keywords: args += ["--keywords", keywords]
    if body: args += ["--body", body]
    return json.dumps(_run(*args), ensure_ascii=False, indent=2)

@mcp.tool()
def brv4_dream(mode: str = "merge") -> str:
    """Detect consolidation opportunities. Modes: merge, link, prune, synthesize."""
    return json.dumps(_run("dream.mjs", "--mode", mode), ensure_ascii=False, indent=2)

@mcp.tool()
def brv4_list() -> str:
    """List all topics in the current ByteRover space."""
    return json.dumps(_run("brv.mjs", "list"), ensure_ascii=False, indent=2)

@mcp.tool()
def brv4_status() -> str:
    """Check ByteRover V4 authentication and space status."""
    auth = _run("auth.mjs", "whoami")
    space = _run("space.mjs", "current")
    return json.dumps({"auth": auth, "space": space}, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    mcp.run()
