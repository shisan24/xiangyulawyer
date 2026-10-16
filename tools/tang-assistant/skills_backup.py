# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
每日技能备份脚本
- 检查 【本机标识】/skills 是否有变化
- 有变化则创建 tar.gz 备份（含机器标记）
- 保留最近 7 个备份，自动清理旧的
"""
import os, tarfile, datetime, glob, hashlib, socket, json, re

# Use 【本机标识】 as sync root (not script dir, since script may be symlinked/copied)
SYNC_DIR = os.path.join(os.path.expanduser("~"), "【本机标识】")
SKILLS_DIR = os.path.join(SYNC_DIR, "skills")
# Fallback: if 【本机标识】 doesn't exist, use [本地路径]
if not os.path.isdir(SKILLS_DIR):
    SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".hermes", "skills")
if not os.path.isdir(SYNC_DIR):
    SYNC_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_PREFIX = "skills-backup-"
MAX_BACKUPS = 7
HOSTNAME = socket.gethostname()

def update_machine_marker():
    """更新机器标记 — 委托给 machine_detect.py（统一入口）"""
    import subprocess
    detect_script = os.path.join(SYNC_DIR, "machine_detect.py")
    if os.path.exists(detect_script):
        subprocess.run(["python3", detect_script], capture_output=True, timeout=10)
    else:
        # fallback: minimal marker
        marker = {
            "hostname": HOSTNAME,
            "last_active": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_backup": None,
        }
        with open(os.path.join(SYNC_DIR, ".machine_marker.json"), "w", encoding="utf-8") as f:
            json.dump(marker, f, ensure_ascii=False, indent=2)

def get_skills_hash():
    hasher = hashlib.md5()
    for root, dirs, files in os.walk(SKILLS_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for f in sorted(files):
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, SKILLS_DIR)
            hasher.update(rel.encode())
            hasher.update(str(os.path.getmtime(fp)).encode())
    return hasher.hexdigest()

def get_latest_backup_hash():
    hash_file = os.path.join(SYNC_DIR, ".backup_hash")
    if os.path.exists(hash_file):
        with open(hash_file, "r") as f:
            return f.read().strip()
    return ""

def create_backup():
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    short_host = HOSTNAME.replace(" ", "-")[:20]
    name = f"{BACKUP_PREFIX}{timestamp}-{short_host}.tar.gz"
    path = os.path.join(SYNC_DIR, name)
    file_count = 0
    with tarfile.open(path, "w:gz") as tar:
        for root, dirs, files in os.walk(SKILLS_DIR):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, SKILLS_DIR)
                tar.add(full, arcname=rel)
                file_count += 1
    size_kb = os.path.getsize(path) // 1024
    return name, file_count, size_kb


def track_versions(backup_name):
    """记录每个技能的 SKILL.md 前 3 行（name + version），用于版本追踪"""
    versions = {"_backup": backup_name, "_time": datetime.datetime.now().isoformat()}
    skills_dir = SKILLS_DIR
    for root, dirs, files in os.walk(skills_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        if "SKILL.md" in files:
            md = os.path.join(root, "SKILL.md")
            try:
                with open(md, "r", encoding="utf-8") as f:
                    head = "".join(f.readlines()[:5])
                # Extract name and version from YAML frontmatter
                name_match = re.search(r"name:\s*(.+)", head)
                ver_match = re.search(r"version:\s*(.+)", head)
                skill_name = name_match.group(1).strip() if name_match else os.path.basename(root)
                skill_ver = ver_match.group(1).strip() if ver_match else "?"
                rel = os.path.relpath(root, skills_dir)
                versions[rel] = {"name": skill_name, "version": skill_ver}
            except:
                pass
    # Write versions file
    vpath = os.path.join(SYNC_DIR, "skills_versions.json")
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False, indent=2)
    return vpath


def rotate_backups():
    backups = sorted(glob.glob(os.path.join(SYNC_DIR, f"{BACKUP_PREFIX}*.tar.gz")))
    if len(backups) > MAX_BACKUPS:
        for old in backups[:-MAX_BACKUPS]:
            os.remove(old)
            print(f"  Removed old: {os.path.basename(old)}")

if __name__ == "__main__":
    update_machine_marker()
    current_hash = get_skills_hash()
    latest_hash = get_latest_backup_hash()
    if current_hash == latest_hash:
        print(f"[{datetime.datetime.now():%H:%M:%S}] [{HOSTNAME}] No changes, skipping")
    else:
        name, files, size = create_backup()
        with open(os.path.join(SYNC_DIR, ".backup_hash"), "w") as f:
            f.write(current_hash)
        rotate_backups()
        print(f"[{datetime.datetime.now():%H:%M:%S}] [{HOSTNAME}] Backup: {name} ({files} files, {size}KB)")
    track_versions(name)
