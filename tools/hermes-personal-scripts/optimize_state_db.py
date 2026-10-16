# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""独占窗口维护：重建 state.db 的全文检索索引并回收空间。

背景（为什么必须独占窗口）
- 本命令（hermes sessions optimize-storage）在重建索引后执行 VACUUM；
  VACUUM 对整库加**独占锁**。
- 若有其他 Hermes 写入方（gateway / 桌面端 / dashboard / cron）在跑，双方互相阻塞；
  本机历史上出现过「VACUUM 锁死 gateway 的 DB 连接 → gateway 崩溃 → 桌面端断连」的事故。
- 官方也警告：在有活跃写入方时重写检索存储，可能让所有 agent 拒绝应答，直到写入方全部停止。

用法
    python optimize_state_db.py --check       # 只做前置检查，不写、不改（随时可跑）
    python optimize_state_db.py               # 正式执行（请先**完全退出** Hermes）
    python optimize_state_db.py --no-vacuum   # 重建索引但不做最终 VACUUM（空间稍后才回收）
    python optimize_state_db.py --skip-backup # 跳过开工前的整库备份（不推荐）

退出码
    0 成功
    2 前置检查不通过（有活跃写入方或库被占用）——什么都没改
    3 执行 hermes sessions optimize-storage 失败
    4 复核不通过（完整性/计数/检索自检）
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

LOG_HANDLE = None


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if LOG_HANDLE:
        LOG_HANDLE.write(line + "\n")
        LOG_HANDLE.flush()


def resolve_home() -> pathlib.Path:
    """认 HERMES_HOME，其次脚本所在目录的上一级，最后才回退 LOCALAPPDATA（换 profile 不能清错库）。"""
    env = os.environ.get("HERMES_HOME")
    if env and (pathlib.Path(env) / "config.yaml").exists():
        return pathlib.Path(env)
    here = pathlib.Path(__file__).resolve().parent          # <home>/scripts
    if (here.parent / "config.yaml").exists():
        return here.parent
    cand = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"
    if (cand / "config.yaml").exists():
        return cand
    raise SystemExit("无法定位 HERMES_HOME：未设置环境变量，且脚本不在 <home>/scripts 下")


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _powershell(script: str) -> tuple[int, str, str]:
    """用 -EncodedCommand 传脚本。

    用清单方式（["powershell","-Command",script]）传含 {} / $_ 的脚本会被解析失败
    （实测 rc=1、stdout 为空）——那正是「探针失效却当成通过」的坑，必须用 base64 免疫引号与转义。
    """
    import base64

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", encoded],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, stdin=subprocess.DEVNULL)
    return proc.returncode, proc.stdout, proc.stderr


def live_writers() -> list[str]:
    """列出可能持有 state.db 的 Hermes 进程。

    fail-closed：探针本身失败（执行异常或非零退出）时返回 `<…>` 哨兵项，
    由调用方按「未确认＝未通过」处理，绝不放行。
    """
    script = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -eq 'Hermes.exe' -or $_.Name -eq 'hermes.exe' -or "
        "($_.Name -eq 'python.exe' -and $_.CommandLine -match 'gateway|serve|dashboard') "
        "} | ForEach-Object { '{0} {1} {2}' -f $_.ProcessId, $_.Name, $_.CommandLine }"
    )
    try:
        rc, out, err = _powershell(script)
    except Exception as exc:                       # 探针失败 ≠ 通过
        return [f"<进程探针无法执行：{exc!r}——按未确认处理>"]
    if rc != 0:
        return [f"<进程探针返回码 {rc}，输出不可用——按未确认处理> {err.strip()[:120]}"]
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def rename_probe(path: pathlib.Path) -> str | None:
    """决定性闸门：Windows 上只要还有进程打开该文件（未共享删除），改名就会失败。

    比「看有没有进程」更硬——SQLite 是按需打开文件的，进程活着不代表此刻持有，
    反之文件被占用则一定有写入方。返回 None 表示未被占用。
    """
    if not path.exists():
        return None
    tmp = path.with_name(path.name + ".hermesprobe")
    try:
        os.replace(path, tmp)
    except OSError as exc:
        return f"{path.name} 仍被进程占用（{type(exc).__name__}: {exc}）"
    try:
        os.replace(tmp, path)
    except OSError as exc:
        return f"{path.name} 探针改名成功但复原失败（{exc}）——请手工把 {tmp.name} 改回原名"
    return None


def exclusive_probe(db: pathlib.Path) -> str | None:
    """决定性闸门：能否拿到独占锁。返回 None 表示可写，否则返回原因。"""
    try:
        con = sqlite3.connect(str(db), timeout=3, isolation_level=None)
    except sqlite3.Error as exc:
        return f"无法打开数据库：{exc}"
    try:
        con.execute("BEGIN EXCLUSIVE")
        con.execute("ROLLBACK")
        return None
    except sqlite3.Error as exc:
        return f"数据库仍被占用（{exc}）"
    finally:
        con.close()


