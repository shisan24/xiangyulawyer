#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Hermes Agent 健康检查脚本
检查项: (1) state.db integrity + WAL checkpoint
       (2) cron last_run_at 时效检查
       (3) Gateway 进程存活检查

使用方法:
    python healthcheck.py           # 标准检查
    python healthcheck.py --fix     # 自动修复可修复项
    python healthcheck.py --json    # JSON输出（供cron解析）
"""

import os
import sys
import json
import sqlite3
import subprocess
import datetime
from pathlib import Path

HERMES_DIR = Path(os.environ.get('HERMES_HOME', os.path.expandvars(r'%USERPROFILE%\.hermes')))
STATE_DB = HERMES_DIR / 'state.db'
CRON_TIMEOUT_MINUTES = 120  # cron任务超过此时间未执行视为停滞


def check_state_db(fix=False):
    """检查 state.db 完整性，优先尝试 WAL checkpoint"""
    results = {'ok': True, 'checks': [], 'errors': []}

    if not STATE_DB.exists():
        results['ok'] = False
        results['errors'].append(f"state.db 不存在: {STATE_DB}")
        return results

    conn = None
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.execute("PRAGMA journal_mode=WAL")

        # Step 1: WAL checkpoint (修复假性损坏)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            results['checks'].append("WAL checkpoint: ok")
        except sqlite3.Error as e:
            results['checks'].append(f"WAL checkpoint: failed ({e})")
            results['errors'].append(f"WAL checkpoint 失败: {e}")

        # Step 2: Integrity check
        try:
            cursor = conn.execute("PRAGMA integrity_check")
            row = cursor.fetchone()
            if row and row[0] == 'ok':
                results['checks'].append("integrity_check: ok")
            else:
                results['ok'] = False
                results['errors'].append(f"integrity_check: {row[0] if row else 'no result'}")
                if fix:
                    # 尝试修复：重建 state.db
                    _rebuild_state_db(conn)
                    results['checks'].append("integrity_check: 已重建")
                    results['ok'] = True
        except sqlite3.Error as e:
            results['ok'] = False
            results['errors'].append(f"integrity_check error: {e}")
            if fix:
                _rebuild_state_db(conn)
                results['checks'].append("integrity_check: 已重建数据库")
                results['ok'] = True

        # Step 3: 检查关键表是否存在
        tables = ['sessions', 'messages', 'memories', 'cron_jobs']
        for table in tables:
            try:
                conn.execute(f"SELECT COUNT(*) FROM {table}")
                results['checks'].append(f"table {table}: exists")
            except sqlite3.Error:
                results['ok'] = False
                results['errors'].append(f"table {table}: missing")

    except Exception as e:
        results['ok'] = False
        results['errors'].append(f"state.db 打开失败: {e}")
    finally:
        if conn:
            conn.close()

    return results


def _rebuild_state_db(conn):
    """备份损坏DB并创建新的"""
    backup_path = STATE_DB.with_suffix('.corrupted_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
    try:
        conn.close()
    except:
        pass
    import shutil
    shutil.copy2(STATE_DB, backup_path)
    print(f"  已备份损坏DB到: {backup_path}")
    # 创建全新DB
    STATE_DB.unlink(missing_ok=True)
    new_conn = sqlite3.connect(str(STATE_DB))
    new_conn.execute("PRAGMA journal_mode=WAL")
    new_conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, metadata TEXT);
        CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT, created_at TEXT, metadata TEXT);
        CREATE TABLE IF NOT EXISTS cron_jobs (id TEXT PRIMARY KEY, name TEXT, schedule TEXT, last_run_at TEXT, next_run_at TEXT, enabled INTEGER DEFAULT 1);
    """)
    new_conn.commit()
    new_conn.close()
    print(f"  已创建全新 state.db")


