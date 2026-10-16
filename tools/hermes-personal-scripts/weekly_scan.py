#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""周报发现材料：上一个自然周，交付事件与修改线索分开。

默认只读取源；不把文件名、mtime、生成动作当完成。缺源明确partial。
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from lawyer_ops import file_changes
from lawyer_quality_state import ITEMS_FILE, DATA_DIR, atomic_json, inspect_receipt, load_items, read_object

TZ=timezone(timedelta(hours=8))

def build_report(home, now=None, state_file=ITEMS_FILE, mail_root=None):
    home=Path(home);now=now or datetime.now(TZ)
    end=now.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=now.weekday())
    start=end-timedelta(days=7)
    cfg=read_object(home/'lawyer-workbench.json')
    roots=cfg.get('case_roots')
    if not isinstance(roots,list) or not roots:raise ValueError('未配置案件根目录')
    discovered=file_changes(roots,max(7,(now-start).total_seconds()/86400),max_depth=12)
    leads=[x for x in discovered['files'] if start.timestamp()<=datetime.fromisoformat(x['modified_at']).timestamp()<end.timestamp()]
    report={'schema':'weekly-evidence/v2','window':{'start':start.date().isoformat(),'end_inclusive':(end-timedelta(days=1)).date().isoformat(),'timezone':'Asia/Shanghai'},
            'scope_roots':roots,'confirmed_deliveries':[],'historical_delivery_claims':[],
            'file_leads':leads,'message_leads':[],'persistent_unresolved':[],
            'mail_pending':[],'sources':{},'coverage_issues':list(discovered['coverage_issues']),
            'rules':'文件/会话检索均为线索；未核交付不进成果，解压/归档不算新编制；本机交付不等于对外送达'}
    for key in ('todo_file','deadline_file'):
        p=Path(cfg.get(key) or '')
        try:report['sources'][key]={'path':str(p),'text':p.read_text(encoding='utf-8-sig'),'modified_at':datetime.fromtimestamp(p.stat().st_mtime,TZ).isoformat(),'meaning':'源内容适用时点须阅读确认，mtime不证明业务已更新'}
        except (OSError,UnicodeError) as exc:report['coverage_issues'].append(f'{key}读取失败：{type(exc).__name__}')
    try:
        state=load_items(state_file)
        report['persistent_unresolved']=[x for x in state['items'].values() if x.get('status') not in {'completed','cancelled'}]
        if not Path(state_file).exists():report['coverage_issues'].append('逐件状态尚未建立，不能据空库认定全部办结')
        for x in state['items'].values():
            if x.get('status')=='completed' and x.get('completed_at'):
                d=datetime.fromisoformat(x['completed_at'])
                if start.timestamp()<=d.timestamp()<end.timestamp():report['confirmed_deliveries'].append(x)
    except (OSError,ValueError,TypeError) as exc:report['coverage_issues'].append('逐件状态不可用：'+str(exc))
    try:
        mail=read_object(home/'scripts/mail/state.json')
        for folder,entry in mail.items():
            if isinstance(entry,dict):report['mail_pending'] += [{**x,'folder':folder,'meaning':'扫描/提醒与附件完成分开'} for x in entry.get('pending',[]) if isinstance(x,dict)]
    except (OSError,ValueError) as exc:report['coverage_issues'].append('邮件pending未覆盖：'+type(exc).__name__)
    mail_root=Path(mail_root or '[本地路径]')
    if mail_root.is_dir():
        for folder in mail_root.iterdir():
            if not folder.is_dir():continue
            try:
                rec=inspect_receipt(folder)
                if rec.get('handled_at'):
                    d=datetime.fromisoformat(rec['handled_at'])
                    if start.timestamp()<=d.timestamp()<end.timestamp():
                        target='confirmed_deliveries' if rec.get('status')=='completed' and rec['version_state']=='current_version_matched' else 'historical_delivery_claims'
                        report[target].append(rec)
            except (OSError,ValueError,TypeError) as exc:report['coverage_issues'].append(f'回执未核：{folder}：{type(exc).__name__}')
    else:report['coverage_issues'].append('邮件附件目录未覆盖')
    db=home/'state.db'
    try:
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as conn:
            rows=conn.execute("SELECT id,session_id,timestamp,content FROM messages WHERE timestamp>=? AND timestamp<? AND role='assistant' AND (content LIKE '%MEDIA:%' OR content LIKE '%已交付%' OR content LIKE '%已完成%') ORDER BY timestamp DESC LIMIT 501",(start.timestamp(),end.timestamp())).fetchall()
        report['message_leads']=[{'message_id':i,'session_id':s,'at':datetime.fromtimestamp(t,TZ).isoformat(),'excerpt':str(c or '')[:1800],'meaning':'交付陈述候选，需回精确会话核业务身份与最终状态'} for i,s,t,c in rows[:500]]
        if len(rows)>500:report['coverage_issues'].append('交付陈述线索超过500项，仅首500项；需专项补检')
    except (OSError,sqlite3.Error) as exc:report['coverage_issues'].append('会话交付线索未覆盖：'+type(exc).__name__)
    report['coverage']='partial' if report['coverage_issues'] else 'discovery_complete_not_business_verification'
    return report

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true')
    a=ap.parse_args(argv)
    try:
        home=Path(os.environ.get('HERMES_HOME') or Path.home()/'AppData/Local/hermes')
        report=build_report(home)
        if a.preview:print(json.dumps(report,ensure_ascii=False,indent=2));return 0
        path=DATA_DIR/'weekly-inventory'/f'{datetime.now(TZ):%Y%m%d-%H%M%S}-{os.getpid()}.json'
        atomic_json(path,report)
        bounded={**report,'file_leads':report['file_leads'][:100],'message_leads':report['message_leads'][:50],
                 'file_lead_count':len(report['file_leads']),'message_lead_count':len(report['message_leads']),
                 'complete_inventory':str(path)}
        print(json.dumps(bounded,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,sqlite3.Error) as exc:
        print('周报发现失败，不能认定没有成果或待办：'+str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
