# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Evidence-bound shared cron work state. Runtime data is on D, not in memory.

This module verifies provenance and version identity, not legal merits. An
omitted item stays unresolved. A local receipt is not customer acceptance or
external delivery. All read/parse errors remain errors.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

TZ=timezone(timedelta(hours=8))
DATA_DIR=Path(os.environ.get('LAWYER_QUALITY_DIR','[本地路径]'))
ITEMS_FILE=DATA_DIR/'work-items.json'
STATUSES={'pending','in_progress','waiting','conflict','completed','cancelled'}
CLOSING_EVIDENCE={'delivery_message','user_confirmation','receipt'}


def stamp():return datetime.now(TZ).isoformat(timespec='seconds')

def read_object(path, *, missing=None):
    try:data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        if missing is not None:return missing
        raise
    if not isinstance(data,dict):raise ValueError(f'JSON object required: {path}')
    return data


@contextmanager
def file_lock(path, timeout=15):
    """OS-owned lock; a process exit releases it. No stale-file deletion."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    f=open(path,'a+b')
    if f.seek(0,2)==0:f.write(b'0');f.flush()
    deadline=time.monotonic()+timeout
    try:
        while True:
            f.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except (OSError,BlockingIOError):
                if time.monotonic()>=deadline:raise TimeoutError(f'State writer busy: {path}')
                time.sleep(0.05)
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
    finally:f.close()


def atomic_json(path, data, retries=4):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with tmp.open('x',encoding='utf-8',newline='\n') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        for n in range(retries+1):
            try:os.replace(tmp,path);break
            except PermissionError:
                if n==retries:raise
                time.sleep(0.05*(n+1))
    finally:
        if tmp.exists():tmp.unlink()


def verify_evidence(evidence, home=None):
    if not isinstance(evidence,dict) or not evidence.get('quote'):raise ValueError('Evidence quote required')
    if evidence.get('path'):
        p=Path(evidence['path'])
        if p.name.lower() in {'.env','auth.json','config.yaml'}:raise ValueError('Credential/config file is not work evidence')
        content=p.read_text(encoding='utf-8-sig')
    elif evidence.get('session_id') and evidence.get('message_id'):
        home=Path(home or os.environ['HERMES_HOME'])
        with sqlite3.connect((home/'state.db').resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            row=db.execute('SELECT content FROM messages WHERE id=? AND session_id=?',(evidence['message_id'],evidence['session_id'])).fetchone()
        if row is None:raise ValueError('Evidence message not found in exact session')
        content=str(row[0] or '')
    else:raise ValueError('Evidence needs exact path or session/message IDs')
    if str(evidence['quote']) not in content:raise ValueError('Evidence quote not found in source')
    return {**evidence,'checked_at':stamp(),'source_sha256':hashlib.sha256(content.encode('utf-8')).hexdigest()}


def load_items(path=ITEMS_FILE):
    data=read_object(path,missing={'schema':'cron-work-items/v1','revision':0,'items':{}})
    if data.get('schema')!='cron-work-items/v1' or not isinstance(data.get('items'),dict):raise ValueError('Invalid work state schema')
    return data


def merge_items(path, updates):
    if not isinstance(updates,list):raise ValueError('Updates must be a list; omitted items are retained')
    verified=[]
    for item in updates:
        if not isinstance(item,dict) or not item.get('id') or not item.get('title') or item.get('status') not in STATUSES:raise ValueError('Invalid work item')
        evidence=item.get('evidence')
        if not isinstance(evidence,list) or not evidence:raise ValueError('Every work item needs source evidence')
        evidence=[verify_evidence(e) for e in evidence]
        if item['status'] in {'completed','cancelled'} and not any(e.get('type') in CLOSING_EVIDENCE for e in evidence):
            raise ValueError('Completion/cancellation needs delivery, user confirmation or receipt evidence')
        verified.append({**item,'evidence':evidence})
    path=Path(path)
    with file_lock(path.with_suffix('.lock')):
        data=load_items(path)
        for item in verified:
            previous=data['items'].get(item['id'],{})
            history=list(previous.get('history',[]))
            if previous:history.append({k:v for k,v in previous.items() if k!='history'})
            data['items'][item['id']]={**previous,**item,'history':history,'updated_at':stamp()}
        data['revision']=int(data.get('revision',0))+1;data['updated_at']=stamp()
        atomic_json(path,data)
    return data


def validate_gate(gate_path, folder):
    """Bind the recorded engineering check to the current artifact bytes.

    This does not independently re-run legal review or declare customer receipt.
    """
    folder=Path(folder).resolve();gate_path=Path(gate_path).resolve()
    if not gate_path.is_relative_to(folder):raise ValueError('Gate outside attachment folder')
    gate=read_object(gate_path)
    if gate.get('ok') is not True or not gate.get('sha256') or not gate.get('path'):raise ValueError('Gate not passed or not bound to an artifact')
    if any(c.get('status')=='fail' for c in gate.get('checks',[]) if isinstance(c,dict)):raise ValueError('Gate contains failed checks')
    artifacts=[]
    for key in ('path','expected','ledger'):
        if not gate.get(key):continue
        p=Path(gate[key]).resolve()
        if not p.is_relative_to(folder) or not p.is_file():raise ValueError('Artifact missing or outside attachment folder')
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if key=='path' and digest!=gate['sha256']:raise ValueError('Artifact changed since gate; preserve user version')
        artifacts.append({'role':key,'path':str(p),'sha256':digest})
    return {'gate_path':str(gate_path),'gate_sha256':hashlib.sha256(gate_path.read_bytes()).hexdigest(),'artifacts':artifacts}


def inspect_receipt(folder):
    folder=Path(folder)
    p=folder/'_处理回执.json'
    if not p.is_file():return {'folder':str(folder),'status':'not_completed','version_state':'no_receipt'}
    rec=read_object(p)
    result={'folder':str(folder),'receipt_path':str(p),'status':rec.get('status'),
            'handled_at':rec.get('handled_at'),'note':rec.get('note',''),
            'resume':rec.get('resume',''),'stage':rec.get('stage'),
            'version_state':'historical_unbound','external_delivery_verified':False}
    bound=rec.get('version_evidence')
    if bound:
        if not isinstance(bound,dict) or not isinstance(bound.get('artifacts'),list) or not bound['artifacts']:
            raise ValueError('Invalid version evidence')
        for item in bound['artifacts']:
            artifact=Path(item['path']).resolve()
            if not artifact.is_relative_to(folder.resolve()):
                raise ValueError('Receipt artifact outside attachment folder')
            if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=item.get('sha256'):
                result['version_state']='changed_after_receipt';return result
        result['version_state']='current_version_matched';result['version_evidence']=bound
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description='逐件状态：不从遗漏推定完成，不改案件台账')
    ap.add_argument('action',choices=['show','merge'])
    ap.add_argument('--input',type=Path)
    ap.add_argument('--state',type=Path,default=ITEMS_FILE)
    args=ap.parse_args(argv)
    try:
        data=load_items(args.state) if args.action=='show' else merge_items(args.state,json.loads(args.input.read_text(encoding='utf-8-sig')))
        print(json.dumps(data,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,sqlite3.Error) as exc:
        print(f'逐件状态未完成：{type(exc).__name__}: {exc}；没有据此清空或结清事项',file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