def db_stats(db: pathlib.Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        cur = con.cursor()
        stats = {"size": db.stat().st_size}
        for name, sql in (("sessions", "SELECT count(*) FROM sessions"),
                          ("messages", "SELECT count(*) FROM messages")):
            try:
                stats[name] = cur.execute(sql).fetchone()[0]
            except sqlite3.Error as exc:
                stats[name] = f"查询失败:{exc}"
        return stats
    finally:
        con.close()


def integrity(db: pathlib.Path) -> str:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return str(con.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        con.close()


def fts_smoke(db: pathlib.Path) -> str:
    """检索自检：新索引必须能查得到东西，否则「重建成功」只是文件变小。"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        cur = con.cursor()
        for table in ("messages_fts", "messages_fts_trigram"):
            try:
                n = cur.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH 'hermes'").fetchone()[0]
                return f"{table}: MATCH 'hermes' → {n} 条"
            except sqlite3.Error:
                continue
        return "检索自检失败：没有可用的 FTS 表能执行 MATCH"
    finally:
        con.close()


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    global LOG_HANDLE
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", action="store_true", help="只做前置检查，不改动任何文件")
    ap.add_argument("--no-vacuum", action="store_true", help="跳过最终 VACUUM")
    ap.add_argument("--skip-backup", action="store_true", help="跳过开工前整库备份")
    args = ap.parse_args()

    home = resolve_home()
    db = home / "state.db"
    logdir = home / "logs"
    logdir.mkdir(exist_ok=True)
    LOG_HANDLE = open(logdir / "optimize_state_db.log", "a", encoding="utf-8")

    log("=" * 60)
    log(f"HERMES_HOME = {home}")
    log(f"state.db    = {db}  ({human(db.stat().st_size) if db.exists() else '不存在'})")
    if not db.exists():
        log("！state.db 不存在，退出")
        return 2

    try:
        enabled = re.search(r"sessions:", (home / "config.yaml").read_text(encoding="utf-8", errors="replace")) is not None
        log(f"config.yaml 中 sessions 段：{'存在' if enabled else '未见'}")
    except OSError as exc:
        log(f"读取 config.yaml 失败：{exc}")

    # ---------- 前置检查（fail-closed：未确认＝未通过） ----------
    log("—— 前置检查 ——")
    occupied = None
    for target in (db, pathlib.Path(str(db) + "-wal"), pathlib.Path(str(db) + "-shm")):
        occupied = rename_probe(target)
        if occupied:
            break
    if occupied:
        log(f"！{occupied}")
        log("说明仍有 Hermes 进程打开 state.db（桌面端 / gateway / cron 任一在跑）。")
        log("请**完全退出 Hermes** 后重跑；本次未改动任何文件。")
        return 2
    log("文件占用探针：state.db / -wal / -shm 均未被占用（决定性判据）")

    procs = live_writers()
    if procs:
        log(f"！发现 {len(procs)} 个可能的写入方（含未确认项一律按不通过处理）：")
        for p in procs[:10]:
            log(f"    {p[:170]}")
        log("请在**完全退出 Hermes**（桌面端、gateway、cron 全部停）后重跑本脚本。")
        log("（本次未改动任何文件）")
        return 2
    log("进程探针：无 Hermes 进程")

    reason = exclusive_probe(db)
    log("独占锁探针：" + (reason if reason else "通过（当前无写入方；仅供参考）"))

    before = db_stats(db)
    log(f"开工前：state.db={human(before['size'])}  sessions={before['sessions']}  messages={before['messages']}")

    if args.check:
        log("--check：检查全部通过，未做任何改动。正式执行请去掉 --check。")
        return 0

    # ---------- 备份 ----------
    if args.skip_backup:
        log("！按参数跳过备份")
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bdir = home / "backups" / f"state-db-{stamp}"
        bdir.mkdir(parents=True, exist_ok=True)
        log(f"备份到 {bdir}")
        try:
            con = sqlite3.connect(str(db), timeout=30, isolation_level=None)
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # 先把 WAL 落进主库，备份才自洽
            con.close()
            for suffix in ("", "-wal", "-shm"):
                src = pathlib.Path(str(db) + suffix)
                if src.exists():
                    shutil.copy2(src, bdir / src.name)
                    log(f"  已复制 {src.name}  {human(src.stat().st_size)}")
            digest = sha256(db)
            (bdir / "state.db.sha256").write_text(digest + "\n", encoding="utf-8")
            log(f"  备份 sha256 = {digest}")
        except Exception as exc:
            log(f"！备份失败，中止（不在没有备份的情况下动库）：{exc!r}")
            return 3

    # ---------- 执行 ----------
    hermes = home / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"
    if not hermes.exists():
        log(f"！找不到 CLI：{hermes}")
        return 3
    cmd = [str(hermes), "sessions", "optimize-storage", "--yes"]
    if args.no_vacuum:
        cmd.append("--no-vacuum")
    log("执行：" + " ".join(cmd))
    t0 = datetime.datetime.now()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log("  | " + line[:300])
    rc = proc.wait()
    log(f"子进程退出码 = {rc}（耗时 {(datetime.datetime.now() - t0).seconds}s）")
    if rc != 0:
        log("！执行失败。库可回滚：备份目录内为整库副本，覆盖回 state.db 即可（覆盖前先停 Hermes）。")
        return 3

    # ---------- 复核 ----------
    after = db_stats(db)
    log(f"完工后：state.db={human(after['size'])}  sessions={after['sessions']}  messages={after['messages']}")
    log(f"回收空间：{human(max(0, before['size'] - after['size']))}")
    ok = True
    if after["sessions"] != before["sessions"] or after["messages"] != before["messages"]:
        log("！会话/消息计数发生变化——不应发生，请人工核对")
        ok = False
    chk = integrity(db)
    log(f"quick_check = {chk}")
    if chk != "ok":
        ok = False
    smoke = fts_smoke(db)
    log("检索自检：" + smoke)
    if "失败" in smoke or "→ 0 条" in smoke:
        log("！检索自检未通过（索引重建后必须能命中）")
        ok = False
    if not ok:
        log("！复核不通过，请按备份回滚或人工检查")
        return 4
    log("完成：索引已重建，空间已回收，数据未变。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断：可安全重跑（命令本身支持断点续跑）")
        sys.exit(3)
