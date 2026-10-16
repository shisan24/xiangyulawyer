# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""把每日待办提要写入看板《待办提要》(daily-digest)。

用法: python digest_to_kanban.py [提要 md 路径]
默认读取: <hermes home>\cron\output\_digest_latest.md
幂等: 同日一张卡（idempotency-key=digest-YYYY-MM-DD），重复运行不重复建卡。
"""
import subprocess, sys, re, pathlib, datetime

HERMES = pathlib.Path(r'[本地路径]')
HERMES_EXE = HERMES / 'hermes-agent' / 'venv' / 'Scripts' / 'hermes.exe'
BOARD = 'daily-digest'
DEFAULT_IN = HERMES / 'cron' / 'output' / '_digest_latest.md'


def main():
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IN
    if not src.exists():
        print('[skip] 输入不存在:', src)
        return 1
    text = src.read_text(encoding='utf-8').strip()
    if not text:
        print('[skip] 输入为空')
        return 1
    m = re.search(r'待办提要（(\d{4}-\d{2}-\d{2})）', text)
    date = m.group(1) if m else datetime.date.today().isoformat()
    title = f'待办提要 {date}'
    key = f'digest-{date}'
    cmd = [str(HERMES_EXE), 'kanban', '--board', BOARD, 'create', title,
           '--body', text, '--idempotency-key', key, '--created-by', 'Hermes·待办提要', '--json']
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    print('exit:', r.returncode)
    if (r.stdout or '').strip():
        print('stdout:', r.stdout.strip()[:600])
    if (r.stderr or '').strip():
        print('stderr:', r.stderr.strip()[:600])
    return r.returncode


if __name__ == '__main__':
    raise SystemExit(main())
