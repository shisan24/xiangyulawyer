#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""版本绑定回执；completed必须提供当前通过的门禁记录。

不发送客户，不把旧回执当新版本验收。partial只写断点，不表示完成。
非零表示未登记，必须保留失败。--preview只读，不改任何回执或状态。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lawyer_quality_state import atomic_json, file_lock, validate_gate

CN_TZ = timezone(timedelta(hours=8))

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="邮件附件目录")
    ap.add_argument("--status", default="completed", choices=["completed", "declined", "partial"])
    ap.add_argument("--note", required=True, help="本机交付摘要或未完步骤；不能代表对外发送")
    ap.add_argument("--gate", type=Path, help="completed必须指定当前门禁JSON")
    ap.add_argument("--resume", default="", help="partial的下一步与断点")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.folder).expanduser().resolve()
    try:
        if not folder.is_dir():raise ValueError(f"目录不存在：{folder}")
        if a.status=="completed" and not a.gate:raise ValueError("completed必须提供--gate；不得仅凭生成文件记完成")
        if a.status=="partial" and not a.resume:raise ValueError("partial必须提供--resume，保留可接续断点")
        bound=validate_gate(a.gate,folder) if a.status=="completed" else None
        if bound and {x['role'] for x in bound['artifacts']}!={'path','expected','ledger'}:
            raise ValueError("完成回执必须绑定修订/批注版、净版基线与台账三件套")
        rec={"schema":"mail-handled/v2", "handled_at":datetime.now(CN_TZ).isoformat(timespec="seconds"),
             "status":a.status,"note":a.note,"by":"hermes-cron","resume":a.resume,
             "version_evidence":bound,"stage":"local_delivered" if bound else "in_progress",
             "external_delivery_verified":False}
        if a.preview:print(json.dumps(rec,ensure_ascii=False,indent=2));return 0
        p=folder/"_处理回执.json"
        with file_lock(folder/".handled.lock"):
            if p.exists():
                old=p.read_bytes()
                history=folder/"_回执历史";history.mkdir(exist_ok=True)
                from time import time_ns
                (history/f"处理回执-{time_ns()}.json").write_bytes(old)
            atomic_json(p,rec)
        print(f"OK 本机处理回执已写，未对外发送：{p}");return 0
    except (OSError,ValueError,TypeError) as exc:
        print(f"处理回执未登记：{exc}",file=sys.stderr);return 2

if __name__=="__main__":sys.exit(main())