def check_cron_health():
    """检查 cron 任务的时效性"""
    results = {'ok': True, 'checks': [], 'errors': [], 'stalled_jobs': []}

    if not STATE_DB.exists():
        results['ok'] = False
        results['errors'].append("state.db 不存在，无法检查cron")
        return results

    conn = None
    try:
        conn = sqlite3.connect(str(STATE_DB))
        cursor = conn.execute(
            "SELECT id, name, last_run_at, next_run_at FROM cron_jobs WHERE enabled=1"
        )
        now = datetime.datetime.now(datetime.timezone.utc)

        for row in cursor.fetchall():
            job_id, name, last_run_at, next_run_at = row

            # 检查 next_run_at 是否过期
            if next_run_at:
                try:
                    next_run = datetime.datetime.fromisoformat(next_run_at.replace('Z', '+00:00'))
                    if next_run < now:
                        # 检查是否远超预期
                        delay = (now - next_run).total_seconds() / 60
                        if delay > CRON_TIMEOUT_MINUTES:
                            results['stalled_jobs'].append({
                                'id': job_id, 'name': name,
                                'next_run_at': next_run_at,
                                'delay_minutes': round(delay, 1)
                            })
                            results['errors'].append(
                                f"Cron停滞: {name} (next_run={next_run_at}, 延迟{delay:.0f}分钟)"
                            )
                            results['ok'] = False
                except (ValueError, TypeError):
                    results['errors'].append(f"Cron {name}: next_run_at 格式异常 ({next_run_at})")
                    results['ok'] = False
            else:
                results['stalled_jobs'].append({
                    'id': job_id, 'name': name,
                    'next_run_at': None,
                    'delay_minutes': None
                })
                results['errors'].append(f"Cron未初始化: {name} (next_run_at=null)")
                results['ok'] = False

            results['checks'].append(f"cron {name}: last={last_run_at}, next={next_run_at}")

    except Exception as e:
        results['ok'] = False
        results['errors'].append(f"cron检查异常: {e}")
    finally:
        if conn:
            conn.close()

    return results


def check_gateway_alive():
    """检查 Gateway 进程是否存活"""
    results = {'ok': True, 'checks': [], 'errors': []}

    try:
        # Windows: 检查 pythonw.exe 进程
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq pythonw.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=10
        )
        if 'pythonw.exe' in result.stdout:
            results['checks'].append("Gateway进程: pythonw.exe 运行中")
        else:
            results['ok'] = False
            results['errors'].append("Gateway进程: pythonw.exe 未找到")
    except Exception as e:
        results['ok'] = False
        results['errors'].append(f"Gateway检查异常: {e}")

    return results


def run_all_checks(fix=False):
    """运行所有健康检查"""
    all_results = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'ok': True,
        'state_db': check_state_db(fix=fix),
        'cron': check_cron_health(),
        'gateway': check_gateway_alive(),
    }

    # 汇总状态
    all_results['ok'] = all(
        all_results[k]['ok'] for k in ['state_db', 'cron', 'gateway']
        if k in all_results and isinstance(all_results[k], dict)
    )

    total_errors = sum(
        len(all_results[k].get('errors', []))
        for k in ['state_db', 'cron', 'gateway']
        if k in all_results and isinstance(all_results[k], dict)
    )
    all_results['total_errors'] = total_errors

    return all_results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Hermes Agent 健康检查')
    parser.add_argument('--fix', action='store_true', help='自动修复可修复项')
    parser.add_argument('--json', action='store_true', help='JSON格式输出')
    args = parser.parse_args()

    results = run_all_checks(fix=args.fix)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Hermes Agent 健康检查")
        print(f"时间: {results['timestamp']}")
        print("=" * 60)

        for section, title in [('state_db', 'State DB'), ('cron', 'Cron 调度'), ('gateway', 'Gateway 进程')]:
            sec = results[section]
            status = "✅ OK" if sec['ok'] else "❌ FAIL"
            print(f"\n[{title}] {status}")
            for check in sec.get('checks', []):
                print(f"  • {check}")
            for err in sec.get('errors', []):
                print(f"  ⚠ {err}")

        print("\n" + "=" * 60)
        if results['ok']:
            print("总体状态: ✅ 一切正常")
        else:
            print(f"总体状态: ❌ 发现 {results['total_errors']} 个问题")
            if args.fix:
                print("已尝试自动修复，请重新运行验证")
            else:
                print("建议运行 python healthcheck.py --fix 自动修复")

    sys.exit(0 if results['ok'] else 1)


if __name__ == '__main__':
    main()
