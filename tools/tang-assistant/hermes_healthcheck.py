# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Hermes 健康检查脚本 v1.0
运行: python hermes_healthcheck.py --full
"""
import os, sys, datetime, json

SYNC_DIR = r"[本地路径]"
HERMES_HOME = os.path.expanduser(r"[本地路径]")
SKILLS_DIR = os.path.join(SYNC_DIR, "skills")

results = {"status": "OK", "checks": []}

def check(name, condition, detail=""):
    if condition:
        results["checks"].append({"name": name, "status": "✓", "detail": detail})
        return True
    else:
        results["checks"].append({"name": name, "status": "✗", "detail": detail})
        results["status"] = "ISSUES"
        return False

# 1. 目录
check("本机目录", os.path.isdir(SYNC_DIR))
check(".hermes", os.path.isdir(HERMES_HOME))

# 2. state.db
state = os.path.join(SYNC_DIR, "state.db")
if os.path.exists(state):
    size_mb = os.path.getsize(state) // (1024*1024)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(state))
    age_h = (datetime.datetime.now() - mtime).total_seconds() / 3600
    check("state.db", True, f"{size_mb}MB, {age_h:.1f}h ago")
else:
    check("state.db", False, "NOT FOUND")

# 3. 技能
if os.path.isdir(SKILLS_DIR):
    n = len([d for d in os.listdir(SKILLS_DIR) if not d.startswith('.') and os.path.isdir(os.path.join(SKILLS_DIR, d))])
    check("技能", n > 30, f"{n} skills")

# 4. 备份
backups = [f for f in os.listdir(SYNC_DIR) if f.startswith("skills-backup-") and f.endswith(".tar.gz")]
if backups:
    latest = sorted(backups)[-1]
    bp = os.path.join(SYNC_DIR, latest)
    age_h = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(bp))).total_seconds() / 3600
    check("备份", age_h < 48, f"{latest} ({age_h:.1f}h)")

# 5. 机器标记（合并各机器独立文件）
import glob as _glob
marker_files = sorted(_glob.glob(os.path.join(SYNC_DIR, ".machine_marker.*.json")))
peers = {}
for mf in marker_files:
    try:
        with open(mf, "r", encoding="utf-8") as f:
            d = json.load(f)
        host = d.get("hostname", os.path.splitext(os.path.basename(mf))[0].replace(".machine_marker.", ""))
        peers[host] = d
    except:
        pass

# 写出合并后的 marker（向下兼容旧脚本）
merged_marker = os.path.join(SYNC_DIR, ".machine_marker.json")
merged = {"peers": peers, "peers_count": len(peers), "updated": datetime.datetime.now().isoformat()}
with open(merged_marker, "w", encoding="utf-8") as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)

if peers:
    hosts = ", ".join(f"{h}({d.get('display_name','?')})" for h, d in peers.items())
    check("标记", len(peers) >= 1, f"{len(peers)}台: {hosts}")
else:
    check("标记", False, "no machine markers found")

# 6. 第三方同步盘 (通过同步目录 mtime)
sync_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(SYNC_DIR))
sync_age_h = (datetime.datetime.now() - sync_mtime).total_seconds() / 3600
check("第三方同步盘同步", sync_age_h < 24, f"last sync {sync_age_h:.1f}h ago")

# 7. config
check("config.yaml", os.path.exists(os.path.join(HERMES_HOME, "config.yaml")))

# 输出
if __name__ == "__main__":
    full = "--full" in sys.argv
    if full or results["status"] == "ISSUES":
        print(f"\n  Hermes Health — {datetime.datetime.now():%m-%d %H:%M}")
        print(f"  {'─'*40}")
        for c in results["checks"]:
            print(f"  [{c['status']}] {c['name']}: {c['detail']}")
        print(f"  {'─'*40}")
        print(f"  {'ALL OK' if results['status'] == 'OK' else 'ISSUES FOUND'}\n")

    # 失败时写标记文件
    if results["status"] == "ISSUES":
        alert_file = os.path.join(SYNC_DIR, ".healthcheck_alert")
        with open(alert_file, "w") as f:
            json.dump({"time": datetime.datetime.now().isoformat(), "issues": [
                c for c in results["checks"] if c["status"] != "✓"
            ]}, f, ensure_ascii=False, indent=2)
    else:
        alert_file = os.path.join(SYNC_DIR, ".healthcheck_alert")
        if os.path.exists(alert_file):
            os.remove(alert_file)

    sys.exit(0 if results["status"] == "OK" else 1)
