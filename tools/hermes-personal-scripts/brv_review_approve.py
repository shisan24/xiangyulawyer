# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
# ByteRover Review Auto-Approve Script - v3
# Auto-approves all pending ByteRover reviews so curated facts become queryable
# Usage: python brv_review_approve.py [workdir]
#   workdir: path to project dir containing .brv/context-tree (optional, auto-detects)

import subprocess, sys, os, re, glob

NODE = r"[本地路径] Files\nodejs\node.exe"
BRV_CLI = r"[本地路径]"

def find_context_tree():
    """Find the .brv/context-tree directory. Checks: explicit arg, cwd, runtime dirs."""
    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if os.path.isdir(os.path.join(candidate, ".brv", "context-tree")):
            return candidate
    
    # Check CWD
    if os.path.isdir(".brv/context-tree"):
        return os.getcwd()
    
    # Check runtime version dirs
    runtime_base = os.path.expandvars(r"%APPDATA%\cn.org.hermesagent.desktop\runtime\versions")
    if os.path.isdir(runtime_base):
        for d in sorted(os.listdir(runtime_base), reverse=True):
            full = os.path.join(runtime_base, d)
            if os.path.isdir(os.path.join(full, ".brv", "context-tree")):
                return full
    
    # Check hardcoded fallback paths (cron workdir may not propagate)
    for hard in [r"[本地路径]", r"[本地路径]"]:
        if os.path.isdir(os.path.join(hard, ".brv", "context-tree")):
            return hard
    
    return None

def run_brv(cwd, *args):
    try:
        result = subprocess.run(
            [NODE, BRV_CLI] + list(args),
            capture_output=True, text=True, timeout=120,
            cwd=cwd
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as e:
        return False, str(e)

def main():
    cwd = find_context_tree()
    if not cwd:
        print("[SKIP] No ByteRover context tree found (.brv/context-tree). Nothing to do.")
        return 0
    
    ok, output = run_brv(cwd, "review", "pending")
    if not ok:
        print(f"[SKIP] brv review pending failed: {output}")
        return 1
    
    if "No pending reviews" in output:
        print("[OK] No pending reviews.")
        return 0
    
    task_ids = []
    seen = set()
    for line in output.split("\n"):
        m = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", line.strip())
        if m:
            tid = m.group(1)
            if tid not in seen:
                task_ids.append(tid)
                seen.add(tid)
    
    if not task_ids:
        # No pending reviews — silent success
        return 0
    
    for tid in task_ids:
        ok, out = run_brv(cwd, "review", "approve", tid)
        if not ok:
            print(f"[FAILED] approve {tid}: {out}")
            return 1
    
    # Approved successfully — silent
    return 0

if __name__ == "__main__":
    sys.exit(main())
